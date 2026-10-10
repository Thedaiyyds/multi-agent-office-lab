# v1.0 实际验收与课程交付

日期2026-10-10。基线v0.6.0 main为f4f3a97ac6b707d4f0883e5dad3d1b5324989ca6，计划先提交于372e77e；最终产品代码冻结于dee1ab995929b60358b25a94e471960601acba67，之后仅补报告及精选证据。独立发布[PR #8](https://github.com/Thedaiyyds/multi-agent-office-lab/pull/8)，最终CI、合并及v1.0.0标签以远端实际记录为准，产品验收源SHA不会改写为后来的文档或merge SHA。

## 完成内容

统一发布版本1.0.0，保留原业务schema契约；增加只离线的acceptance命令，真实执行原图、数据工具、上传预检、有限返工及导出门禁；补部署、两部门演示、课程提交说明、Markdown与可编辑Word实验报告、至少2000汉字架构分析、实际网页截图和证据索引。浏览器发现接纳后禁用表单默认显示问题，保存失败证据并修复元数据回填；没有修改实际权威统计或冻结任务。

真实开发者一人，A/B/C为实际AI辅助角色，分工及交叉审查见[实际审查](review-v1.0.md)。老师最新补充允许任意开源框架；三人组队及课程平台提交需按老师安排处理，不能把AI写成人类组员。身份空栏遵从用户“先空着”。

## 八场景离线验收

命令：uv run --locked office-agents acceptance --output-dir outputs/v1.0-final-acceptance。
实际suite_id为552349e2-e842-4821-8d9e-9d647b6dc455；source_commit为产品冻结SHA，source_dirty=false，CLI退出0，八项检查通过。完整[summary及原运行](../evidence/v1.0/acceptance/552349e2-e842-4821-8d9e-9d647b6dc455/summary.json)、[终端输出](../evidence/v1.0/acceptance-cli.txt)。

| 场景 | 实际状态 | 本地HTTP | 返工 | 验证重点 |
| --- | --- | --- | --- | --- |
| 研发Q2 | completed | 6 | 0 | 项目3、完成2、比例2/3、成果2，行号及源SHA |
| 研发Q1 | completed | 6 | 0 | 2、1、1/2、1；指标随日期范围改变 |
| 市场Q2 | completed | 6 | 0 | 1、0、0、1；部门筛选及无匹配分子行 |
| 错字段上传 | input_rejected | 0 | 0 | 上传真实预检拒绝，无run_id和最终产物 |
| 缺需求 | needs_input | 1 | 0 | Manager真实停点，未运行下游 |
| 错事实后修复 | completed | 7 | 1 | 首稿4被fact_value拒绝，Writer恢复3并复审 |
| 持续错误 | review_failed | 7 | 2 | 三次拒绝、到上限停止，无最终报告 |
| 模拟请求超时 | failed | 1 | 0 | 明确MockTransport超时，停在Manager，无下游 |

总34次本地MockTransport HTTP，外部API 0；异常和预期停止必须满足真实节点/预算/审核/文件门禁才能判为验收通过，不能称业务成功率100%。索引逐次记录实际UUID及相对产物位置，summary和suite不覆盖旧记录。较早08c9f9c源的首轮suite c9a72995仍保留原来源。

## 测试及全新克隆

- 本机完整595项测试通过，5.80秒；[原输出](../evidence/v1.0/regression.txt)。新增验收15项、独立跨模块5项、UI新增1项及增强原断言；基线574项。Ruff及格式检查通过。
- 从GitHub重新clone codex/v1.0-release，检出精确产品冻结SHA。无.env且显式移除LLM_/DEEPSEEK_环境变量，uv sync --locked --python 3.12、Ruff、格式、595项测试、graph-demo和8场景验收全部退出0。完整[命令与元数据](../evidence/v1.0/clean-clone.json)、[实际日志](../evidence/v1.0/clean-clone.txt)。
- 新克隆测试31.91秒，faulthandler_timeout=10打印慢初始化诊断栈，最终595通过退出0；保留日志，不宣称冷初始化已经解决或删除诊断。复现中另一次suite 2ba83f87-e1cc-4873-aa20-ba075e1ae2f0成功，34次本地HTTP，source_dirty=false。
- 新克隆独立启动Streamlit在127.0.0.1:8520，/_stcore/health返回200及ok，检查后终止复现服务。此健康检查不是新浏览器运行证据，也不是长期稳定性测试。

## 原生浏览器及截图

实际产品运行在127.0.0.1:8517，由Codex内置浏览器操作真实页面。4次独立任务：研发Q2、市场Q2、错误事实返工、持续错误到上限；各6/6/7/7次本地HTTP，返工0/0/1/2。实际UUID、状态、指标、文件及6张原始805×717 JPEG见[浏览器索引](../evidence/v1.0/browser-acceptance.json)和[证据说明](../evidence/v1.0/README.md)。正常最终Markdown通过实际浏览器下载，与服务器report.md逐字节一致，SHA256见索引。

市场部提交后左侧禁用需求仍为市场部，实际指标1/0/0/1，修复展示回退。错误事实明细显示passed=false、fact_value、程序本轮未调用审核模型；逐轮原产物证明4→3。持续错误三轮拒绝后review_failed，没有report.md、最终报告标题或最终下载。普通查看与下载只读已有任务，未触发新执行。

新截图没有图像生成、拼接或编辑。窄视口的指标卡文字会部分省略，完整值由run.json核对；图内不修数字。报告中的4张v0.6历史截图保留原SHA与UUID，另选2张v1.0新图；代码绘制的架构/时序图与实际运行截图分别标识。

## Word 实验报告检查

可编辑报告为docs/report/experiment-report.docx，附录包含至少2000汉字体系结构分析；正文、表格、2张架构图及6张有明确来源的运行截图共8个嵌入图。姓名、学号、班级及未知教师留空，作者元数据为空。主协调者与AI C各自按原尺寸逐页检查最终25页，均通过，无缺字、溢出或截图截断。首次渲染发现中文字体缺失，修正字体与打包渲染器Fontconfig后重新生成；C发现图5详细图注跨页，构建器将图注与图片同页后重新检查全部页面。最终SHA256、字节数及页码见[报告检查索引](../evidence/v1.0/report-qa.json)。内部PDF/页面PNG仅用于排版检查，不作为交付或Git证据。

## 付费调用及发布边界

本版新增全部测试、CLI和网页验收使用offline_mock，没有读取本地模型配置或向DeepSeek发送新请求；新增付费API token为0。本地HTTP计数、输出预留预算、历史真实模型用量不同，不混算。历史DeepSeek证据保留原版本、日期、UUID及实际token，未冒充本版新接入。

精选模拟证据及报告纳入Git，outputs和.env仍忽略。发布先更新PR完整交付内容，再等待精确最新head的offline-checks成功并核对全部检查后merge；main与annotated v1.0.0远端标签必须对应同一merge提交。可通过GitHub PR及git ls-remote origin 'refs/tags/v1.0.0*'复核实际结果。本版不代表课程平台已提交或教师已验收。
