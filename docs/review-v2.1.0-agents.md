# v2.1.0 五业务 Agent 职责复核

审查日期：2026-10-20。依据用户提供的实验指导书 2.3 节以及实施说明书 R2。五个角色是系统执行工作汇报时的业务 Agent；开发时使用的代码代理与组员人数不计入这五个角色。

## 结论与调用关系

v2.0.0 的核心协作链已经存在，并非五张角色卡片或轮播动画。`execution.py` 的 `execute()` 使用 LangGraph 建图，默认调用关系是：

```text
Manager 需求接收与任务拆解
  → Planner 内容规划
  → Data 授权材料/本地接口整理与确定性统计
  → Writer 报告撰写
  → Checker 程序校验与模型审核
      ├─ 未通过且有额度 → Writer 修订 → Checker 再审
      ├─ 修订达到上限 → review_failed
      └─ 通过 → Manager 最终验收 → 合格快照及 Markdown/PDF
```

Manager 末尾再次执行验收仍是原角色，共五种角色、正常六次节点执行。人工编辑后的重新审核明确使用 Checker→Manager，不伪装成一次全新的完整生成。

| 实验职责 | 实际实现及结果传递 | 可复核的既有测试 |
| --- | --- | --- |
| 需求接收、任务拆解 | `ExecutionContext.manager()` 保存原始需求，解析并验证部门和半开期间，生成 `requirements/tasks`。缺项进入 `needs_input`，不能猜造 | `test_missing_requirement_or_authorized_material_stops_with_specific_next_steps`；期间与部门越界测试 |
| 内容规划 | `planner()` 取已完成 Manager 节点的实际 `output`，接收其任务清单，生成章节及 `groups` 数据维度 | `test_planner_output_actually_limits_data_tools_even_with_other_materials_selected` 验证收到 Manager tasks，并改规划为仅项目后检查 Data 只统计项目 |
| 数据整理 | `data()` 按 Planner 的 `groups` 调用明确授权的文件/固定本地接口；全量结构化记录进入 `calculate_statistics()`，结果保留来源哈希、版本和行号 | `test_normal_technical_case_has_real_role_dependencies_and_frozen_sources`；缺分类与跨文件冲突测试 |
| 报告撰写 | `writer()` 接收需求、大纲、统计事实、授权文字片段；数据表及数值引用由程序渲染。返工接收 `previous_review` 和实际 `previous_narrative` | 上述技术场景测试比较 Writer 输入事实集；`test_writer_revision_receives_previous_draft_and_exact_offending_numeric_fragments` |
| 审核与修正 | `checker()` 将程序问题与模型审核合并；模型说通过不能覆盖程序发现的裸数值/非法引用。意见真实返回 Writer；最多两次修订。`acceptance()` 校验审核状态及报告版本后由 Manager 决定接受或拒绝 | `test_checker_feedback_drives_a_real_writer_revision_before_final_manager_acceptance`；`test_persistent_bad_draft_stops_after_two_revisions_without_final_acceptance`；`test_final_manager_can_reject_a_checker_approved_draft` |

任务事件、节点实际输入/输出、逐轮稿与审核、预算、最终验收分别持久化。取消、超时、预算不足、重启中断有终态；不能用静态回复或历史成功记录代替当前真实模型调用。

## 扩大案例时发现的问题与修正要求

1. **P2：文字材料截短和省略原先没有明确提示。** 原实现每行最多 1000 字、总计最多 5000 字，超过后直接跳过。v2.1.0 变更记录 `statistics.note_limitations`，传入 Data、Writer、Checker 和 Manager 验收，并写入运行事件及导出来源附录。结构化记录仍然全量统计；不能把文字片段选取说成全文理解。
2. **P2：大样本逐事实重复输出每个来源行，会使附录和 PDF 过大。** v2.1.0 的新统计快照声明 `source_format=grouped-v1`：同一事实、同一材料 ID/版本/完整哈希/字段的连续行号合并为范围，非连续行分别保留。原始统计 JSON 不删任何行级来源。没有该声明的旧快照继续按旧格式渲染，以保留已审核历史文件的规范内容及哈希。
3. **范围限制：记录变多不自动意味着部门整体覆盖。** 正常自动生成输入没有声明应到人员名单与工作日期，考勤整体覆盖率、整体出勤率仍应为未定义，只展示明确标注的样本指标。已有 `calculate_statistics()` 保持这一限制；本次大案例不能通过改标签将样本说成总体，也不能推导未提供的往期提升。
4. **演示范围：固定背景材料须实际进入数据链。** 正常本地接口现在以 `include_notes=True` 返回固定白名单 `context_file`，Data 通过原有 `stage_import/confirm` 将 TXT 冻结为普通 notes 材料，并记录部门、期间、版本和 SHA256。技术三类接口共享同一工作说明，只装入一次；随后只将匹配需求部门和期间的片段传入 Writer。`include_notes` 默认仍为 False，旧 demo 继续使用小夹具且不增加背景材料。本次无需用户补做 TXT 上传，也无需额外端口或独立演示空间。

来源行号压缩的静态审查确认：按原始行号集合合并，无连续缺口时才能形成范围；分组键保留材料身份、版本、完整 SHA256 及字段。此结论只针对显示压缩，不能替代新增大案例端到端与历史快照兼容测试。

## 本次实际执行的验证

- 使用 `git archive HEAD` 将 **448411149b4e12cb826cc195262aa7f6e04ab438（v2.0.0）** 解出到临时目录，设置该目录的 `src` 为 `PYTHONPATH`，运行 `tests/test_workbench_execution.py` 与 `tests/test_workbench_execution_acceptance.py`：**78 passed，6.29 秒**。
- 上述测试使用本地确定性夹具或 `httpx.MockTransport`；**没有调用付费模型，没有消耗用户 DeepSeek token**。这证明调度、实际结果传递、统计和错误处理，不代表本次新增大数据已完成新的真实模型验收。
- 在共享工作目录开发中的一次同组运行得到 77 passed / 1 failed。唯一失败是普通本地接口场景，当时 API 已切换到尚未生成的 `data/office-cases` 路径；这是开发过程中的中间状态，不能作为最终验证结果。新增数据落盘后的集成结果由本版发布记录单独报告。
- 新增背景链静态复查确认：调用者不能传入任意 URL/服务器文件路径；内容走原有导入校验和不可变材料存储，版本去重使用现有内容指纹；数据接口背景授权不扩大已传给 Writer 的部门/期间范围。
- 独立执行新增 `tests/test_workbench_office_cases.py` 初次结果为 **3 passed / 1 failed，7.98 秒**。两个大案例均已完成五角色、正常验收和 Markdown/PDF 生成；唯一失败是技术 PDF 中完整 SHA256 的直接子串断言，因为 PDF 提取文字包含自动折行。已反馈应先去除提取文本中的排版空白，再核对完整哈希；不能将这个中间结果写成测试全通过。
- 将隔离 v2.0.0 的 `render_markdown()` 与本版函数同时用于已保存的技术、行政真实模型快照，二者输出及快照原 `draft_markdown` **逐字节相同**（技术 16324 字节，行政 5321 字节）。这直接验证旧快照缺省渲染未被来源压缩和文字限制字段改变。

集成复核已由主协调者完成：858项Python测试通过，包含新增大案例五角色、Markdown/PDF实际下载、统计口径、文字限制传递与来源行号集合验证；前端13项接口测试与构建通过。PDF提取校验按排版空白归一后比较完整SHA256。两个案例的可复制需求另做全图回归。完整发布验证见本版发布记录；未消耗付费模型token。
