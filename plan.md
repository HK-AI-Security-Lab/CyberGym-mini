# CyberGym — 三层漏洞挖掘 + 分诊 + 验证方案

目标：在真实开源项目上，做**规模化**的漏洞挖掘、优先级分诊与（最终）真实验证。
不追求更强的单模型，而是研究 **harness（多 agent 协作架构）**：用群体智能跑通
「扫候选 → 辩论筛真伪 → 按危害排优先级 → 真实环境验证」这条链路。
整个系统拆成三层，**层间接口干净、可独立开发/评测/替换**。

**两个 2026 信号定义方向**（详见 `README.md`）：
- **微软 MDASH**：100+ 专职 agent 跑 `Prepare→Scan→Validate→Dedup→Prove` 流水线，CyberGym 拿
  88.45% 榜首——**"the harness is the product, the model is one input"**。
- **Anthropic Mythos**：扫 1000+ 仓库 flag 23,019 issue / 6,202 高危——挖的远多于能修的，**必须分诊**。

```
L3  挖漏洞的模型        用 L2/L1 轨迹蒸馏小模型（Qwen 等）          —— 靠后，需 GPU
L2  推演 + 分诊（重点） Scan→Validate→Dedup→Triage：源码 → 候选 →   —— 已落地单 agent 定位，
                       辩论 → 优先级打分（高/中/低危）                 多 agent 待扩，纯 API
L1  仿真验证（Prove）  真实触发验证：PoC 真能 crash               —— 搁置，需 Docker/执行
```

**层间契约**
- L2 的结论最高只到 `likely`（代码层可定位 + 已分诊打分），**绝不自升级为 `confirmed`**。
- `likely → confirmed` 只能由 L1 在真实环境触发完成；L1 的 prove 成功率反向校准 L2 优先级排序。
- L2/L1 跑出的成功/失败轨迹，就是 L3 的训练数据。

> 旧版 plan（一条龙产品规格，10 个 agent + 知识图谱 + runtime judge，见 `guide.md`）已废弃。
> 它把三层焊死在一条 pipeline，且在「单 agent + 外部记忆能不能 work」都没验证前就上重工程。
> 现在的原则：**先用单 agent 把 L2 定位闭环跑通并可量化，再按 MDASH 思路逐步加 agent。**

---

## L2 — 推演 + 分诊（当前重点）

**定位**：纯推理层（零执行，笔记本可跑）。输入一批已知漏洞版本的真实仓库 + bug 描述
（+ 可选 crash log），输出**带优先级打分的候选漏洞集**：root-cause 位置（file/function/line +
bug_class）+ 可达性/可利用性结论 + 高/中/低危分诊。对应 MDASH 的 `Scan→Validate→Dedup→Triage`。

**核心理念**：模型上下文有限 → 推理状态**外置到共享黑板**，所有 agent 读写同一份记忆，
每步只读紧凑视图、写回结构化 delta。这既是上下文限制的解法，也是多 agent 协作的前提。

**多 agent 设计（详见 `l2/README.md`）**：Auditor×N 找候选 → Debater 正/反方辩论可达性/可利用性
（正反可用不同模型，分歧即信号）→ Dedup 合并等价发现 → Prioritizer 按维度打分
（reachability / precondition / privilege / impact / exploitability）切高/中/低危。
注意 CyberGym 无优先级 ground truth，分诊靠 L1 prove 成功率校准。

### 已完成（= MDASH Scan 阶段的单个 Auditor，见 `l2/README.md`）
- [x] 共享黑板（hypotheses/evidence/graph/notes/todo）
- [x] 工具层（read_file/search_code/list_files + 写记忆 + challenge 雏形 + conclude 门禁）
- [x] 单 agent 推演循环（含预算 + 死循环熔断）
- [x] LLM 封装（yunwu.ai OpenAI 兼容，超时 + 重试，已支持传 model）
- [x] 确定性定位判分（vs patch.diff，file/function/line 三档 + groundedness）
- [x] CyberGym subset 下载器 + batch 聚合脚本
- [x] 端到端跑通 arvo:1065

