# v0.1 搭建与模型探测

本文提供运行步骤，不预填实际成功记录。离线图、mock 测试和真实模型调用分别记录，实际验收由对应版本验证结果确认。

## 1. 获取代码和依赖

安装 Git、uv。uv 的安装方法见 [官方说明](https://docs.astral.sh/uv/getting-started/installation/)。执行：

```bash
git clone https://github.com/Thedaiyyds/multi-agent-office-lab.git
cd multi-agent-office-lab
uv python install 3.12
uv sync --locked --python 3.12
```

`uv sync --locked` 使用仓库中的 `uv.lock`，依赖声明与锁文件不一致时会失败，避免复现者静默修改依赖。Python 3.12 和 3.13 满足项目版本范围，但版本验收统一使用 3.12。首次安装需要下载运行时和依赖；“离线图”指图执行不调用模型，并不表示首次安装可以断网进行。

记录实际版本用于实验报告：

```bash
git --version
uv --version
uv run --locked python --version
git rev-parse HEAD
```

## 2. 先验证离线执行

```bash
uv run --locked office-agents graph-demo --output-dir outputs
uv run --locked pytest
uv run --locked ruff check .
```

`graph-demo` 是两节点确定性流程，用来验证 LangGraph 安装和图执行，产物标记 `mode=offline`。pytest 中的 mock 模型响应仅验证请求协议和错误分支，不联网。它们不能证明模型可访问，也不能证明业务 Agent 已经工作。

## 3. 配置模型服务

```bash
cp .env.example .env
```

在项目根目录的 `.env` 中填写下列字段，或由当前进程的环境变量提供配置。不要将真实密钥写入源码、截图或提交信息。

| 配置项 | 要求 |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible 服务的实际 API 前缀，通常包含 `/v1`；以服务说明为准，不要填写末尾的 `/chat/completions` 路径 |
| `LLM_MODEL` | 服务中实际可用的模型标识 |
| `LLM_API_KEY` | 服务要求的密钥；无认证的本地服务可以为空 |
| `LLM_TIMEOUT_SECONDS` | 单次请求超时秒数，范围为大于 0 且不超过 300，默认模板为 30 |
| `LLM_MAX_RETRIES` | 请求失败后的额外重试次数，范围为 0～5，默认模板为 1；不表示业务返工次数 |

不默认连接外部服务或选择模型。填写自己已有账户的实际服务信息；如使用本地模型服务，仍需确认其接口与能力兼容。真实探测会发送实际请求。

```bash
uv run --locked office-agents doctor
```

`doctor` 不联网，只检查配置是否完整有效。缺少地址或模型、配置值非法时返回失败。地址语法通过，不代表接口存在、认证通过或模型具备所需能力。

## 4. 三项真实模型探测

```bash
uv run --locked office-agents smoke --output-dir outputs
```

`smoke` 一次执行以下探测，报告标记 `mode=live`。任一探测失败或配置缺失，命令退出码为 1，并保留可用于排错的安全报告。

| 探测 | 成功判据 | 能证明的范围 |
| --- | --- | --- |
| 文本 | 模型返回有效文本回复 | 配置服务能够接受本次文本请求 |
| JSON | 使用严格 `json_schema` 请求，本地验证 `number=7`、`label=probe` | 本次结构化输出符合指定约束 |
| 工具 | 强制调用 `echo_number`，参数为 -100～100 的严格整数；执行后回传结果并取得最终回复 | 本次工具选择、参数解析和回传链路可用 |

报告保存在 `outputs/live-<run_id>.json`，离线图报告为 `outputs/offline-<run_id>.json`。报告只保留安全摘要，不保存模型原文、原始响应或密钥。`mode=live` 表示走真实服务路径，失败报告同样使用该标记；必须结合每项结果判断是否成功。

三项探测是兼容性样例，并不保证所有复杂业务请求均成功。单纯返回 JSON 文本不能替代严格 Schema 探测成功，模型介绍中声称支持工具也不能替代实际运行。

## 5. 常见失败的处理

| 现象 | 处理 |
| --- | --- |
| 配置检查失败 | 检查 `.env` 所在目录、必填字段和数值格式 |
| 网络连接或服务请求失败 | 检查服务是否启动、网络连通、API 前缀及模型标识；在本地核实账户权限和密钥，不在日志中输出密钥 |
| 模型不存在 | 使用服务提供方或本地部署中实际存在的模型标识 |
| 文本通过，JSON 或工具失败 | 记录部分通过；核实服务的兼容协议及模型能力，再调整配置复测 |
| 请求超时 | 检查服务状态，必要时调整超时时间，保留实际失败原因 |

不要为了让探测显示成功将离线固定输出写入真实服务路径。未配置真实服务时，记录“离线验证完成、真实模型待配置/待验证”；只完成部分探测时，逐项记录结果。

## 6. 实验证据

每条证据记录代码 commit SHA、执行命令、模式、实际结果和产物位置。真实模型证据另记录模型标识及三项探测结果；服务地址按需要脱敏。截图来自实际终端，检查画面是否含密钥后再归档。

实际执行结果见 [v0.1 验证记录](validation-v0.1.md)。v0.1 不需要制造五 Agent 或网页界面截图。后续角色和 UI 按 [开发路线](../ROADMAP.md) 实现，报告接口见 [报告契约](report-contract.md)。
