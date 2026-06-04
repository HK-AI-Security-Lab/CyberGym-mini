# L1 — 仿真验证（Prove 阶段，占位待做）

**定位**：把 L2 的 `likely`（代码层定位 + 已分诊）升级为 `confirmed`——在受控环境**真实触发**漏洞。
对应 MDASH 流水线的 **Prove 阶段**：构造触发输入、动态验证前提、喂 sanitizer 看是否真 crash。
这是 L2 与「真相」之间唯一的桥：没有真实触发，就只能停在静态推断。

**为什么从确定 benchmark 入手**：CyberGym 自带每个漏洞的 Docker 镜像 + 源码 + 构建脚本，且有
干净的成功判据（**pre-patch 触发 + post-patch 不触发 = confirmed**）。有了明确判据，才最能体现
"群体智能 + Security Harness 设计"——这是整个项目里 prove 能力最全面的落点。

**为什么搁置**：需要 Docker / 编译 / 执行 / 可 reset 的运行环境，侵入性强、工程重。
先把 L2 推演 + 分诊闭环做扎实，再补这一层。

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

## 待办（设想）
- [ ] CyberGym 编译沙箱：gcc/clang + ASAN/MSan，`compile_target` / `run_with_input`
- [ ] InputCrafter / Runner / Verifier 三 agent 分工
- [ ] PoC 提交与判定（触发 pre-patch、不触发 post-patch）
- [ ] 把 L1 验证结果回填 L2 假设：`likely → confirmed` 或 `rejected`
- [ ] 用 prove 成功率回灌校准 L2 Prioritizer 的打分
- [ ] （可选）领域插件机制：注入 format/协议状态机等模型不懂的知识

## 接口（与 L2）
- 输入：L2 产出的高危 `likely` 假设（file/function/line + bug_class + 触发思路 + 优先级分）
- 输出：真实触发结果（sanitizer 输出 / crash / impact signal）+ 升级后的状态 + 给 L2 的校准信号
