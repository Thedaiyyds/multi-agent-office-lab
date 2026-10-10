# v0.6 实际网页验收证据

日期：2026-10-10。截图与浏览器运行源代码为 `ec6af104e52768343918f30c68dc84f87541203b`，都是本机Streamlit实际页面的原始Chromium截图，没有图片生成或修改。运行模式全部是offline_mock，外部API请求为0；图、数据统计、审核、返工、导出实际执行。`c850e05`只改测试生命周期，没有改产品源码；最终新克隆验收另记录自身精确SHA。

[浏览器验收索引](browser-acceptance.json)列明7例、UUID、状态、请求次数、源SHA和下载一致性；browser-runs按UUID保存实际产物。正常和上传两次实际浏览器下载的字节都与保存的report.md完全相同，下载不改变可见run_id。

| 截图 | 实际内容 |
| --- | --- |
| [01 初始页面](screenshots/01-initial.png) | 中文需求、样例/上传、默认mock和预算；尚未启动任务 |
| [02 正常完成](screenshots/02-normal.png) | 五角色完成与研发部Q2真实统计，完成率2/3 |
| [03 审核返工](screenshots/03-repair.png) | 故意注入错误项目数，拒绝后返工一次并通过 |
| [04 上传后统计变化](screenshots/04-uploaded.png) | 原生上传3文件，完成数2变3，完成率100% |
| [05 持续错误终止](screenshots/05-revision-limit.png) | 最多两次返工，最终review_failed，无最终报告下载 |
| [06 错误上传](screenshots/06-invalid-upload.png) | CSV字段错误在接纳任务前拒绝，0模型请求 |
| [07 审核明细](screenshots/07-review-detail.png) | 独立bad-fact运行的实际fact_value拒绝及项目数4的坏草稿 |
| [08 最终报告](screenshots/08-final-report.png) | 独立正常运行的真实受约束Markdown报告 |

`uploaded-fixture/`是仓库模拟数据的副本，仅将projects.csv中的P003季度末快照改成completed/100；不是用户真实业务材料。在页面选择上传，待三个文件传输完成后再开始，统计应为项目3、完成3、完成率100%、成果2。

`clean-clone-initial-failure.txt`保留首次573pass/1超时失败，`app-rechecks.txt`保存UI生命周期调整后5轮13项结果。最终新克隆命令、结果和SHA分别见clean-clone.txt、clean-clone.json。原超时未复现且原因未确认，不声称已证实或修复某个产品死锁。

这些材料可用于课程最终实验报告的截图与验收部分，尚未代写最终报告，也不能视为三名人类组员完成开发。
