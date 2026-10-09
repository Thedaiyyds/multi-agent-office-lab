# v0.2.0 开发与验收计划

日期：2026-10-09。开发基线：v0.1.1；分支：feature/v0.2-data-tools。本文先定义工作与验收条件，完成结果另记于 validation-v0.2.md。

## 目标与范围

实现可供后续 Data Agent 调用的确定性办公数据工具。输入为一个授权数据目录内的 projects.csv、achievements.csv、issues.txt，输出为带来源的四项指标和数据问题。全部开发、测试、演示离线执行，不读取模型配置或调用模型。不提前实现业务 Agent、LangGraph 协作、报告撰写和网页。

## 固定接口与统计口径

- schemas.py 统一定义 DataRequest、SourceRef、SourceRecord、DataIssue、ProjectSnapshot、Achievement、RawRow、RawTable、IssueMaterial、ValidatedDataset、Metric、DataResult，其他模块导入这些类型。
- read_csv(data_root, source_id) 返回 RawTable；validate_data(data_root) 返回 ValidatedDataset，收集明确的问题，不静默丢弃非法数据。
- calculate_metrics(dataset, request) 返回 DataResult；run_data_tools(data_root, request) 串联读取、校验与统计。
- DataRequest 使用 department、start_date、end_date、data_origin；日期严格采用 YYYY-MM-DD，区间 [start_date, end_date)，部门精确匹配。
- 先全面校验全部数据，再筛选部门及日期。项目按季度内最新快照计数；同一项目的部门必须固定。同日同编号完全相同记录去重并警告，冲突记录报错。成果编号全文件唯一：相同重复可去重并警告，冲突报错。
- 四项指标为 project_count、completed_project_count、completion_rate、achievement_count。完成率是 0～1 原始比例；无项目则 null，并说明原因。两个计数都为零时状态 no_data；任何数据错误则 invalid_data，metrics 为空；否则 ok。
- 每个指标包含口径、来源文件标识和选中记录行号。来源含原始文件 SHA-256、记录数；不保存本地绝对路径。
- issues.txt 只作为未按部门或季度筛选的原始材料返回，明确 scope=unfiltered，不计数、不自动归因。缺文件阻止统计；空文本允许并警告。
- CSV 接受 UTF-8/UTF-8 BOM，必需表头必须齐全且不可重复，额外表头拒绝；数据行字段数必须一致；日期、状态、有限进度值以及 completed=100 都须合法。
- 每文件最多 2 MiB、CSV 最多 10,000 条数据记录。来源名称固定在白名单，解析后路径必须位于授权目录内；拒绝越界符号链接。错误摘要不回显原始行或文件内容。

## 分工与独占写入范围

| 负责人 | 实现任务 | 独占文件 | 交叉审查 |
| --- | --- | --- | --- |
| 协调者 | 固定共享类型、CLI、版本配置、集成与发布 | schemas.py、cli.py、pyproject.toml、uv.lock、README.md、CHANGELOG.md、plan/validation 文档、CI、evidence | 复核所有接口、来源与退出状态 |
| A 架构 Agent | 有边界的文件读取、字段校验、去重与来源生成 | tools/__init__.py、tools/data_io.py | 审查 B 的统计、来源与异常传播 |
| B 数据 Agent | 模拟数据、指标计算、手工预期与统计测试 | tools/metrics.py、data/samples/*、tests/test_metrics.py | 审查 A 的去重、日期和数据异常处理 |
| C 测试与文档 Agent | 独立异常/读取测试、CLI 测试、实际契约与数据字典 | tests/test_data_io.py、tests/test_data_cli.py、docs/data-contract.md、docs/data-dictionary.md | 审查 CLI 和用户说明是否对应实现 |

共享 checkout 中不由各角色切换 Git 分支，不修改其他角色文件。接口变更先反馈协调者，统一落地。AI 角色代表真实辅助分工，Git 仍使用实际开发者身份。

## 开发步骤与完成条件

1. 固定接口：落地本计划和共享 Pydantic 类型，分派三个角色。
2. 并行开发：A 读取与校验；B 基于共享类型编写统计、模拟数据及手工预期；C 独立设计边界测试和数据说明；协调者实现 data-check CLI。
3. 集成：串联三个文件处理、输出指标和问题，按 run_id 隔离保存 JSON。CLI 的 invalid_data/错误需求/保存失败返回非零，no_data 返回零但明确展示缺数据状态。
4. 验收：正常部门季度、其他季度、其他部门、无匹配数据逐项比较手算。错误场景覆盖空 CSV、缺字段、重复和冲突、坏日期、非有限/越界进度、缺文件、乱码、超限、路径越界；全局异常不能因筛选被隐藏。
5. 交叉审查：A/B/C 按上表互查，提出具体文件与问题；协调者修复后回归受影响场景。测试不能只镜像实现，必须使用独立预期与异常样例。
6. 证据与文档：执行真实离线 CLI，归档代表性 JSON、命令输出和对应 run_id；截图只能来自真实运行，不生成虚假 UI。更新验证记录和版本说明。
7. 新克隆复现：安装锁定依赖并运行数据命令，避免依赖未提交文件。GitHub PR 检查包括 Ruff、pytest、离线图和样例数据命令，CI 不使用 API 密钥。
8. 发布：创建 v0.2 PR、附上验证与审查结果；CI 实际通过后合并 main，再推送 v0.2.0 标签。不得直接向 main 推送版本功能。

## 手算验收矩阵

B 提供同一份模拟数据的独立预期表，覆盖三个主部门项目，其中一个多快照、两个完成；主场景应为 3、2、2/3。另一个季度、另一个部门应有不同结果。边界日期必须验证开始日包含、结束日排除；不得把跨季度重复快照相加为项目数。

## 状态记录

| 阶段 | 当前状态 |
| --- | --- |
| 接口与计划 | 已完成，计划与初始类型先提交于 c62d76c |
| 并行实现与测试 | A/B/C 已完成；151 项整合测试通过 |
| 交叉审查与修复 | 已完成，实际发现与修复见 review-v0.2.md |
| 整体验收与证据 | 本地检查通过，正在归档 CLI 和新克隆复现证据 |
| PR、CI、合并、标签 | 待发布，按 PR 检查结果执行 |

本表在集成时更新；不能仅因分派 Agent 就标记工作完成。
