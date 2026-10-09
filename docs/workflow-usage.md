# v0.4 工作流使用说明

`run` 入口执行真实 StateGraph。Manager 解析需求 → Planner 生成大纲 → Data 调用本地工具 → Writer 使用本次统计撰写 → Checker 对照需求、大纲、指标和草稿审核。`agent-demo` 继续保留 v0.3 的固定独立角色样例，两者分开。

```bash
uv run --locked office-agents run --request '生成研发部2026年第二季度工作报告'
uv run --locked office-agents run --request '生成研发部2026年第一季度工作报告'
uv run --locked office-agents run --request '部门：研发部 2026-04-01 到 2026-07-01 章节：概况,成果'
uv run --locked office-agents run --request '生成财务部2026年第二季度工作报告'
```

默认 `mode=offline_mock`，不读取 `.env`，通过本地 HTTP 脚本验证真实编排。脚本只支持研发部、市场部、财务部，或 `部门：名称`；时间使用两个 ISO 日期、明确年份季度（如 2026年第二季度、2026Q2）；章节用 `章节：标题一,标题二`。它不代表通用自然语言理解能力。live 则由真实模型解析，经过已有需求溯源和结构校验。

```bash
uv run --locked office-agents run --mode live --profile deepseek --request '生成研发部2026年第二季度工作报告'
uv run --locked office-agents run --mode live --data-dir uploads/example --data-origin provided --request '生成研发部2026年第二季度工作报告'
```

自有数据目录固定文件名 projects.csv、achievements.csv、issues.txt。路径由调用方绑定，不授予模型任意文件访问。数据先全量校验再筛选。样例目录自动标为 simulated，可显式设置 `--data-origin`；自己的文件默认 provided。`issues.txt` 未筛选，不可归因于本次部门和季度。统计范围是 `[start_date,end_date)`，项目取区间内最新快照。

每次正常链路最多 6 请求，预留输出上限 1984 tokens（输入另计），零重试；DeepSeek 关闭思考。可设置 `--max-requests 1` 等进一步降低预算，预算耗尽明确失败。mode=offline_mock 的 request_count 是本地 HTTP 处理次数，不是收费 API 次数；usage 缺失为 null，不伪造 token 统计。

## 状态与产物

| 状态 | 含义 | 最终报告 | CLI 退出码 |
| --- | --- | --- | --- |
| completed | 五角色完成且审核通过 | report.md | 保存成功为 0 |
| needs_input | 需求、数据缺失或校验失败 | 无 | 1 |
| review_failed | Checker 拒绝草稿 | 无；draft.md 标明审核未通过 | 1 |
| failed | 模型、工具、预算或执行异常 | 无；保留已有草稿 | 1 |

每次运行目录 `outputs/<run_id>/` 保存 run.json（完整业务状态与用量）、events.jsonl（顺序事件）、nodes/（每节点实际输入输出）、draft.md（如有）和 report.md（仅通过）。目录已存在时拒绝覆盖。Data 工具在节点边界关联整体 run_id，统计和来源保持原样。节点 duration_ms 测量整个角色执行；模型/工具子事件没有独立计时时耗时为 null，不冒充精确 HTTP 延迟。

业务输入和校验后的业务数据会进入本地运行结果；密钥、原始响应、推理内容、错误响应体不保存。自有数据默认留本地，提交实验材料前选择脱敏证据。仓库只归档模拟数据联调。

导出前再次核对权威事实、来源、范围、章节、渲染和节点记录，Checker 模型“通过”不能覆盖程序错误。程序检查结构化核心事实，不保证所有自然语言断言正确。本版 revision_count=0，不执行自动修改；v0.5 再增加有限返工。2/3 表示样例 3 个项目完成 2 个，不是软件开发完成率。

真实截图仍需实际界面截图；JSON 与终端记录是运行证据，不冒充截图。计划与架构见 [plan-v0.4](plan-v0.4.md)、[architecture-v0.4](architecture-v0.4.md)。
