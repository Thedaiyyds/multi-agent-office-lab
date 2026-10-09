# v0.2 验证记录

验证日期：2026-10-09。本版实现确定性数据工具，全部验证离线执行，没有调用 DeepSeek API，也没有读取模型配置来计算数据。业务 Agent 和报告流程尚未实现。

## 开发与审查

开发计划和共享接口先提交于 c62d76c；三个 AI 角色按独占文件范围实现、测试并互查。实际分工、发现与修复见 [开发计划](plan-v0.2.md) 和 [交叉审查记录](review-v0.2.md)。Git 使用实际开发者身份。

## 本地整体验证

| 检查 | 实际结果 |
| --- | --- |
| uv run --locked pytest -q | 151 passed |
| uv run --locked ruff check . | 通过 |
| uv run --locked ruff format --check . | 30 files already formatted |
| git diff --check | 通过 |
| 研发部 Q2 CLI | ok，项目 3、完成 2、完成率 2/3、成果 2 |
| 模型调用 | 0 次；data-check 的独立测试禁止配置读取及 HTTP 请求 |

测试包括完整样例手算、不同季度/部门、边界日期、最新快照、重复和冲突、空完成率、全局错误传播、来源哈希和物理行号、乱码/格式/超限/路径错误、长字段及解析设置恢复、CLI 退出码与文件保存。没有把 mock 模型探测计作真实模型运行。

## 实际运行证据与新克隆复现

实际验收代码 commit 为 `66185e8`。证据目录为 [evidence/v0.2](../evidence/v0.2/)，只包含模拟材料，不提交 .env 或自有上传数据。命令、退出码、运行编号及对应文件见 [acceptance.json](../evidence/v0.2/acceptance.json)，原始 CLI 输出见 [cli-output.txt](../evidence/v0.2/cli-output.txt)。

| 实际 CLI 场景 | 项目数 | 完成数 | 完成率 | 成果数 | 状态 / 退出码 |
| --- | --- | --- | --- | --- | --- |
| 研发部 Q2 | 3 | 2 | 2/3 | 2 | ok / 0 |
| 研发部 Q1 | 2 | 1 | 1/2 | 1 | ok / 0 |
| 市场部 Q2 | 1 | 0 | 0 | 1 | ok / 0 |
| 财务部 Q2，无匹配数据 | 0 | 0 | null | 0 | no_data / 0 |
| 范围外市场部 2025 年 NaN 进度 | 不输出 | 不输出 | 不输出 | 不输出 | invalid_data / 1 |

研发部 Q2 run_id 为 b1a0b728-2fa3-498b-ad98-2bcdc772ed93，最新快照引用 projects.csv 第 3、4、5 行，已完成引用第 3、4 行；成果引用 achievements.csv 第 2、3 行。范围外坏数据场景 run_id 为 055e26a6-5ba8-4427-b20b-a7959599fbd9，错误定位到 projects.csv 第 10 行 progress 字段，指标及问题原文均为空。

异常演示是明确的离线错误注入，不代表真实办公数据。使用归档 fixture 可重现：

```bash
mkdir -p outputs/v0.2-invalid-fixture
cp data/samples/achievements.csv data/samples/issues.txt outputs/v0.2-invalid-fixture/
cp evidence/v0.2/invalid-projects.csv outputs/v0.2-invalid-fixture/projects.csv
uv run --locked office-agents data-check --data-dir outputs/v0.2-invalid-fixture --data-origin simulated --department 研发部 --start-date 2026-04-01 --end-date 2026-07-01
# 预期退出码 1、invalid_data、metrics 为空
```

在独立临时目录对 `66185e8` 执行全新本地 Git clone（--no-hardlinks），未复制原 .venv、.env 或 outputs。安装锁定依赖成功；151 项测试、Ruff 与格式检查、离线 graph-demo、研发部 Q2 data-check 全部通过。命令及实际输出已归档为 [clean-clone.json](../evidence/v0.2/clean-clone.json)，本地路径已用占位符替换。

## 已知范围与截图

issues.txt 返回原样的 scope=unfiltered 材料，没有按部门或日期归因，不统计问题数量。完成率仅反映区间内有快照的项目，不代表全部存量项目。损坏 CSV 的来源记录数只能覆盖错误前可解析记录。

终端截图尚未归档：本次自动化接口禁止操控 Terminal，实际命令输出和 JSON 将归档为可复核证据，不能将其称为终端截图。课程报告的真实运行截图仍需在后续整理。

版本功能通过 feature/v0.2-data-tools 的独立 PR 集成，发布状态以 GitHub PR Checks、合并记录及 v0.2.0 标签为准。
