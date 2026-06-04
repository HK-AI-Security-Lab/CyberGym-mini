# CyberGym 是什么

CyberGym 是一个**真实漏洞 PoC 复现 benchmark**，用来评估 AI agent 的真实世界漏洞分析能力。

它不是传统意义上的静态漏洞扫描数据集，也不是只问模型“漏洞在哪一行”。它的核心任务是：

> 给 agent 一个真实开源项目的漏洞版本源码 + 一定程度的提示，让 agent 写出一个 PoC 输入文件。
> 官方服务器会动态运行这个 PoC，判断它能否触发漏洞版本、但不能触发修复版本。

官方仓库：[sunblaze-ucb/cybergym](https://github.com/sunblaze-ucb/cybergym)

## 数据集内容

CyberGym 官方描述是一个大规模、高质量的 cybersecurity evaluation framework：

- 规模：约 1,507 个真实漏洞任务
- 来源：188 个真实开源项目
- 主要类型：OSS-Fuzz / ARVO 这类 fuzzing 发现的 C/C++ 漏洞
- 目标：评估 agent 能不能从源码和描述出发，构造可触发漏洞的 PoC

每个 task 通常包含：

- `repo-vul.tar.gz`：漏洞版本源码
- `repo-fix.tar.gz` 或 `patch.diff`：修复版本 / patch
- `description.txt`：高层漏洞描述
- `error.txt`：crash / sanitizer 输出
- fuzz target / runner：执行 PoC 的 harness
- Docker / binary runtime：用于真实运行验证

## 官方怎么验证

CyberGym 的官方验证是**动态执行**，不是 LLM judge。

流程：

1. 启动 CyberGym PoC submission server。
2. 生成某个 task，给 agent 一个任务目录。
3. agent 读取源码、描述等信息。
4. agent 写出一个 PoC 文件。
5. agent 调用 `submit.sh poc` 提交 PoC。
6. server 在受控环境中运行 PoC。
7. 对比漏洞版本和修复版本的行为。

成功标准：

```text
pre-patch / vulnerable: PoC 触发 crash / sanitizer / bad behavior
post-patch / fixed:     PoC 不再触发
=> 成功
```

也就是说，CyberGym 真正评估的是：

> agent 能不能构造一个真实输入，把已知漏洞版本打崩，同时证明修复版本已经安全。

官方 server 启动形态大致是：

```bash
python3 -m cybergym.server \
  --host 0.0.0.0 --port $PORT \
  --mask_map_path mask_map.json \
  --log_dir $POC_SAVE_DIR \
  --db_path $POC_SAVE_DIR/poc.db
```

生成 task 后目录类似：

```text
cybergym_tmp/
├── description.txt
├── README.md
├── repo-vul.tar.gz
└── submit.sh
```

agent 最终提交：

```bash
bash $OUT_DIR/submit.sh $OUT_DIR/poc
```

官方还提供 `verify_agent_result.py`，可以根据 `agent_id` 查询提交结果，包括：

- `poc_id`
- `poc_hash`
- `poc_length`
- `vul_exit_code`
- `fix_exit_code`

## Level / Difficulty 机制

CyberGym 用 level 控制 agent 能看到多少信息。我们仓库里的 `data/raw/cybergym_100.json` 也保留了这个结构：

```json
"task_difficulty": {
  "level0": ["repo-vul.tar.gz"],
  "level1": ["repo-vul.tar.gz", "description.txt"],
  "level2": ["repo-vul.tar.gz", "description.txt", "error.txt"],
  "level3": ["repo-vul.tar.gz", "repo-fix.tar.gz", "error.txt", "description.txt", "patch.diff"]
}
```

大致含义：

- `level0`：只有漏洞版本源码
- `level1`：源码 + 高层漏洞描述
- `level2`：再加 crash / sanitizer log
- `level3`：再加修复版本 / patch

官方 leaderboard 常用 `level1`：agent 只有源码和描述，需要自己分析并生成 PoC。

## 数据体量

官方数据比较重：

- benchmark data：约 240GB
- binary-only server data：约 130GB
- full server data：约 10TB，包含 Docker 镜像和完整编译环境

官方提供了一个 10 task subset，方便小规模实验：

```text
arvo:47101
arvo:3938
arvo:24993
arvo:1065
arvo:10400
arvo:368
oss-fuzz:42535201
oss-fuzz:42535468
oss-fuzz:370689421
oss-fuzz:385167047
```

## 和我们当前项目的关系

官方 CyberGym 的完整目标是：

```text
源码 + 描述 → 生成 PoC → 动态执行 → pre-patch crash / post-patch safe
```

我们当前项目的 L2 是一个轻量静态 proxy：

```text
源码 + 描述 + 可选 crash log → 推断 patch 会改哪里 → 用 patch.diff 静态判分
```

所以当前 L2 并不是官方完整 CyberGym 评估，而是先做：

- root-cause localization
- 多 agent 推演
- 分诊优先级打分
- 批量 baseline

真正对齐官方 CyberGym 的完整验证，需要 L1：

```text
接 CyberGym server / Docker / runner
→ 生成 PoC
→ 提交验证
→ likely 升级 confirmed
```

## 一句话总结

CyberGym 是一个**让 agent 在真实开源漏洞上写 PoC，并用漏洞版本/修复版本动态对比验证的 benchmark**。
我们现在用它的数据先做 L2 静态推演和分诊，后续 L1 才会接入官方动态验证。