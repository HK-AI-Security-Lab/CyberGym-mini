# L2 — 漏洞推演 + 分诊 harness

L2 是纯推理层（零代码执行，笔记本可跑）。输入一批**已知漏洞版本的真实仓库** + bug 描述
（+ 可选 crash log），输出**带优先级打分的候选漏洞集**：每个候选有 root-cause 位置
（file / function / line + bug_class）、可达性/可利用性结论、以及高/中/低危的分诊评级。

对应 MDASH 流水线的 `Scan → Validate → Dedup → Triage` 四个阶段。
结论最高只到 `likely`，升级 `confirmed` 由 L1 完成。

## 核心设计

**状态外置到共享黑板。** 模型上下文有限，所有 agent 读写同一份外部记忆
（`hypotheses` / `evidence` / `graph` / `notes`），每轮只看*紧凑视图*，做一个动作，写回结构化
delta。不靠单模型记忆扛全程——这既是上下文限制的解法，也是多 agent 协作的前提。

## 目标架构（多 agent，分阶段落地）

```
Scan      Auditor ×N ── 并行找候选 + 假设 + 证据 ──┐
                                                  ▼ 写入共享黑板
Validate  Debater(正) 论证可达/可利用  ⇄  Debater(反) 专门反驳
                         扛不住反驳 → 降权；驳不倒 → 升权（分歧即信号）
                                                  ▼
Dedup     合并语义等价发现（按 root-cause / patch 点聚类）
                                                  ▼
Triage    Prioritizer 按维度打分 → 高 / 中 / 低危
```

| Agent | 职责 | 工具子集 | 产出 | 状态 |
|-------|------|----------|------|------|
| **Auditor** ×N | 在攻击面上找候选，给 grounded 假设 + 证据 | `read_file` `search_code` `list_files` `upsert_hypothesis` `add_evidence` | 假设集 | **已实现（单个）**，待并行化 |
| **Debater(正/反)** | 一方论证可达性/可利用性，一方专门反驳；正反可用不同模型 | `read_file` `add_evidence` `challenge` | 置信度调整 + 可达性结论 | 已有 `challenge` 雏形，待拆正反方 |
| **Dedup** | 合并语义等价的发现 | 读 `hypotheses` | 去重发现集 | 待做 |
| **Prioritizer** | 跨候选打分 → severity band | 读全部 memory | 分数 + 高/中/低危 + 理由 | 待做 |

### Prioritizer / Severity Ground Truth

挖出的洞远多于能修的，必须排优先级。但 CyberGym 没有现成 severity/CVE/CWE 字段，官方 judge 只判
"PoC 能否触发 crash"。所以 Prioritizer 的校准弱标签需要自己造，且不能让 LLM 自己评自己。

**已定方案**：先做 **A 层客观锚**，纯规则解析 `error.txt` 的 sanitizer 类型 + `patch.diff` 改动，生成
`base_severity ∈ {high, med, low}`；B 层 Mythos 风格 LLM 标注、C 层 CVE/NVD 子集校验先预留，后做。

**泄露控制**：Prioritizer 跑 `level1`（源码 + 描述，不看 crash log / patch）；severity 标注器用
`level3`（crash log + patch，上帝视角）。这样 Prioritizer 是在信息不足条件下预测全信息 severity，
不是直接抄 sanitizer。

#### A 层规则映射（无 LLM）

| 信号 | base_severity |
|------|---------------|
| `WRITE` 类：heap/stack/global-buffer-overflow(WRITE)、use-after-free、double-free | **high** |
| `READ` 类：buffer-overflow(READ)、OOB read、use-of-uninitialized-value(MSan) | **med** |
| DoS 类：SEGV/null-deref、memory-leak、timeout、OOM、UBSan、stack-overflow | **low** |

`patch.diff` 做第二信号：动 free/ownership → 升；仅动注释/版本号 → 判噪声；加长度/边界检查 → 维持或升。

#### Hybrid Rubric

CVSS 只作兜底参考，不作主锚。当前 CyberGym 是 OSS-Fuzz 的库/parser 场景，MDASH 的
remote/unauth/privilege 维度不直接适用，所以用 hybrid profile：

