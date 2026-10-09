# 多智能体智能办公协作实验

课程项目目标是使用 LangGraph 搭建部门工作汇报系统：需求解析 → 大纲规划 → 数据整理 → 报告撰写 → 审核与有限返工。代码按 [开发路线](ROADMAP.md) 逐版推进。

当前里程碑为 v0.2：在 v0.1 模型接入基础上，实现模拟办公数据的读取、校验、统计及来源追踪。151 项离线测试和新克隆复现通过。五个业务 Agent、完整办公汇报流程和 Streamlit 界面按后续版本实现；实际验收结果见版本验证记录。

v0.1.1 已实际通过 DeepSeek V4 Pro 的三项探测：4 次请求共 483 token，77 项离线测试通过，详见 [验证记录](docs/validation-v0.1.md)。

## 快速开始

需要 Git、uv 和 Python 3.12。本项目的 Python 版本范围为 3.12～3.13，课程复现统一使用 3.12。尚未安装 uv 时，从 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装。

```bash
git clone https://github.com/Thedaiyyds/multi-agent-office-lab.git
cd multi-agent-office-lab
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked office-agents graph-demo
uv run --locked office-agents data-check --department 研发部 --start-date 2026-04-01 --end-date 2026-07-01
uv run --locked pytest
uv run --locked ruff check .
```

`graph-demo` 使用确定性的离线节点验证 LangGraph 图能执行，输出标记为 `mode=offline`。mock 测试验证适配器的正常和错误处理，不调用外部模型。这些结果不能作为真实模型接入成功或五 Agent 协作完成的证据。

## v0.2 数据工具

`data-check` 默认读取仓库 `data/samples/` 内的三个模拟文件，无需 `.env`，不调用模型：

```bash
uv run --locked office-agents data-check --department 研发部 --start-date 2026-04-01 --end-date 2026-07-01
uv run --locked office-agents data-check --department 市场部 --start-date 2026-04-01 --end-date 2026-07-01
```

研发部 Q2 的手算预期是项目 3 个、完成 2 个、完成率 2/3、成果 2 个。统计先校验全部文件，再按部门和半开日期区间筛选；同一项目只取区间内最新快照。无项目时完成率为 `null`，不伪造为 0%。任何数据错误会阻止指标输出，返回 `invalid_data` 及非零退出码；合法但无匹配项目或成果时返回 `no_data`，退出码为 0。

处理自己的数据时，将同名文件放在一个目录并指定：

```bash
uv run --locked office-agents data-check --data-dir uploads/example --data-origin provided --department 研发部 --start-date 2026-04-01 --end-date 2026-07-01
```

每文件最多 2 MiB，CSV 最多 10,000 条数据记录，必需字段与来源边界见 [数据契约](docs/data-contract.md)。结果保存为 `outputs/data-{run_id}.json`，包括口径、SHA-256、来源行号与数据问题。`issues.txt` 是未按部门和季度筛选的原始材料，不统计问题条数；自有材料会进入本地结果文件，按需选择脱敏证据提交。

[数据字典](docs/data-dictionary.md) 和 [模拟数据手算表](data/samples/README.md) 说明字段与预期；[开发计划](docs/plan-v0.2.md) 记录实际 AI 分工和验收流程。

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
- [v0.2 验证记录](docs/validation-v0.2.md)：离线统计、异常处理、交叉审查与复现结果。
- [团队协作方式](TEAM_WORKFLOW.md)：一名实际开发者和三个 AI 开发角色的职责、评审与真实证据规则。
- [数据接口](docs/data-contract.md)：指标、来源和数据问题的实际约定。
- [报告与审核接口草案](docs/report-contract.md)：后续 Writer、Checker 和导出的接口。

Git 使用实际开发者身份，角色 A/B/C 表示 AI 辅助模块分工。实验记录、截图和测试结果按实际运行整理。密钥保存在本地 `.env`，提交 `.env.example`；自动生成的 `outputs/` 默认不提交，需要归档时选择脱敏证据。