### 待办（按价值排序）
- [ ] **① 提单 agent 定位准确率 + 跑 baseline**：top-3 多候选、强制先 add_evidence 再 conclude、
      用描述关键词强制 search；批量跑官方 10 条 subset 出 grade 分布。这是 Auditor 底座。
- [ ] **② 加 Debater（正/反方辩论）**：拆 `challenge` 为正反方，正反用不同模型，扛不住反驳降权。
      单仓库内最易出效果、最能体现 MDASH 价值，改动小（复用 memory）。
- [ ] **③ 加 Prioritizer（分诊打分）**：跨 task 按 5 维度打分 → 高/中/低危。需多 task 一起跑。
- [ ] **judge 降噪**：忽略纯注释/版本号 hunk；function 抽取只认真正函数定义。
- [ ] （可选）补一小批 web/应用层 CVE repo，让「文档 vs 代码 gap」成为核心信号。

---

## L1 — 仿真验证 / Prove（搁置）

**定位**：把 L2 的 `likely` 升级为 `confirmed`——在受控环境真实触发漏洞，对应 MDASH 的 **Prove 阶段**。
从确定 benchmark（CyberGym：pre-patch 触发 + post-patch 不触发）入手，判据干净，**最能体现群体智能 +
harness 设计**。CyberGym 自带镜像即现成沙箱。**需要 Docker/编译/执行/可 reset，侵入性强，故暂缓。**

协作形态偏*分工*（非辩论）：InputCrafter 构造触发输入 → Runner 沙箱编译+喂输入 → Verifier 判触发。
占位与设想见 `l1/README.md`。要点：
- [ ] CyberGym 编译沙箱（gcc/clang/ASAN/MSan），喂输入观察 sanitizer 输出
- [ ] PoC 生成与提交（CyberGym：触发 pre-patch crash、不触发 post-patch）
- [ ] 验证结果回填 L2（likely→confirmed/rejected），prove 成功率校准 L2 优先级排序

---

## L3 — 挖漏洞的模型（靠后）

**定位**：用 L2 产出的高质量轨迹，蒸馏/训练能独立承担推演的小模型。**需 GPU 才真正开训**；
只用强 API 模型当 teacher 生成轨迹则不需要 GPU。

占位与设想见 `l3/README.md`。要点：
- [ ] 轨迹数据集：从 L2/L1 的 `runs/` 收集 (成功/失败/反证) trajectory + L1 验证标签
- [ ] teacher-student 蒸馏（teacher = 强 API 模型 / 多 agent ensemble）
- [ ] 首选蒸 **debater student**（任务窄、易学），接回 L2 Validate 跑量
- [x] ~~待澄清 MDASH~~：已确认是微软多 agent harness，属 L2/L1 架构参考，非 L3 蒸馏方案

---

## 硬件 / 成本
- **L2**：笔记本 + LLM API，无需 GPU。当前用 `claude-sonnet-4-6`（快/便宜可换 `claude-haiku-4-5`）。
- **L1**：Docker + 较大 CPU/磁盘，无需 GPU。
- **L3**：仅真正微调时租 GPU。

## 目录
```
l2/      L2 推演 harness（已实现）        l2/README.md  做了什么 + 怎么跑
l1/      L1 环境/仿真（占位，待做）
l3/      L3 模型/蒸馏（占位，待做）
scripts/ download_cybergym.py            数据下载器
data/raw/cybergym_100.json               CyberGym 任务元数据（被 run.py 使用）
tasks/   下载的任务数据（gitignored）      runs/  每次运行产物（gitignored）
guide.md 早期设计文档（历史，仅参考）       dev_log.md  开发日志
```

## 6 月 9 日后续实施 plan：验证优先 + 4 个 multi-agent 版本

目标不是一次性复刻 MDASH 的 100+ agents，而是先把“生成输入 → 真实运行 → 观察结果 → 迭代”的验证闭环搭起来，再连续做 4 个可运行的 multi-agent 版本。原则：**每做一个 agent，就必须能看到它看了什么、提交了什么、为什么被接收或拒绝**。

### 当前基线

现在还不是 MDASH 式多 agent：