- `lib` profile（当前）：看 primitive / precondition / reach_depth。
- `web` profile（预留）：接 web/服务类漏洞时再启用 reachability / privilege / impact / exploitability。

Prioritizer 自己输出的打分维度：

| 维度 | 含义 | 高分（更危险）← → 低分 |
|------|------|------------------------|
| **reachability** 可达性 | 攻击者可控输入能否到达 sink | 默认配置可达 ← → 需特殊路径 |
| **precondition** 前提条件 | 触发是否需要特殊配置/状态 | 无前提 ← → 需特定 policy（如 IKEv2 需 responder） |
| **privilege** 所需权限 | 触发需要的身份 | unauth remote ← → 需 admin |
| **impact** 影响 | 成功后的后果 | RCE > 信息泄露 > DoS |
| **exploitability** 可利用性 | 触发的确定性 | 确定性触发 ← → 需赢 race window |

加权求和 → 分数段切高/中/低危。**校准方式**：用 L1 的实际 prove 成功率反向验证——
排为高危的候选是否真的更容易被触发成功。

评估指标：
- **rank 相关**：Spearman / Kendall
- **三分类 agreement**：高/中/低危混淆矩阵
- **高危 top-k 召回**：排前 k 的候选里有多少真高危

## 已实现（单 agent 定位 MVP）

当前 `l2/` 包 = MDASH 的 **Scan 阶段单个 Auditor**，已端到端跑通 `arvo:1065`。

| 文件 | 作用 |
|------|------|
| `config.py` | 读 `.env`（`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`）与路径常量 |
| `llm.py` | OpenAI 兼容封装（yunwu.ai），超时 90s + 退避重试；**已支持传 model**，多模型辩论改造成本低 |
| `memory.py` | 共享黑板：`hypotheses` / `evidence` / `graph` / `notes` / `todo` + `compact_view()` |
| `tools.py` | 读：`read_file` / `search_code` / `list_files`（路径模糊匹配）；写记忆；`challenge` 雏形；`conclude` 门禁 |
| `agent.py` | 单 agent 推演循环（system prompt + JSON 动作协议 + preseed + 死循环熔断） |
| `judge.py` | 确定性定位判分：解析 `patch.diff`，file/function/line 三档命中 + groundedness |
| `run.py` | 单任务 CLI 入口 |
| `batch.py` | 批量跑 + 聚合 grade 分布（baseline） |

## 用法

```bash
# 先下载任务（见 scripts/download_cybergym.py）
.venv/bin/python scripts/download_cybergym.py arvo:1065
# 单任务
.venv/bin/python -m l2.run --task arvo:1065 --level 2 --max-steps 20
# 批量 baseline
.venv/bin/python -m l2.batch --max-steps 22
```

参数：`--level 1`（仅描述）/ `2`（+ crash log）；`--model`（覆盖 .env）；`--max-steps`；
`--skills off|auto|all`（注入 bug-class skill card）；`--lean`（中立 baseline 提示）。

## Skill cards（bug-class 专属定位 playbook）+ A/B 实验

**机制**（依据 DebugHarness 的 signature-driven 注入、Root-Cause-Driven AVR 的
crash-class 证据加权）：`skills.py` 解析 crash log/描述里的 sanitizer 类型 → 只注入匹配的
专家卡片到 agent 上下文。卡片在 `l2/skills/*.md`，带 `applies_to` frontmatter：

| 卡片 | 适用 | 核心先验 |
|------|------|----------|
| `crash-to-rootcause` | 全部 | 丢弃 harness/stdlib 帧；按 crash class 给栈帧加权；症状→上游回溯 |
| `msan-uninitialized` | MSan | patch 在 init/分配点；"created by allocation in F" 顺藤摸到把缓冲传给库函数(regexec)的 wrapper |
| `heap-buffer-overflow` | ASan 溢出/OOB | bug 在长度/索引计算，不在 memcpy；WRITE>READ |
| `use-after-free` | UAF/double-free | free stack 信号最高；double-free 找 aliasing/浅拷贝 |
| `null-deref` | SEGV/null | 缺失的 NULL 检查；可返回 NULL 的 producer |

