# 版本记录

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
