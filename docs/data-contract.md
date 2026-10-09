# v0.2 数据工具契约

v0.2 实现离线数据读取、完整校验和确定性统计。工具不读取模型配置、不请求模型；五个业务 Agent 属于后续版本。字段示例和手算结果见 [数据字典](data-dictionary.md)，类型定义见 `src/office_agents/schemas.py`。

## 输入与调用

授权数据目录必须包含 `projects.csv`、`achievements.csv` 和 `issues.txt`。来源名称固定，不接受任意路径作为 `source_id`；解析后的文件须位于授权目录内，越界符号链接拒绝。每个文件最大 2 MiB，只读取普通文件。CSV 最大 10,000 条数据记录，不计表头；引号中的换行属于同一条记录。数据行为空或宽度错误仍属于原始记录。

CSV 接受 UTF-8 和 UTF-8 BOM，字段集合必须与字典相同，允许调换表头顺序；缺字段、重复或额外表头均报错。所有日期严格使用 `YYYY-MM-DD`。数字进度须有限且在 0～100，`completed` 要求进度恰为 100。

```python
from office_agents.schemas import DataRequest
from office_agents.tools.data_io import read_csv, validate_data
from office_agents.tools.metrics import calculate_metrics, run_data_tools

request = DataRequest(
    department="研发部",
    start_date="2026-04-01",
    end_date="2026-07-01",
    data_origin="simulated",
)
table = read_csv("data/samples", "projects.csv")  # RawTable
dataset = validate_data("data/samples")  # ValidatedDataset
result = calculate_metrics(dataset, request)  # DataResult
result = run_data_tools("data/samples", request)  # 串联读取、校验、统计
```

`DataRequest` 仅有 `department`、`start_date`、`end_date`、`data_origin`。部门去掉首尾空白后必须非空，并进行精确匹配。区间要求 `start_date < end_date`，采用开始包含、结束排除的 `[start_date, end_date)`。Python API 的来源默认是 `provided`，调用方可以声明 `simulated`。这个字段记录来源声明，不会验证数据是否真实。

```bash
uv run --locked office-agents data-check \
  --data-dir data/samples \
  --department 研发部 \
  --start-date 2026-04-01 \
  --end-date 2026-07-01 \
  --output-dir outputs
```

CLI 在数据目录解析后等于当前工作目录的 `data/samples` 时默认标为 `simulated`；其他目录默认 `provided`。可用 `--data-origin simulated|provided` 显式覆盖。成功或数据异常均保存 `outputs/data-{run_id}.json`；请求字段非法时只输出静态错误摘要，不生成报告。`ok`、`no_data` 返回退出码 0；`invalid_data`、请求非法、工具执行失败或报告保存失败返回 1。

## 校验顺序与统计口径

1. 先校验所有文件和全部记录，再按部门和区间筛选。任何部门或区间外的数据错误也会阻止本次统计，不能通过筛选隐藏错误。
2. 同一 `project_id` 的部门在整个文件中必须固定。同一 `project_id + snapshot_date` 的字段在类型转换及首尾空白归一化后相同时去重，保留第一条的来源并发出警告；内容冲突则报错。
3. `achievement_id` 在整个成果文件中唯一。相同重复去重并警告；同编号内容冲突报错。
4. 在筛选区间内，每个项目只取最新快照。项目数是这些唯一项目的数量，完成数是这些快照中状态为 `completed` 的数量，完成率是完成数除以项目数。
5. 成果按部门和成果日期筛选后，按已校验和去重的编号计数。

项目口径是“区间内有快照的项目”，不是季度末全部存量，也不是季度内新完成项目。同一项目可在不同季度分别出现。状态决定是否完成，单纯 `progress=100` 不会把 `active` 改成 `completed`。完成率保存 0～1 原始数值，不在工具层做百分比取整。

项目数为零时，完成率返回 `null` 并附 `no_projects` 警告；其他计数照常返回。项目和成果都为零时为 `no_data`，仍返回四项指标；只要有项目或成果则为 `ok`。若存在任何 `error`，状态为 `invalid_data`，`metrics=[]`，不返回问题原文材料。

