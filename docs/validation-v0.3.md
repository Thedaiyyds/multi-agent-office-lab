# v0.3 验证记录

日期：2026-10-09。本版验证五个独立 Agent，不声明已实现完整 LangGraph 编排、自动返工或网页。计划先提交于 c686013，实际协作及审查见 [开发计划](plan-v0.3.md) 和 [交叉审查](review-v0.3.md)。

## 离线验证

- 305 项测试通过（保留 v0.2 基线，新增角色、请求预算及独立入口验证）。
- Ruff 代码检查通过，格式检查通过。
- all 固定样例五角色通过，6 次本地 MockTransport 请求，输出预留 1984 token；Data 真实执行一次本地统计工具。
- Checker 注入错误指标与缺章节得到 review_failed；Manager 缺字段得到 needs_input，CLI 退出码均为预期的 1。
- mock 使用 mode=offline_mock，响应是人工固定样例，不是模型生成，不读取模型密钥。

实际验收代码 commit 为 `9da16a4`。固定响应样例的命令、退出码和运行编号见 [mock-acceptance.json](../evidence/v0.3/mock-acceptance.json)，实际 CLI 输出见 [mock-cli-output.txt](../evidence/v0.3/mock-cli-output.txt)。normal / bad-draft / missing-requirements 三份 JSON 明确标记 offline_mock，不作为真实模型输出。

在独立临时目录以 --no-hardlinks 对 `9da16a4` 全新本地 Git clone，未复制 .env、.venv 或 outputs，移除 LLM 环境变量。锁定安装、305 项测试、Ruff、格式检查及五角色 mock 命令全部通过，实际命令及输出见 [clean-clone.json](../evidence/v0.3/clean-clone.json)。

## 真实验收预算

DeepSeek V4 Pro，一轮最多 7 请求；关闭思考、temperature=0、零重试。五个角色正常样例最多 6 请求，再加一份 Checker 错数字/缺章节样例；预留输出上限总计 2240 token，输入另计。失败立即停，保留失败，不自动重跑付费调用。

## 真实模型实际验收

只执行一次真实验收，设置总请求上限 7、预留输出上限 2240。普通角色与错误注入共用一个 Session，第二份报告的请求数/usage 是累计值，不能与第一份报告再相加。实际证据见 [live/acceptance.json](../evidence/v0.3/live/acceptance.json)、[正常角色输出](../evidence/v0.3/live/normal.json)、[Checker 错误注入输出](../evidence/v0.3/live/bad-draft.json)。

| 实际验证 | 结果 |
| --- | --- |
| Manager | ready，部门和日期有原文依据，章节及来源声明合法 |
| Planner | 必需四章完整，四个指标各有唯一归属 |
| Data | 实际执行一次 run_data_tools；指标为 3 / 2 / 2÷3 / 2，模型摘要返回 |
| Writer | 实际模型生成结构化草稿；本地核对实际草稿的章节、核心事实、单位和来源全部通过 |
| Checker 正常独立输入 | passed，程序和模型审核通过 |
| Checker 注入错误数字/缺章节 | review_failed，为预期拒绝；定位 fact_value、required_sections 等问题 |
| 请求数 | 7 次，零自动重试，无重复付费验证 |
| 输入 token | 3642 |
| 输出 token | 1169 |
| 总 token | 4811，来自服务 usage，包含全部 7 请求 |
| reasoning token | 服务未提供统计，标为不可用 |
| 预留输出上限 | 2240，不是实际消耗 |

正常五角色阶段为 6 请求、3777 总 token；随后一份坏草稿增加 1 请求、1034 token。错误注入的 review_failed 是审核能力通过的证据，不是接口调用失败。真实 DataResult 中 mode=offline 表示统计由本地确定性程序产生；外层 AgentRunReport.mode=live 表示该轮调用了真实模型。

归档只包含模拟输入、经校验的角色输出、实际事件及白名单用量，不包含密钥、服务原始错误或隐藏思考。没有因录制证据再发真实请求。

## 范围与证据

Writer 只生成草稿，正常 Checker 的独立固定输入与 Writer 输出分别验证，尚未自动串联角色输出。程序审核覆盖核心指标、来源、章节及渲染一致性；不保证所有自然语言事实正确。Data 模型摘要不能替代其权威统计结果。

真实工具事件来自实际执行。运行日志和 JSON 可归档；Terminal 自动化接口此前禁止操控，终端截图仍待后续整理，不用模拟图片替代。发布状态以独立 PR 的 CI、合并记录和 v0.3.0 标签为准。
