# v0.1 验证记录

验证日期为 2026 年 10 月 9 日。v0.1 的代码开发已完成环境、模型适配、CLI 验证入口和离线测试；真实模型配置尚未提供，因此模型接入完整验收仍待完成。

## 本地实际环境与结果

| 项目 | 实际值或结果 |
| --- | --- |
| 操作系统 | macOS Apple Silicon |
| Python | 3.12.15 |
| uv | 0.12.23 |
| LangGraph | 1.2.14，完整依赖以 uv.lock 为准 |
| 安装 | uv sync --locked --python 3.12 成功 |
| 离线测试 | uv run --locked pytest -q：59 passed |
| 代码检查 | uv run --locked ruff check .：通过 |
| 离线图 | increment → double，输入 2 得到 6，实际执行通过 |
| 缺配置 | doctor 返回退出码 1，明确提示填写 LLM_BASE_URL |
| 真实模型 | 未配置，未执行成功的真实请求，不作为已验收项 |

测试覆盖模型请求协议、有限重试、鉴权不重试、错误摘要不包含原始响应或密钥、严格结构化输出、受限工具调用、CLI 失败退出、运行报告和确定性图运行。测试中的模拟 HTTP 响应不证明模型可用。

本次真实离线图产物保存在 [evidence/offline-langgraph-v0.1.json](../evidence/offline-langgraph-v0.1.json)，run_id 为 edcad020-1a32-42ea-8e97-6b0ddea8aea6。此文件来自真实 graph-demo 执行，明确标记 mode=offline，不是模型或五 Agent 协作证据。

## 待完成的模型验收

在本地 .env 配置实际服务地址、模型和必要密钥后运行：

```bash
uv run --locked office-agents doctor
uv run --locked office-agents smoke
```

smoke 必须分别通过 text、structured_json 和 tool_call 三项，再记录所用模型的接入验收。当前不会因为离线测试通过而标注真实调用成功，也不发布代表完整模型验收通过的 v0.1.0 标签。

## AI 协作实际贡献

- 架构角色 A 实现 config、llm、probes、cli 和包入口，并完成源码自查。
- 数据角色 B 实现离线验证测试和后续数据契约草案，并检查模型适配接口。
- 报告与界面角色 C 编写 README、配置模板、搭建说明和后续报告契约草案，并核对 CLI 文档。
- 主协调助手配置依赖锁、CI、Git 集成，执行整体验证并归档实际运行记录。

Git 使用实际开发者身份，角色 A/B/C 表示 AI 辅助工作。本版没有业务数据处理、五个业务 Agent、审核返工或网页界面。

## 截图与后续记录

本次提交保存结构化运行证据和可复现命令。尚未归档终端截图；后续模型配置完成后，截取真实 doctor、smoke 输出并遮挡密钥，记录对应 commit SHA 和 run_id。不要将 mock 或离线图截图标注为真实模型协作。

GitHub CI 结果通过 PR 的 Checks 页面查看；仅在检查实际成功后合并。

## 新克隆环境复现

在独立临时目录克隆开发分支 commit 65f2507 后，重新建立虚拟环境并执行 README 中的安装及离线命令。uv sync --locked --python 3.12 成功，59 项测试通过，Ruff 检查与格式检查通过，graph-demo 实际执行通过。该复现不使用原工作区的 .venv、输出目录或模型配置。