- `L2`：单 agent 静态定位 + skill card 注入 + A/B。
- `L1`：动态 Prove runner 已通，可以验证 `vul crash / fix clean`。
- 已有共享 memory / trace / score，但还没有真正的 worker pool、auditor ensemble、正反方 debater、dedup、ranker、InputCrafter。

下面从这个基线开始拆。顺序调整为 **V0 验证优先**：先把真实 Prove loop 跑起来，否则只是静态评估，不是在挖漏洞。

---

## 版本 0：真实验证环境 / PoC 尝试循环

目的：先让模型不要只在脑子里想。最小闭环是：`InputCrafter` 生成候选 PoC → `Runner` 跑 vulnerable → 如果 vul 崩再跑 fixed → `Verifier` 给 confirmed/rejected/inconclusive → 失败原因回给下一轮。

### 新增组件

```text
InputCrafter
  输入：task_id、description、crash log、harness info、上一轮失败反馈
  输出：候选 PoC 文件

Runner / Verifier
  输入：PoC + vul/fix images
  输出：confirmed / rejected / inconclusive
```

### 两种模式

```text
smoke-reference
  用镜像内 /tmp/poc 做 smoke test，只验证 L1 环境和判据是否正常。
  这不是正式评测，因为它等于用官方答案。

llm
  模型只能看 description / crash log / harness 摘要 / 失败反馈。
  不看 patch.diff、不看 fix 源码、不看官方参考 PoC。
```

### 命令行要求

```bash
.venv/bin/python -m l1.loop --task arvo:1065 --strategy smoke-reference --attempts 1
.venv/bin/python -m l1.loop --task arvo:1065 --strategy llm --attempts 5
```

必须打印：

```text
[loop] task=arvo:1065 strategy=llm attempts=5
[input_crafter] attempt=1 strategy=llm wrote poc_001 size=...
[runner] attempt=1 vul_crash=false fix_crash=false verdict=rejected reason=does not crash vulnerable
[input_crafter] feedback attempt=1 reason=...
[runner] attempt=3 vul_crash=true fix_crash=false verdict=confirmed
[loop] final status=confirmed poc=poc_003
```

### 验收

- `smoke-reference` 对 `arvo:1065` 必须 confirmed。
- `llm` 即使不成功，也必须保存每次 PoC、运行结果、失败原因。
- 输出：`console.log`、`attempts.jsonl`、`pocs/poc_*.bin`、`prove_results.jsonl`。

---

## 版本 1：Prepare Worker + 代码结构索引

目的：先解决“agent 看代码时是不是在吞垃圾 token”的问题。agent 不应该直接读全仓库，也不应该只靠 grep。先建结构化 code map，再让后续 agent 只读相关函数。

### 新增组件

```text
Prepare Worker
  输入：task_id、repo-vul、description、error.txt
  输出：
    runs/<task>/code_index/symbols.json
    runs/<task>/code_index/code_map.json
    runs/<task>/code_index/prepare_trace.jsonl
```

最小实现先不用重工程：

- C/C++ 用正则/ctags 风格抽取函数、struct、include、文件列表、函数行号范围。
- 从 crash log 抽取 project frames。
- 从 fuzzer/harness 文件识别入口：`LLVMFuzzerTestOneInput`、`/out/*_fuzzer`。
- 生成候选 upstream functions：基于 crash frame、同名 wrapper、调用文本引用、skill card 关键词。

后续再接 tree-sitter / CodeQL / clangd，不第一步就上重依赖。

### Prepare 输出 schema

```json
{
  "task_id": "arvo:1065",
  "entrypoints": [
    {"kind": "fuzzer", "file": "magic_fuzzer.cc", "function": "LLVMFuzzerTestOneInput"}
  ],
  "files": [
    {"path": "src/funcs.c", "language": "c", "functions": ["file_regexec"]}
  ],
  "functions": [
    {"name": "file_regexec", "file": "src/funcs.c", "start": 508, "end": 514}
  ],
  "crash_frames": [
    {"file": "src/softmagic.c", "function": "magiccheck", "role": "symptom"}
  ],
  "candidate_scopes": [
    {"file": "src/funcs.c", "function": "file_regexec", "reason": "MSan pmatch/regexec wrapper"}
  ]
}
```

