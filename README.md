# 多智能体智能办公协作实验

课程项目目标是使用 LangGraph 搭建部门工作汇报系统：需求解析 → 大纲规划 → 数据整理 → 报告撰写 → 审核与有限返工。代码按 [开发路线](ROADMAP.md) 逐版推进。

v0.1 的范围是环境配置、模型能力探测和离线图运行验证。此版本不包含五个业务 Agent、真实办公汇报流程或 Streamlit 界面。`pyproject.toml` 的版本号不代表实验已经验收或发布；实际结果以运行记录和版本验证文档为准。

v0.1.1 已实际通过 DeepSeek V4 Pro 的三项探测：4 次请求共 483 token，77 项离线测试通过，详见 [验证记录](docs/validation-v0.1.md)。

## 快速开始

需要 Git、uv 和 Python 3.12。本项目的 Python 版本范围为 3.12～3.13，课程复现统一使用 3.12。尚未安装 uv 时，从 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装。

```bash
git clone https://github.com/Thedaiyyds/multi-agent-office-lab.git
cd multi-agent-office-lab
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked office-agents graph-demo
uv run --locked pytest
uv run --locked ruff check .
```

`graph-demo` 使用确定性的离线节点验证 LangGraph 图能执行，输出标记为 `mode=offline`。mock 测试验证适配器的正常和错误处理，不调用外部模型。这些结果不能作为真实模型接入成功或五 Agent 协作完成的证据。

## 接入真实模型

```bash
cp .env.example .env
# 在本地编辑 .env，填写实际服务地址、模型名和必要的密钥
uv run --locked office-agents doctor
```

`.env.example` 的地址、模型和密钥均为空，因此未配置时 `doctor` / `smoke` 会明确失败。`doctor` 只检查配置，不联网；通过配置检查也不代表服务可用。默认 `smoke` 向配置的服务发送请求，分别验证文本回复、严格 JSON Schema 输出和工具调用。

按服务选择一种真实探测命令即可。使用 DeepSeek V4 Pro 时，显式选择节省 token 的探测配置：

```bash
uv run --locked office-agents smoke --profile deepseek
```

该配置每次请求最多输出 64 tokens，关闭思考，强制 0 重试，失败即停；正常流程为 4 次请求。JSON 探测采用 `json_object` 和 Pydantic 本地 schema 校验，不代表服务端支持默认配置的严格 `json_schema`。API 参数依据 [DeepSeek 官方说明](https://api-docs.deepseek.com/api/create-chat-completion/)。实际调用与 token 用量以运行记录为准。

支持严格 `json_schema` 的其他服务可使用默认配置：

```bash
uv run --locked office-agents smoke --output-dir outputs
```

只有实际运行的三项探测都通过，才能记录该模型具备 v0.1 所验证的能力。尚未提供真实模型配置时，真实探测应记录为待验证。命令、配置细节、探测结果和排错方法见 [搭建说明](docs/setup.md)。

## 文档与协作

- [版本路线](ROADMAP.md)：v0.1～v1.0 的开发任务和验收条件。
- [v0.1 验证记录](docs/validation-v0.1.md)：实际执行结果、环境和未验证项目。
- [团队协作方式](TEAM_WORKFLOW.md)：一名实际开发者和三个 AI 开发角色的职责、评审与真实证据规则。
- [数据接口草案](docs/data-contract.md)：指标、来源和数据问题的约定。
- [报告与审核接口草案](docs/report-contract.md)：后续 Writer、Checker 和导出的接口。

Git 使用实际开发者身份，角色 A/B/C 表示 AI 辅助模块分工。实验记录、截图和测试结果按实际运行整理。密钥保存在本地 `.env`，提交 `.env.example`；自动生成的 `outputs/` 默认不提交，需要归档时选择脱敏证据。
