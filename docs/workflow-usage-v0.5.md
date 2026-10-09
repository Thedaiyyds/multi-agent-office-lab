# v0.5 完整工作流使用说明

使用 Python 3.12，执行 `uv sync --locked --python 3.12`。默认 mock 不读取 .env，只把模型 HTTP 响应替换为本地脚本；LangGraph、来源文件读取、指标统计、审核与导出实际执行。显式 `--mode live --profile deepseek` 才使用配置的真实服务，关闭思考，角色共享硬预算。

## 普通运行和故障实验

```bash
uv run --locked office-agents run --request '生成研发部2026年第二季度工作报告'
uv run --locked office-agents workflow-test --case bad-fact --request '生成研发部2026年第二季度工作报告'
uv run --locked office-agents workflow-test --case missing-section --request '生成研发部2026年第二季度工作报告'
uv run --locked office-agents workflow-test --case always-bad --max-revisions 2 --request '生成研发部2026年第二季度工作报告'
```

普通 run 不接受 `--case`。workflow-test 为明确的故障实验：bad-fact 把首次项目数改为权威值加一；missing-section 删除首次草稿最后一章（仅单章时改错标题）；always-bad 每次都改错。节点记录同时保存生成草稿 generated_output 和实际注入后的 output；events 包含 error_injected。这不是自然模型错误。程序拒绝后，下一 Writer 实际收到 previous_draft、review 和不变的统计数据；不是程序自动改正事实。

自有数据用 `--data-dir uploads/example --data-origin provided`，默认 data/samples 为 simulated。格式与统计口径沿用 [数据契约](data-contract.md)。需求必须给出部门、年份/季度或完整半开日期范围；真实实测使用明确范围与章节，见 [验收记录](validation-v0.5.md)。

## 返工、重试与预算

| 参数 | 默认值与范围 | 含义 |
| --- | --- | --- |
| --max-revisions | 2，允许 0/1/2 | 首次草稿以后最多开始几次返工 |
| --retry-budget | 0，允许 0/1/2 | 全会话网络重试额度；每个逻辑请求最多重试一次 |
| --max-requests | 6 + 2×返工额度 + 重试额度；硬上限 12 | 每个真实/模拟 HTTP 尝试均计数，重试不能绕过 |
| --max-output-tokens | 1984 + 1024×返工额度 + 768×重试额度；硬上限 5568 | 请求前累计预留的输出上限，输入另计 |
| --timeout-seconds | 使用配置，允许有限正数且不超过 300 | 每次 HTTP 超时配置 |
| --output-dir | outputs | 每次在新 run_id 目录保存，不覆盖旧运行 |

正常链路最多 6 次 HTTP；两次返工且没有本地审核提前拒绝时最多 10 次。发现程序错误的 Checker 不调用模型，因此坏事实修复通常 7 次，持续注入通常 7 次即达到两次返工上限。只有超时、连接异常、429、5xx 可申请重试；鉴权、参数、非法 JSON/schema、本地校验不重试。默认零重试便于节约用量。降低总请求/输出额度会使运行提前安全失败，即使还有返工额度。

revision_count 是已经开始的返工尝试，路由到下一 Writer 时计入；即使该 Writer 随后失败也计数。logical_request_count 是逻辑请求意图；预算拒绝可能增加它却没有 HTTP。request_count 是实际 HTTP 尝试次数，retry_count 是其中的网络第二次尝试。usage 为服务实际返回用量，缺失记 null，不能当作 0；输出预留并不是实际付费用量。

## 审核与产物

完整工作流采用 constrained 正文：章节范围说明必须符合提供的无数字模板，所有核心数字从结构化 fact_claims 渲染并与 metrics 核对。不支持无来源的历史进度/风险描述；不合规原草稿保留并拒绝。建议是模型提出的未来行动，标记“尚未实施”“待人工评估”，不保证可行。独立 agent-demo 的旧自由正文样例不适用这项完整工作流约束。

已知程序错误返回 program_only；通过本地检查才请求 Checker 模型，记 program_and_model。程序错误不能被模型 passed 覆盖。整个历史、每轮数据/前序反馈、节点输出、注入标记和实际请求预算账本在最终导出再检查。

```text
outputs/<run_id>/
  run.json                 # 状态、指标来源、历史、预算及用量
  events.jsonl             # 节点、工具、HTTP、重试和故障标记
  nodes/01-manager.json …  # 实际输入输出；每轮 Writer/Checker 各一份
  revisions/00/draft.md     # 首次草稿
  revisions/00/review.json  # 实际审核；未完成审核则无此文件
  revisions/01/…           # 实际开始并生成的返工草稿
  draft.md                 # 最近生成的草稿及当前审核状态
  report.md                # 仅 completed 且最终门禁复核通过
```

completed 退出 0。needs_input、review_failed、failed 退出 1；保存实际已产生的记录，没有审核结果不伪造 review.json。JSON/终端文字是证据，不能当作实验运行截图。后续 v0.6 提供页面，最终实验报告与实际截图还需整理。