### 命令行要求

运行时必须能看到进度：

```bash
.venv/bin/python -m l2.prepare --task arvo:1065 --verbose
```

控制台必须打印：

```text
[prepare] task=arvo:1065 source=tasks/arvo_1065/repo-vul
[prepare] files=123 c_files=57 functions=821
[prepare] crash_frames=7 project_frames=5
[prepare] entrypoints=1 candidate_scopes=12
[prepare] wrote runs/.../code_index/code_map.json
```

### 验收

- `arvo:1065` 能产出 `code_map.json`。
- 后续 Auditor 不再从空白仓库开始，而是先读 `code_map`。
- 运行失败要在命令行看到具体卡在哪个文件、哪个阶段。

---

## 版本 2：Auditor Ensemble（3 个并行 auditor）

目的：先做真正的“多 agent 干活”。不是一个 agent 多想几次，而是多个 auditor 用不同视角、不同 scope、不同 skill card 产出候选。

### 三类 Auditor

```text
Auditor-A: crash-guided
  只看 crash frames + 上下游函数
  目标：从症状回溯 root cause

Auditor-B: structure-guided
  只看 Prepare 生成的 candidate_scopes / code_map
  目标：从代码结构找 wrapper、parser、boundary check

Auditor-C: skill-guided
  只看 bug-class skill card + 相关函数
  目标：按 MSan/UAF/OOB/null-deref playbook 找候选
```

### Orchestrator 行为

```text
Orchestrator
  1. 读取 code_map
  2. 给每个 auditor 分配不同 context
  3. 并行或串行启动 auditor worker
  4. 收集 worker 输出的 hypotheses
  5. 写入 shared blackboard
```

### 记忆隔离

每个 auditor 有自己的 local scratchpad：

```text
runs/<task>/workers/auditor_crash/trace.jsonl
runs/<task>/workers/auditor_structure/trace.jsonl
runs/<task>/workers/auditor_skill/trace.jsonl
```

它们不能互相读 scratchpad，只能把结构化结果提交到：

```text
runs/<task>/blackboard/hypotheses.jsonl
runs/<task>/blackboard/evidence.jsonl
```

提交格式：

```json
{
  "worker": "auditor_skill",
  "type": "hypothesis",
  "file": "src/funcs.c",
  "function": "file_regexec",
  "line": 508,
  "bug_class": "use-of-uninitialized-value",
  "claim": "pmatch should be zero-initialized before regexec",
  "evidence_refs": ["ev_12", "ev_15"],
  "confidence": 0.78
}
```

### 命令行要求

```bash
.venv/bin/python -m l2.multi_run --task arvo:1065 --version v2 --verbose
```

控制台必须打印每个 worker 的状态：

```text
[orchestrator] stage=prepare done code_map=...
[orchestrator] start worker=auditor_crash scope=5 functions budget=8
[worker:auditor_crash] read src/softmagic.c:1680-1920
[worker:auditor_crash] submit hypothesis h1 file=src/softmagic.c fn=magiccheck conf=0.42
[orchestrator] start worker=auditor_skill cards=msan-uninitialized budget=8
[worker:auditor_skill] read src/funcs.c:480-530
[worker:auditor_skill] submit hypothesis h2 file=src/funcs.c fn=file_regexec conf=0.78
[orchestrator] hypotheses=4 evidence=9
```

### 验收

- 至少 3 个 auditor worker 都能独立产出 trace。
- blackboard 能合并它们的 hypotheses。
- `score.json` 能对 ensemble 的 top-k 做判分。

---

## 版本 3：Evidence Checker + Ranker

目的：不做“多个模型讨论/争论”。讨论分歧本身不可靠，容易变成 LLM 互相编理由。这里改成 **Evidence Checker / Skeptic Verifier**：只检查证据缺口和硬约束，证据缺口才是信号。

### 新增组件

```text
Evidence Checker
  输入：每个 hypothesis + evidence + code snippets
  目标：检查没读过行、非项目代码、fuzzer wrapper、crash site 冒充 root cause、bug class 不匹配、缺上游证据
  输出：checks / missing_evidence / confidence adjustment

Ranker
  输入：hypotheses + evidence checks
  输出：ranked_findings.json
```

