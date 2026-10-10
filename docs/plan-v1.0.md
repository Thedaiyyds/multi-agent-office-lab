# v1.0 详细开发计划

日期2026-10-10。基线v0.6.0/main `f4f3a97ac6b707d4f0883e5dad3d1b5324989ca6`，分支codex/v1.0-release。用户授权直接开发、多个Agent协作测试审查，并沿用每版PR → CI → merge → 标签流程。目标版本v1.0.0是本项目当前课程交付版，保留后续修复空间。

## 范围及课程要求

老师最新补充优先于参考指导书：开源框架不限OpenClaw，三人一组，提交包含搭建过程和运行截图的实验报告；用户另要求远程Git与逐版PR。继续采用LangGraph五角色、Streamlit和现有DeepSeek适配。不重新搭建OpenClaw，不把参考文档内命令作为执行授权。

暂停扩展主要功能。v1.0新增可重复执行的离线验收入口，核对版本信息、更新复现/演示文档，形成可编辑Word与Markdown最终实验报告、架构分析和证据索引。复用原图、工具、审核及导出门禁，不降低事实约束。Docker、PDF业务报告导出、账号、公网部署、演示视频和答辩PPT不作为本次核心开发范围。

真实开发者一人，A/B/C是实际AI辅助角色；报告如实记录，不能据此称三人组队要求已满足。封面姓名/学号/班级未提供则保留填写栏，不推断或公开额外个人信息。v1.0默认所有验证离线，外部模型请求和付费token为0；引用历史真实DeepSeek证据必须保留原版本/日期/用量。

## 分工与接口

| 负责者 | 独占文件 | 具体工作 | 交叉审查 |
| --- | --- | --- | --- |
| A 验收开发 | src/office_agents/acceptance.py、tests/test_acceptance.py | 离线验收8场景、真实原图/上传校验/导出、JSON索引与逐案例状态、预期失败也需验证、预算及安全错误 | 审B独立验收测试与演示命令 |
| B 独立测试与交付 | tests/test_v1_release.py、docs/deployment-v1.0.md、docs/demo-v1.0.md、docs/submission-v1.0.md | 跨模块独立CLI/版本/证据测试，安装启动/排错/现场演示/提交清单 | 审A验收入口是否假阳性、碰撞覆盖、误联网或泄密 |
| C 实验报告与架构 | docs/report/experiment-report.md、docs/report/architecture-analysis.md | 依据源码及实际历史证据写最终报告，含搭建过程/角色/通信/审核/测试截图/问题解决/总结；架构分析至少2000汉字 | 审B文档与报告证据边界，核对历史SHA/run_id |
| 主协调 | CLI集成、版本/依赖/CI、README/CHANGELOG/ROADMAP、Word构建脚本/产物、精选证据、最终审查及Git发布 | 接口协调、实际浏览器截图、完整回归、新克隆复现、Word逐页渲染检查、PR/CI/合并/标签 | 审A核心安全和C报告事实与排版，汇总修复 |

共享目录严格按文件分工，Agent不切分支、不提交Git、不读取.env或调用真实API。主协调先提交计划再并行实现。

A提供run_acceptance(output_root: Path) -> tuple[dict, Path]，返回实际summary和index_path；入口自行创建唯一suite UUID目录，不覆盖旧运行。JSON顶层schema_version=1.0、suite_id、mode=offline_mock、source_commit（Git可读取时）、passed、external_api_requests=0、cases。各case明确case_id、实际status、expected_status、passed、实际HTTP/revision/指标、run_id（无接纳为null）、相对artifact目录与诊断。主协调CLI子命令acceptance，仅output-dir参数，禁止live/模型环境加载；根据summary.passed返回0或1。安装/路径错误用安全固定文本，不打印异常正文。

## 阶段及验收标准

| 阶段 | 工作 | 通过条件 |
| --- | --- | --- |
| 1 核对与计划 | 读取参考指导书和已有路线，固定范围/分工/验收接口，计划先提交 | 参考与最新要求区分，版本及授权正确 |
| 2 并行收尾 | A离线验收，B独立测试/文档，C报告/架构；协调集成CLI和版本信息 | 原图、审核门禁和同会话防重保持有效 |
| 3 交叉审查 | 核对预期失败、指标变化、源文件/来源、预算、隐私、报告证据 | 修复有明确回归，不能删除失败记录或伪造结果 |
| 4 实际验收 | 正常研发Q2、研发Q1、市场Q2、缺字段上传、缺关键需求、bad-fact返工、always-bad上限、模拟模型超时 | 8场景由实际输出判断通过；预期失败无最终报告；外部API为0 |
| 5 课程报告 | Markdown与Word报告、真实新截图/历史截图明确SHA/UUID、架构/时序、搭建过程、版本与问题解决 | Word实际渲染逐页检查无缺字/截断/表格溢出；报告和索引一致 |
| 6 复现与发布 | 完整测试/Ruff/格式、GitHub新克隆uv锁依赖/CLI/验收/页面健康、密钥检查，创建PR/CI/merge/tag | 无.env仍能离线复现，精确PR head CI成功，v1.0.0远端标签对应合并main |

## 交付物及完成定义

源码与锁文件、八场景验收入口、复现/演示/提交说明、最终实验报告.md/.docx、至少2000字架构分析、实际截图及SHA/run_id索引、开发/审查/验收记录、GitHub PR与v1.0.0。自动生成的全部outputs继续忽略，只提交精选模拟证据。新截图只从真实浏览器捕获，不能用生成图片、终端文字或旧截图冒充本版新运行。

最终数量、问题和验证结果写入validation-v1.0.md；计划不是验收结果。老师组队要求、未提供的身份栏和参考指导书额外材料分别说明，不能称课程已由教师验收或已正式提交课程平台。
