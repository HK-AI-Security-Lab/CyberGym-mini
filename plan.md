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
