# 版本记录

## v0.2.0 数据准备与确定性工具

- 新增固定来源的 CSV/TXT 读取与全量校验，支持 UTF-8/BOM、来源 SHA-256 与物理行号，限制文件和记录大小。
- 新增项目最新快照及成果统计：部门精确匹配、半开日期区间、冲突拒绝、相同重复警告去重，无项目完成率返回 null。
- 新增 data-check 离线入口，按 run_id 保存四项指标、口径、来源与数据问题；数据错误阻止全部指标，不调用模型。
- 提供跨季度、跨部门模拟数据、独立手算矩阵、详细开发计划、数据字典和实际交叉审查记录。
- 151 项测试、Ruff 检查与格式检查通过。实际 CLI 和新克隆复现证据见 docs/validation-v0.2.md。

## v0.1.1 DeepSeek 低消耗探测

- 增加显式 DeepSeek 探测配置：关闭思考，每次最多输出 64 token，无自动重试，首个失败后停止。
- DeepSeek Chat Completions 使用 JSON object 输出，再由本地 Pydantic 校验字段、类型和取值；通用配置保留服务端 JSON Schema 请求。
- 记录实际 HTTP 请求数和服务返回的 token 用量；缺失用量明确标为不可用。
- DeepSeek V4 Pro 实际探测三项通过：4 次请求，总用量 483 token（输入 434、输出 49）；77 项离线测试通过。实际证据见 docs/validation-v0.1.md。

## v0.1 开发基线

本版建立环境、模型适配与验证入口。真实模型验收状态见 docs/validation-v0.1.md；未配置模型时不能声明已完成模型接入验收。

- Python 3.12、uv 项目配置和固定依赖锁文件。
- OpenAI-compatible Chat Completions 模型适配，集中配置与安全错误提示。
- doctor 配置检查、graph-demo 离线 LangGraph 验证、smoke 真实模型能力探测。
- 离线 HTTP mock 测试和 GitHub Actions 检查。
- 搭建说明、后续数据及报告契约草案、版本路线和真实 AI 协作记录。

本版没有五个业务 Agent、办公数据处理、审核返工或网页界面，这些功能按路线在后续版本实现。

## 仓库初始化

已有 GitHub README 作为仓库基线。本地开发计划与 AI 协作流程在实现前记录，v0.1 功能通过独立 PR 集成。