## 输出与来源

`DataResult` 包含 `run_id`、`created_at`（UTC ISO 时间）、`mode="offline"`、`status`、`request`、`metrics`、`sources`、`data_issues`、`issue_materials`。

| 指标 ID | 值和单位 | 行号引用 |
| --- | --- | --- |
| project_count | 非负计数，count | 每个所选项目的最新快照 |
| completed_project_count | 非负计数，count | 所选已完成快照 |
| completion_rate | 0～1 比例或 null，ratio | 全部分母项目的最新快照，分子由其状态决定 |
| achievement_count | 非负计数，count | 所选去重成果记录 |

每个指标另含 `definition`、`source_ids`、`source_refs`。引用对象是 `source_id` 加 `line_number`；行号是 CSV 记录在原文件中的物理起始行号，多行字段不会把后续引用错误地按逻辑序号递增。零计数可能没有行号引用，来源标识仍保留。

`SourceRecord` 保存 `source_id`、同名 `file_name`、原始文件字节的 SHA-256、`record_count`，不保存本地绝对路径。CSV 的记录数包括重复和错误宽度记录，与去重后的业务计数不同。超 10,000 条仍统计可解析的原始总量，保留前 10,000 条；CSV 语法错误处无法继续解析时记录数只覆盖此前成功解析的记录。超过 2 MiB 或未能读取文件不生成 hash；已经读取的字节即使乱码或解析错误也保留 hash。`issues.txt` 的 `record_count=0`，不能解释为零个业务问题。

`issues.txt` 原文保留空白，作为 `IssueMaterial(source_id="issues.txt", scope="unfiltered", text=...)` 返回。它没有结构化部门和日期字段，因此不按需求筛选、不统计问题条数、不自动归因。文件缺失报错；空文件或只有空白允许并警告。调用方和未来 Writer 必须保留 `unfiltered` 说明，不能把全部问题写成所选部门或季度的问题。

## 数据问题代码

问题对象包含 `severity`、`code`、静态 `message`，并可附 `source_id`、`line_number`、`field`。错误摘要不回显原始行、字段值或本地路径。合法的来源标识和行号用于定位；业务请求和有效原文材料本身仍是报告内容，不代表整份报告自动脱敏。

| error 代码 | 含义 |
| --- | --- |
| unknown_source | 来源不在固定白名单，或 read_csv 使用非 CSV 来源 |
| invalid_data_root | 授权目录不存在、不是目录或无法解析 |
| path_outside_root | 来源解析后越出授权目录 |
| missing_file | 缺少必需文件 |
| unreadable_file | 文件不可读、符号链接循环或不是普通文件 |
| file_too_large | 超过 2 MiB |
| invalid_encoding | 不是合法 UTF-8 |
| empty_csv | 空 CSV 或没有表头 |
| invalid_csv | CSV 引号等语法错误 |
| invalid_headers | 表头字段集合或唯一性错误 |
| invalid_row_width | 数据记录字段数与表头不一致 |
| too_many_records | 超过 10,000 条 CSV 数据记录 |
| invalid_project / invalid_achievement | 字段或记录一致性约束失败 |
| project_department_conflict | 同一项目跨记录的部门发生变化 |
| project_snapshot_conflict | 同项目同日快照内容冲突 |
| achievement_conflict | 同成果编号内容冲突 |

| warning 代码 | 含义 |
| --- | --- |
| empty_table | CSV 只有表头，无数据记录 |
| duplicate_project_snapshot | 相同项目快照已去重 |
| duplicate_achievement | 相同成果记录已去重 |
| empty_issue_material | 原文问题材料为空或只有空白 |
| no_projects | 所选范围无项目，完成率没有分母 |

`read_csv` 只处理读取与 CSV 结构，字段语义和跨记录校验由 `validate_data` 完成。`calculate_metrics` 接收已校验的 `ValidatedDataset`；公开串联入口 `run_data_tools` 确保在统计前执行全部校验。未来 Agent 应使用串联入口并读取实际指标，不能自行修改统计事实或补造缺失记录。
