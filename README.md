# CyberGym

在真实开源项目上做**规模化漏洞挖掘 + 分诊 + 验证**的实验平台。

不追求"一个更强的模型"，而是研究 **harness（agent 协作架构）**：用一群专职 agent 的群体智能，
把"扫出一堆候选漏洞 → 辩论筛真伪 → 按危害排优先级 → 真实环境验证"这条链路跑通。

## 为什么是 harness 而不是模型

两个 2026 年的信号定义了这个方向：

- **微软 MDASH**（multi-model agentic scanning harness）：编排 100+ 专职 agent 跑一条
  `Prepare → Scan → Validate → Dedup → Prove` 流水线，在公开 benchmark **CyberGym 上拿到 88.45%
  榜首**，用的还是通用模型。结论一句话：**"the harness is the product, the model is one input"**——
  价值在模型外面的系统，不在某个具体模型。
- **Anthropic Mythos**：扫 1000+ 仓库 flag 出 **23,019 个 issue，其中 6,202 高/危**。挖出来的洞
  远多于能修的 → **必须做优先级分诊**，否则就是一个没人能消化的 triage backlog。

CyberGym 把这两点合到一起：**MDASH 式的多 agent 协作** + **Mythos 式的规模化优先级分诊**。

## 三个核心设计理念

1. **群体智能 / 分歧即信号**：auditor 提候选、debater 正反方辩论，扛不住反驳的降权；正反方可用
   *不同模型*，模型间分歧本身就是可利用的信号。不是"单 agent 多调几次"，而是角色分工 + 对抗。
2. **专职 agent**：auditor ≠ debater ≠ prioritizer ≠ prover，各有自己的 prompt、工具子集、停止条件。
   不指望一个 prompt 干完全部。
3. **状态外置到共享黑板**：所有 agent 读写同一份外部记忆（hypotheses / evidence / graph），
   不靠单个模型的上下文扛全程。这也是规模化的前提。

**层间契约**：L2 结论最高只到 `likely`（代码可定位 + 已分诊打分），升级到 `confirmed` 只能由
L1 真实触发完成；L2/L1 的成功/失败轨迹是 L3 的训练数据。

## 三层架构（MDASH 5 阶段的映射）

```
一批仓库
  │
  ├─ L2 推演 + 分诊（纯推理，已落地单 agent 定位，待扩为多 agent）────────────────┐
  │    Prepare   画攻击面 / 读历史 commit                                          │
  │    Scan      Auditor ×N 并行找候选 + 假设 + 证据                                │
  │    Validate  Debater 正/反方辩论可达性 & 可利用性 → 调整置信度                  │
  │    Dedup     合并语义等价的发现（按 root-cause 聚类）                           │
  │    Triage    Prioritizer 按维度打分 → 高 / 中 / 低危                             │
  │                         │ 只把"高危 + 前提可满足"的候选送下去                   │
  ├─ L1 仿真验证（搁置，最能体现群体智能 + Prove）──────────────────────────────┐ │
  │    Prove     编译漏洞版本 → 构造触发输入 → 喂 sanitizer                        │ │
  │              pre-patch 触发 + post-patch 不触发 = confirmed                    │ │
  │                         │ 实际 prove 成功率反过来校准 L2 的优先级排序           │ │
  └─ L3 挖漏洞的模型（靠后）────────────────────────────────────────────────────┘ │
       用 L2/L1 的轨迹蒸馏小模型（需 GPU）                                           │
```

| 层 | 做什么 | MDASH 阶段 | 需要什么 | 状态 |
|----|--------|-----------|----------|------|
| **L2** 推演 + 分诊 | 源码 → 候选漏洞 → 辩论 → 优先级打分 | Scan / Validate / Dedup / Triage | 只要 LLM API + 文件工具 | **已落地单 agent 定位 MVP**，多 agent 待扩 |
| **L1** 仿真验证 | 真实触发：PoC 真能 crash | Prove | Docker / 编译 / 执行 | 搁置 |
| **L3** 挖漏洞模型 | 用轨迹蒸馏小模型 | — | GPU（仅真正微调时） | 靠后 |

> 落地优先级：① 先把单 agent 定位准确率打上去 + 跑 batch baseline（Auditor 底座）
> → ② 加 Debater（单仓库内最易出效果）→ ③ 加 Prioritizer（你要的分诊打分）
> → ④ 最后做 L1 Prover（工程最重）。

每层的具体设计与现状见各自 README：
[`l2/README.md`](l2/README.md) ·
[`l1/README.md`](l1/README.md) ·
[`l3/README.md`](l3/README.md)。整体路线图见 [`plan.md`](plan.md)。

## 快速开始（L2，当前可跑）

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # 填入 LLM_API_KEY（base url 默认 https://yunwu.ai/v1）

# 下载一个任务（仅小文件：源码 + patch + 描述，不是 240GB 全量）
.venv/bin/python scripts/download_cybergym.py arvo:1065

# 跑推演 + 判分，产物落在 runs/<task>_<ts>/
.venv/bin/python -m l2.run --task arvo:1065 --level 2 --max-steps 20
```

## 目录

```
l2/        L2 推演 + 分诊 harness（已实现单 agent 定位）
l1/        L1 仿真验证（占位，待做）
l3/        L3 模型/蒸馏（占位，待做）
scripts/   download_cybergym.py    数据下载器
data/raw/  cybergym_100.json       CyberGym 任务元数据
tasks/     下载的任务数据（gitignored）
runs/      每次运行产物（gitignored）
plan.md    三层方案与路线图
dev_log.md 开发日志        guide.md 早期设计（历史参考，已废弃）
```
