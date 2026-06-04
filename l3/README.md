# L3 — 挖漏洞的模型（占位，待做）

**定位**：用 L2/L1 产出的高质量轨迹，蒸馏/训练能独立承担推演的小模型（Qwen 等），
让「挖漏洞」不必每次都依赖最强的 API 模型。

**为什么靠后**：需要先有一个能 work、能产出大量轨迹的 L2（最好已带 L1 验证标签），才有训练数据。
只用强 API 模型当 teacher 生成轨迹时**不需要 GPU**；真正做 SFT/蒸馏时才租 GPU。

## MDASH 已澄清（不是蒸馏架构）

之前待澄清的"MDASH 微软架构"已确认：它是微软的 **multi-model agentic scanning harness**
（多模型 agent 协作*流水线*，见 2026-05-12 博客），属于 **L2/L1 的 harness 设计参考**，
**不是 L3 的蒸馏方案**。MDASH 对 L3 的唯一启示是它的模型分工：

- 强 SOTA 模型当 **heavy reasoner**（≈ L2 Auditor）
- 蒸馏小模型当 **cost-effective debater** 跑高频/高量的辩论 passes
- 第二个独立 SOTA 当 **counterpoint**（反方）

→ **L3 的产物（蒸馏小模型）正好可以填 MDASH 里"debater 跑量"这个角色**：用便宜的 student
承担高频辩论，把贵的强模型留给 heavy reasoning。这是 L3 与 L2 架构的衔接点。

## teacher / student 方向（初定）

- **teacher**：L2 的强 API 模型 / 多 agent ensemble（auditor + debater 的完整轨迹）
- **student**：Qwen 等开源模型，先做 behavior cloning / SFT
- **首个目标角色**：不是一上来就替代 reasoner，而是先蒸出一个够用的 **debater student**（任务更窄、
  更容易学），接进 L2 Validate 阶段跑量。

## 待办（设想）
- [ ] 轨迹数据集：从 `runs/` 收集 (成功 / 失败 / 反证 / alternate-path) trajectory，
      含每步 (状态, 动作, observation)、最终 grade，以及（若有）L1 的 confirmed/rejected 标签
- [ ] teacher 设定：强 API 模型 / 多 agent ensemble
- [ ] student：Qwen 等做 SFT / behavior cloning，首选蒸 debater 角色
- [ ] held-out 评测：用没训过的 task，比 student 与 teacher 的定位准确率 / 辩论质量
- [ ] 把 debater student 接回 L2 Validate，验证"便宜跑量"是否成立

## 接口（与 L2/L1）
- 输入：L2 的 `runs/` 轨迹（trace.jsonl + 黑板快照 + score.json）+ L1 的验证标签
- 输出：可替换进 `l2/llm.py` 的 student 模型 endpoint（先用于 debater 角色）