### Evidence Checker 只看有限上下文

它不重扫仓库，也不发表“不同观点”，只看：

- hypothesis
- evidence refs 指向的代码片段
- crash log 摘要
- code_map 中相关函数签名
- skill card 的反例规则

不允许它自由读全仓库，避免无限扩散。

### check schema

```json
{
  "worker": "evidence_checker",
  "hypothesis_id": "h2",
  "checks": {
    "line_read": true,
    "is_project_code": true,
    "is_not_fuzzer_wrapper": true,
    "bug_class_matches_crash": true,
    "has_upstream_evidence": false
  },
  "verdict": "weak",
  "missing_evidence": [
    "No evidence that this is upstream of the MSan origin"
  ],
  "confidence_delta": -0.25
}
```

### Ranker 输出

```json
{
  "ranked": [
    {
      "hypothesis_id": "h2",
      "final_confidence": 0.81,
      "decision": "likely",
      "why": "MSan origin + wrapper evidence; checker found no hard blocker"
    }
  ]
}
```

### 命令行要求

```bash
.venv/bin/python -m l2.multi_run --task arvo:1065 --version v3 --verbose
```

必须打印：

```text
[evidence_checker] check h1 verdict=weak missing=upstream_evidence delta=-0.30
[evidence_checker] check h2 verdict=strong no_hard_blocker
[ranker] top1=h2 file=src/funcs.c fn=file_regexec conf=0.81
[judge] grade_top1=line grade_any=line
```

### 验收

- 能看出 Evidence Checker 是否真的改变了排名。
- 和 v2 对比：`grade_top1` 或 `grade_any` 是否提升。
- 保存 `evidence_checks.jsonl`，后续可做 checker/ranker 训练数据。

---

## 版本 4：InputCrafter + L1 Prove 闭环

目的：最终不要只看 patch 定位，要看 PoC 是否真实触发。这个版本把 L2 的 likely 候选接到 L1。

### 新增组件

```text
InputCrafter
  输入：top-k likely findings、bug class、harness info、seed/ref_poc、crash log
  输出：candidate PoC files

Runner / Verifier
  输入：PoC + vul/fix images
  输出：confirmed / rejected / inconclusive
```

### InputCrafter 权限

InputCrafter 不读全仓库，只看：

- top-k findings
- crash log
- harness 类型：libFuzzer / honggfuzz / CLI / HTTP
- seed corpus / `/tmp/poc` 参考输入（如果有）
- 相关文件格式文档（如果有）

### Prove 结果回填

```json
{
  "finding_id": "h2",
  "poc_id": "poc_003",
  "vul": {"crashed": true, "sanitizer": "msan", "exit_code": 77},
  "fix": {"crashed": false, "exit_code": 0},
  "verdict": "confirmed"
}
```

### 命令行要求

```bash
.venv/bin/python -m l2.multi_run --task arvo:1065 --version v4 --prove --verbose
```

必须打印：

```text
[input_crafter] finding=h2 strategy=mutate_seed seed=/tmp/poc attempts=5
[runner] poc=poc_001 vul_crash=false fix_crash=false verdict=rejected
[runner] poc=poc_003 vul_crash=true fix_crash=false verdict=confirmed
[orchestrator] final status=confirmed finding=h2 poc=poc_003
```

### 验收

- 至少对 `arvo:1065` 能从候选 finding 走到 L1 prove。
- 先允许用参考 PoC/seed 做 smoke test，再逐步让 InputCrafter 自己生成。
- 输出 `prove_results.jsonl`。

---

## 统一 Orchestrator / Worker 设计

不先上 HTTP server。第一阶段用本地进程 orchestrator，后续再 server 化。

```text
l2/multi_run.py
  Orchestrator 状态机
  stage: prove_loop -> prepare -> audit -> check -> rank -> prove

l2/workers/
  prepare.py
  auditor.py
  evidence_checker.py
  ranker.py
  input_crafter.py

runs/<task>_<ts>/
  console.log
  orchestrator_trace.jsonl
  code_index/
  workers/
  blackboard/
  score.json
  ranked_findings.json
  prove_results.jsonl
```

