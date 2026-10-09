# v0.3 Writer 与 Checker 接口

v0.3 已实现独立的 Writer 和 Checker，类型位于 `agent_schemas.py`。本版固定样例用于验证角色接口，尚未自动把 Manager 输出驱动完整业务流程；审核返工、最终报告导出和网页属于后续版本。

## 输入边界

`run_writer(requirements, outline, data, session)` 接收需求、大纲和权威 `DataResult`。`run_checker(requirements, outline, data, draft, session)` 额外接收结构化草稿。需求中的部门、日期半开区间 `[start_date, end_date)` 和 `data_origin` 必须与数据请求逐项相同。大纲标题及顺序对应必需章节，四项指标各分配到唯一章节；允许问题及建议章节不分配指标。

Writer 与 Checker 不修改原始数据、指标、口径和来源。Writer 数据校验失败时拒绝生成报告，无匹配数据时本地生成明确说明缺失的草稿，不产生统计事实或模型请求。Checker 对无数据、无效数据或输入契约不匹配返回 `needs_input=true`，不调用模型。比例为 `null` 时固定渲染为“缺失/未定义”，不替换为 0%。

`issues.txt` 仍是未按部门及时间筛选的材料；Writer 提示词只接收 `issue_scope=unfiltered`，不发送原文。报告固定显示“未筛选，不可归因于当前部门或日期范围”，不把原问题自动归因于当前季度。

## Writer 输出 Draft

| 字段 | 当前含义 |
| --- | --- |
| `sections` | 按大纲顺序的 `{section_id,title,text}` |
| `fact_claims` | 四项核心指标声明：`section_id,metric_id,value,unit,source_ids` |
| `suggestions` | `{section_id,text}`；固定标注“建议（尚未实施）” |
| `issue_scope` | 固定 `unfiltered` |
| `markdown` | 程序调用 `render_draft` 按统一模板生成的报告草稿 |

正常数据请求一次模型，输出上限 768 token。`DraftContent` 是模型输出，`Draft` 在它基础上添加程序渲染的 Markdown。四项核心统计采用固定事实行：例如 `事实：项目数 = 3 [count]；来源：projects.csv`，比例保留原始比值，避免显示四舍五入掩盖来源差异。模型产生错误但结构合法的数字时保留草稿，交 Checker 定位，不偷偷纠正数字或改权威数据。非有限数字和格式错误由共享解析层拒绝。生成文本合并为单行并转义 Markdown 符号，防止注入额外章节、HTML 或链接结构。

运行编号由外层 `AgentRunReport` 管理，当前 Draft 自身没有 `run_id` 或修订轮次字段。草稿只表示生成完成，不能直接称为审核通过的最终报告。

## Checker 输出 Review

| 字段 | 当前含义 |
| --- | --- |
| `passed` | 程序与模型审核都允许通过 |
| `issues` | 至多 32 项：`code,location,message,severity` |
| `revision_instructions` | 至多 32 项修改建议 |
| `needs_input` | 关键数据或契约不足，需补充输入 |

`check_draft` 不访问模型，确定性检查以下内容：需求与数据范围一致；必需章节和大纲的 ID、标题、顺序一致；不存在重复章节；四项核心事实无缺失和重复；事实分配章节正确；值与权威数据一致（绝对容差 `1e-9`，拒绝布尔值和非有限值）；单位和来源列表一致；建议引用有效章节；Markdown 与同一份结构化内容的固定渲染结果逐字一致。无匹配数据草稿不能带统计事实。

正常数据时 `run_checker` 另请求一次模型，输出上限 256 token，审核逻辑、覆盖、无依据事件和未筛选材料归因。程序错误先合并到输出，模型即使返回 `passed=true` 也不能抹去。程序检查与模型意见合并至多 32 项；模型解析或请求错误由共享层报告调用失败，区别于正常审核未通过。

通过仅说明这些确定性规则及本次模型语义审核通过。程序不穷尽解析自由文本中的全部事实；自然语言事件、额外数字、建议是否可行依赖模型审核，不能宣称全部事实已验证。

## 后续编排、导出和界面计划

完整 LangGraph 编排计划将通过审核的报告进入 `completed`，可修正问题返回 Writer，关键数据缺失进入 `needs_input`，达到修改上限仍未通过进入 `review_failed`。这些返工轮次、终态和导出规则尚未在 v0.3 实现。

未来导出按运行编号隔离，只有审核通过的产物标为最终报告。网页依据实际执行事件更新进度，下载对应当前运行和修订版本的实际产物；不使用计时动画冒充执行。截图记录运行编号、commit SHA、输入及结果，mock、错误注入与真实模型分别标注。
