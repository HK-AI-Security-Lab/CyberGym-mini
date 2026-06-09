# L1 — 仿真验证（Prove 阶段，最小闭环已跑通）

**定位**：把 L2 的 `likely`（代码层定位 + 已分诊）升级为 `confirmed`——在受控环境**真实触发**漏洞。
对应 MDASH 流水线的 **Prove 阶段**：把候选 PoC 喂进 vul/fix 两个构建，看 sanitizer 是否真 crash。
这是 L2 与「真相」之间唯一的桥：没有真实触发，就只能停在静态推断。

**为什么从确定 benchmark 入手**：CyberGym/ARVO 自带每个漏洞的 Docker 镜像（vul + fix），且有
干净的成功判据（**pre-patch 触发 + post-patch 不触发 = confirmed**）。判据干净才最能体现
harness 的价值，也才能 A/B 测出 skill card / 多 agent 的增量。

## 已实现（最小 Prove 闭环，实测跑通 arvo:1065）

```
l1/
  sandbox.py  唯一碰 Docker 的层：拉镜像 / 发现 /out 下 fuzz target /
              把候选 PoC 覆盖到 /tmp/poc，用镜像自带 `arvo run`（保证 MSAN/ASAN
              _OPTIONS 等环境一致）复现，解析 exit code + sanitizer 特征判 crash
  prove.py    编排 vul/fix 对照 → verdict(confirmed/rejected/inconclusive) + reason
  run.py      CLI：python -m l1.run --task arvo:1065 --poc <file>
  input_crafter.py  V0 PoC 候选生成：smoke-reference / llm / fallback-pattern
  loop.py     V0 真实验证循环：InputCrafter → Runner/Verifier → 反馈
```

用法：
```bash
# 用 ARVO 镜像内置的参考 PoC 自检（从 vul 镜像 /tmp/poc 拷出）
.venv/bin/python -m l1.run --task arvo:1065 --poc <poc_file>

# V0：真实验证 loop。smoke-reference 只验证环境，llm 才是正式尝试入口
.venv/bin/python -m l1.loop --task arvo:1065 --strategy smoke-reference --attempts 1
.venv/bin/python -m l1.loop --task arvo:1065 --strategy llm --attempts 5
```

**实测结果（arvo:1065，libmagic MSan）**：
- 参考 PoC（12B）→ VUL crash(MSan,exit77) + FIX clean(exit0) → **CONFIRMED**
- 随机 12B 垃圾 → VUL 不 crash → **REJECTED**（判据有区分度，不误报）
- V0 loop 已实测：`smoke-reference` confirmed；`fallback-pattern` rejected；`llm` 在 API 网络 EOF 时自动降级并继续真实 runner，不让流程崩掉
- 单次复现 ~1-2s（amd64 模拟对小输入无瓶颈）

## 实际运行中发现的细化工程需求（探路产出）

| 发现 | 对大规模研究的含义 |
|------|--------------------|
| 每个 task 的 prove 只需 **ARVO vul/fix 镜像对**（各 ~1-2GB），**不需要 10TB 全量 server data** | prove 环境按需拉镜像即可，成本可控；10TB 是误导项 |
| Docker Hub registry 从本网络**频繁 503/截断**，官方源不可用 | 必须配**国内镜像源/私有 registry mirror**（实测 `docker.m.daocloud.io` 可用）；大规模需自建 registry 缓存 |
| ARVO 镜像 `/bin/arvo` 已封装**精确 sanitizer 环境 + FUZZING_ENGINE**（此例 libfuzzer/memory） | 复现必须沿用镜像自带 env，**不能自己拼**；harness 格式（libFuzzer vs honggfuzz）必须尊重，否则本对的 PoC 会假失败（MDASH 失败分析同款坑） |
| 镜像内 `/tmp/poc` 是**官方参考触发输入** | 可当 oracle / seed，给 InputCrafter 当起点或回归基线 |
| arm64 Mac 跑 amd64 镜像靠模拟，小输入 1-2s OK | 真要批量/长跑 fuzzing，需 **amd64 主机**，不能靠笔记本模拟 |

## 在多 agent 架构里的位置

L2 把"高危 + 前提可满足"的候选送进来，L1 只对这批候选做动态验证，省算力。

```
L2 Prioritizer ──(高危候选 + 触发思路)──▶ L1 Prove ──(confirmed / rejected)──┐
                                                                              │
        ▲ 实际 prove 成功率反向校准 L2 的优先级排序 ◀─────────────────────────┘
```

**协作形态**：L1 的群体智能更多是*分工*而非辩论——
- **InputCrafter**：按候选的 bug_class 构造触发输入（overflow→超长输入、UAF→特定时序）
- **Runner**：在沙箱编译 + 喂输入，收集 sanitizer 输出
- **Verifier**：判 pre-patch 触发 / post-patch 不触发，给出 confirmed/rejected
- （可选）**领域插件**：注入模型不懂的领域知识（如特定文件格式、协议状态机），对应 MDASH 的 plugin

## 两条可选路径

1. **CyberGym 原生（最小仿真，推荐起点）**
   用 CyberGym 自带镜像，编译漏洞版本、喂 agent 生成的 PoC、看 sanitizer。
   - 注意：完整 server 数据 ~10TB（全量）/ subset 较小；编译镜像才是重头，L2 完全不碰。

2. **自造业务仿真**
   linux 镜像 + 挂载一个服务（web/API），形成完整 simulation，用于业务逻辑/越权类验证。

## 待办
- [x] prove 沙箱：拉 ARVO vul/fix 镜像 + `run_poc`（喂输入看 sanitizer）
- [x] PoC 判定（触发 pre-patch、不触发 post-patch）→ confirmed/rejected/inconclusive
- [x] V0 InputCrafter loop：生成候选 PoC → 真实跑 vul/fix → 保存反馈
- [ ] **InputCrafter agent 接 L2**：吃 L2 的 root-cause 定位 + bug_class，生成候选 PoC
- [ ] 把 L1 验证结果回填 L2 假设：`likely → confirmed` 或 `rejected`
- [ ] 用 prove 成功率回灌校准 L2 Prioritizer 的打分
- [ ] 批量：对 10-task subset 跑 prove，出 confirmed 率 + 失败归因分布
- [ ] （可选）领域插件 / skill card：注入 format/协议状态机等模型不懂的知识，A/B 测增量

## 接口（与 L2）
- 输入：L2 产出的高危 `likely` 假设（file/function/line + bug_class + 触发思路 + 优先级分）
- 输出：真实触发结果（sanitizer 输出 / crash / impact signal）+ 升级后的状态 + 给 L2 的校准信号