### Orchestrator 负责

- 分配 worker。
- 控制每个 worker 的 token / steps / timeout。
- 给 worker 裁剪上下文。
- 校验 worker 输出 schema。
- 接收或拒绝 delta。
- 打印实时日志。

### Worker 负责

- 只完成一个角色的工作。
- 只能看到分配给它的 context bundle。
- 只能写自己的 trace 和提交结构化 delta。
- 不允许直接改最终结论。

---

## 记忆与权限隔离

```text
Global Task State
  - task_id
  - level
  - model config
  - build/harness metadata
  - selected skill cards
  - stage status

Evidence Store
  - code snippets
  - crash frames
  - symbol/function records
  - source-to-sink notes
  - PoC replay results

Worker Local Scratchpad
  - worker 私有推理
  - worker 自己的 read history
  - worker 自己的失败/重试记录
```

权限规则：

- Prepare 可以读 repo 全量，但输出必须是结构化 index，不把全量源码塞给 LLM。
- Auditor 只能读 code_map 分配到的 scope，再按需 read_file。
- Evidence Checker 默认不能自由搜全仓库，只能围绕 hypothesis 的 evidence 做硬检查。
- Ranker 不能读新代码，只能读 blackboard。
- Runner / Verifier 不需要 LLM。
- InputCrafter 只读 top findings + harness/seed，不读无关代码。

---

## 代码阅读策略：AST / code map 优先

后续所有 agent 看代码都按这个流程：

```text
repo
  -> Prepare Worker 建 code_map
  -> Orchestrator 选 scope
  -> Auditor 读函数摘要 / 函数范围
  -> 必要时 read_file 精读具体行
```

禁止：

```text
把整个仓库直接塞给模型
```

允许：

```text
code_map 摘要 + relevant snippets + read_file 精读
```

短期实现：

- Python 正则/轻量 parser 抽 C/C++ 函数范围。
- 从 crash log 抽函数名。
- 用 rg/search_code 找引用。

中期实现：

- tree-sitter。
- universal-ctags。
- compile_commands.json。

长期实现：

- CodeQL DB。
- clangd index。
- source-to-sink dataflow。

---

## 命令行可观测性要求

以后写代码时，所有长流程必须让命令行看到它在干什么。

每个阶段必须打印：

```text
[stage] start/end
[worker] start/end
[worker] read file/range
[worker] submit hypothesis/challenge/ranking
[orchestrator] accept/reject delta
[judge] score
[runner] vul/fix result
```

所有 run 必须保存：

```text
console.log
orchestrator_trace.jsonl
workers/<worker>/trace.jsonl
blackboard/hypotheses.jsonl
blackboard/evidence.jsonl
score.json
```

如果后台跑，必须让用户知道：

```text
现在在跑哪个 task
预计多久
日志在哪里
结束后结果在哪里
```

---

## 实施顺序

1. **V0 Real Prove Loop**
   - 新增 `l1/input_crafter.py`
   - 新增 `l1/loop.py`
   - 先跑 `smoke-reference` 验证环境，再跑 `llm` 策略收集失败原因

2. **V1 Prepare Worker**
   - 新增 `l2/prepare.py`
   - 生成 `code_map.json`
   - 命令行可见 prepare 进度

3. **V2 Auditor Ensemble**
   - 新增 `l2/multi_run.py`
   - 新增 3 个 auditor profile
   - 合并 hypotheses 到 blackboard

4. **V3 Evidence Checker + Ranker**
   - 新增 `evidence_checks.jsonl`
   - top-k 重新排序
   - 对比 v2/v3 分数

5. **V4 InputCrafter + L1 Prove**
   - 把 ranked finding 接到 `l1.run`
   - 先用 seed/ref_poc smoke test
   - 再做自动 PoC 生成

6. **实验**
   - 每版先跑 `arvo:1065`
   - 再跑官方 9/10 task subset
   - 指标：`grade_top1`、`grade_any`、groundedness、confirmed rate、失败归因

这个计划完成后，才算从“单 agent MVP”走到“可实验的 MDASH-like harness”。