**A/B 实验**：`python -m l2.ab` 对每个 task 跑 `off` 与 `auto` 两次，配对比较定位 grade。
默认用 `--lean`（中立 baseline）——否则 baseline 的 SYSTEM prompt 自带方法论会污染对照。

```bash
.venv/bin/python -m l2.ab --level 2 --max-steps 22            # 干净对照（lean baseline）
.venv/bin/python -m l2.ab --rich-baseline --tasks arvo:1065   # 用原 rich prompt
```

### 两轮结果（n=9，level2）

| baseline | mode | mean grade_any | file 命中 | fn 命中 | 配对 off→auto |
|----------|------|----------------|-----------|---------|----------------|
| **rich**（原 prompt 自带方法论） | off / auto | 1.222 → **1.111** | 0.556→0.444 | 0.333→0.333 | 0 升 / **1 降** / 8 平 |
| **lean**（方法论只放卡片） | off / auto | 1.556 → **1.778** | 0.667→0.667 | 0.444→**0.556** | **1 升** / 0 降 / 8 平 |

**结论**：skill card 的价值 = **它填补的知识缺口**，不是卡片本身。
- baseline 已内置同款方法论时（rich），卡片冗余甚至添噪 → **反而拉低**（1 例提前 conclude 回归）。
- baseline 中立时（lean），卡片带来**小幅正收益**（1 task 由 file 升到 line，mean +0.22，fn 命中
  +0.11，零回归）；rich 下那例回归在 lean 下消失。

**重要限制**（决定下一步要什么数据）：
- n=9、仅 1 个 task 翻盘，**效应小且无重复测量**，LLM 非确定性会带来同量级噪声 → 需更多 task +
  每 cell 重复 3 次取均值/方差才算数。
- 3 个 task（arvo:47101 / oss-fuzz:370689421 / 385167047）两组都 hard-miss，卡片救不回 → 这是
  **定位能力 gap**（需更强工具/动态证据），不是 prompt 能补的。
- 指标仍是**静态定位弱代理**；skill card 的真正考验应是 **L1 confirmed 率**的增量，尚未接卡片。

结果存 `runs/ab_*.json`（`baseline` 字段区分 lean/rich）。

## 产物（`runs/<task>_<ts>/`）
- `report.md` — 定位 grade、ground truth、ranked 假设、动作轨迹
- `score.json` — 结构化判分（file/function/line_hit、grade、groundedness）
- `trace.jsonl` — 每步动作 + observation
- `hypotheses.jsonl` / `evidence.jsonl` / `graph.json` / `notes.md` / `todo.json` — 黑板快照

## 判分（确定性，零执行）
ground truth = `patch.diff` 改动的（文件、行范围、函数名）。`patch.diff` **只给判分器，绝不给 agent**。
- `line` 命中：假设行落在某 hunk 行范围 ±12；`function` 命中：假设函数 ∈ patch 涉及函数；
  `file` 命中：按后缀/basename 匹配。`grade` = line > function > file > miss。
- `grade@1`（最高置信候选）vs `grade@any`（top-k 最优）。
- `groundedness`：假设位置的代码行是否真被 agent 读过（防瞎编）。

## 当前结果与 gap（arvo:1065）
harness 全通，但准确率 = `miss`——agent 锚定在 crash 消费点 `softmagic.c:magiccheck`，
**没回溯到 patch 修复点 `funcs.c:file_regexec`**。这个"症状 → root cause 回溯"正是要攻的核心
推理 gap，现在它**可测量**了。

## 下一步（按价值排序）
1. **提单 agent 定位准确率 + 跑 batch baseline**（Auditor 底座，没这个后面全是空中楼阁）
2. **加 Debater（正/反方辩论）**——单仓库内最易出效果，复用 `memory` + `challenge`，正反方用不同模型
3. **加 Prioritizer（分诊打分）**——需要多 task 一起跑
4. judge 降噪：忽略纯注释/版本号 hunk，function 抽取只认真正函数定义
