# v0.3.0 五个独立业务 Agent 开发计划

日期：2026-10-09；基线：v0.2.0；分支：feature/v0.3-role-agents。先提交计划与共享接口，再开发及验收。

## 范围与接口

本版实现 Manager、Planner、Data、Writer、Checker 的独立接口、提示词、实际输出和运行事件。五个角色共用模型，但权限、输入与输出分开。`agent-demo` 是独立固定样例验收入口，all 模式逐项执行角色样例，不使用 Manager 输出自动驱动后续角色，不作为 v0.4 的完整业务编排。LangGraph 完整串联、审核返工及网页仍属后续版本。

共享类型放在 agent_schemas.py，不改变 v0.2 数据统计口径；共享模型请求与成本限制放在 agent_runtime.py。工具只接受受限参数，本地目录由调用方绑定，模型不能指定读取路径。

| 角色接口 | 输入 | 输出与本地校验 |
| --- | --- | --- |
| run_manager(user_text, session, data_origin=...) | 明确需求或缺信息的自然语言 | ManagerDecision：ready + Requirements，或 needs_input + 缺失字段/问题；不猜缺失部门或年份 |
| run_planner(requirements, session) | 已校验需求 | Outline：稳定章节编号、标题、用途、指标 ID；覆盖必需章节及四项指标 |
| run_data_agent(requirements, data_root, session) | 需求及绑定的授权目录 | DataAgentResult；强制 run_data_tools 工具调用，精确校验参数后执行，再把统计摘要返回模型；日志记录真实执行 |
| run_writer(requirements, outline, data, session) | 需求、大纲、权威 DataResult | Draft：模型章节/事实声明/建议，加程序统一渲染 Markdown；草稿不等于已审核报告 |
| run_checker(requirements, outline, data, draft, session) | 原需求、大纲、事实及草稿 | Review：程序检查必需章节/核心指标/单位/来源/正文与结构一致性，模型检查覆盖和表达；模型不能覆盖程序错误 |

## 核心规则

- 需求日期是严格 YYYY-MM-DD 半开区间；章节标题非空且唯一，输出 Markdown。data_origin 由调用方声明，不让模型改变。
- Planner 的章节顺序与需求一致，编号唯一，四项指标各有唯一章节归属。
- Data 工具名称固定 run_data_tools，参数仅 department/start_date/end_date；与需求逐项一致才执行。仅一次工具调用，拒绝未知工具、多调用、非法 JSON、额外参数和越权参数；路径不进入工具参数。
- Data 复用全量校验与确定性统计。数据错误返回 needs_input，不能产生虚假指标；无匹配数据明确保留 null 和警告。模型不能替代计算或改写工具结果。
- Writer 不修改 DataResult，以结构化事实声明和固定行模板展示核心数字。缺数据明确说明；issues.txt 未筛选，不归因于当前部门/季度；建议与事实分开。
- Checker 对核心事实、章节和渲染一致性作程序检查，并请求模型作内容审核。通过不代表穷尽验证自然语言中所有事实；检查覆盖范围必须写明。
- 输入材料作为数据对待，不能授予新工具权限；无邮件、网络搜索或任意文件工具。不保存隐藏思考、鉴权、原始错误响应。

## 开发分工与交叉审查

| 负责人 | 独占文件 | 开发及测试 | 交叉审查 |
| --- | --- | --- | --- |
| 协调者 | agent_schemas.py、agent_runtime.py、agent_examples.py、cli.py、对应 runtime/CLI 测试、计划/验证/版本/CI/evidence | 共享接口、成本限制、独立样例、集成和发布 | 全模块边界、来源与状态一致性 |
| A 架构 Agent | agents/__init__.py、agents/manager.py、agents/planner.py、tests/test_manager_planner.py | 需求解析、缺信息、章节规划 | Writer/Checker 的事实与章节契约 |
| B 数据 Agent | agents/data.py、tests/test_data_agent.py、docs/agents-data.md | 受限工具调用、真实执行事件与数据摘要 | Manager/Planner 的参数和 Data 接口 |
| C 报告 Agent | agents/writer.py、agents/checker.py、tests/test_writer_checker.py、docs/report-contract.md | 草稿、确定性审核与模型审核 | Data 权限/结果和 CLI 说明 |

共享 checkout 不分别切分支，不修改其他角色文件。变更接口先反馈协调者。使用实际 Git 身份，AI 开发角色不冒充人类组员。

## 成本与真实验证预算

默认 `agent-demo --mode mock` 使用本地 HTTP 模拟，报告 mode=offline_mock；CI 与异常测试全部离线，无密钥。live 必须显式选择。

DeepSeek 使用 JSON object + 本地 Pydantic 校验，关闭思考、temperature=0、零重试。每个角色单次输出上限：Manager 256、Planner 384、Data 工具调用 128 / 摘要 192、Writer 768、Checker 256。每个独立角色限制请求数，all 正常最多 6 次。实际验收只运行一轮五个角色，再额外审核一份注入错误的草稿，最多 7 请求，预留输出上限总和 2240 token；输入 token 另计，记录服务 usage。失败即停，不自动重复付费调用。若任何真实样例失败，保留真实失败并先离线定位，不声明已通过。

## 实施顺序与验收

1. 提交详细计划和共享类型；同步角色函数及 Session API。
2. 三个 Agent 并行开发独占模块和测试，协调者实现请求预算、固定样例、CLI。
3. 离线测试正常 JSON、缺字段、未知指标、工具越权、数据异常、错数字/缺章节、模型审核不能覆盖程序错误、超预算、超时和输出解析失败。
4. 交叉审查，记录具体发现并回归受影响场景。全部基线测试继续通过，Ruff 与格式检查通过。
5. 实际运行 mock 样例及错误注入，记录 mode、run_id、事件、结果，不标作真实模型证据。
6. 在新克隆目录无 .env 验证锁定安装和离线样例，CI 增加 agent-demo mock。
7. 离线检查通过后做一次最多 7 请求的真实 DeepSeek 验收：五个角色均输出有效结果，Data 真实工具执行，Checker 能识别错误数字/缺章节。归档请求数、usage、输出和事件，不保存思考。
8. 文档写清能力边界、真实验证结果及复现命令；创建独立 PR，CI 成功后合并并推送 v0.3.0 标签。

真实运行截图只来自实际界面；Terminal 自动化接口此前被禁止，若仍不可用，保留实际日志/JSON并明确截图待整理，不伪造截图。实际完成状态最终记录于 validation-v0.3.md 与审查文档。

## 实际完成状态

| 阶段 | 完成结果 |
| --- | --- |
| 计划与初始接口 | 先提交于 c686013 |
| 三角色开发与交叉审查 | 已完成，具体发现及修复见 review-v0.3.md |
| 离线整合与样例 | 305 项测试、代码及格式检查通过，正常/缺需求/坏草稿已归档 |
| 新克隆复现 | 无 .env，锁定安装、305 测试与五角色 mock 入口通过 |
| 真实模型验收 | 一轮 7 请求，五角色正常结果与 Checker 错误注入均达到预期；4811 token |
| Git 发布 | 通过独立 PR 检查后合并，状态以 GitHub 记录及 v0.3.0 标签核实 |
