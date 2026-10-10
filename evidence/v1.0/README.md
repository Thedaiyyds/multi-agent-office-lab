# v1.0 实际证据索引

日期2026-10-10。最终产品源码冻结于dee1ab995929b60358b25a94e471960601acba67；后续提交只补报告和证据。所有本版业务验收为offline_mock，外部API请求为0，不产生DeepSeek付费token。模型实际token用量未提供，不能把预留输出量写成已消费用量。

## 最终验收

- [CLI结果](acceptance-cli.txt)：8个场景通过，suite为552349e2-e842-4821-8d9e-9d647b6dc455。[实际JSON及完整运行](acceptance/552349e2-e842-4821-8d9e-9d647b6dc455/summary.json)记录源SHA及source_dirty=false，总34次本地MockTransport HTTP。
- [本机完整回归](regression.txt)：595项通过，5.80秒。
- [全新GitHub克隆](clean-clone.json)及[实际输出](clean-clone.txt)：exact源SHA，无.env，清除模型环境变量；锁定安装、Ruff、格式、595测试、图安装演示、8场景验收及8520本机网页健康检查均成功。测试31.91秒，输出保留10秒faulthandler冷启动诊断栈，pytest最终退出0；不把该诊断冒充失败或根因已解决。
- [真实浏览器索引](browser-acceptance.json)：Codex内置浏览器、805×717默认视口、4次真实任务、本地HTTP共26次、6张原始JPEG；无图像生成、拼接或编辑。任务执行现有原图和审计门禁，HTTP模型返回由本地夹具提供，不能宣称为新真实模型验证。

| 实际浏览器场景 | run_id | 状态 | 本地HTTP / 返工 |
| --- | --- | --- | --- |
| 研发Q2 | 5ebe1e80-b53c-476e-836c-f0bdf1c8eb1b | completed；3/2/66.7%/2 | 6 / 0 |
| 市场Q2 | 41fbc07c-4c6c-4d94-8d5f-6a4be58ced9f | completed；1/0/0%/1；左栏需求保留正确 | 6 / 0 |
| 主动错误事实 | 0d2fc947-efdc-4ab0-bdee-1dc76c40186b | completed；初稿4被拒绝，修订为3 | 7 / 1 |
| 持续主动错误 | 752925ee-090c-4aec-87ee-efcc0b3d2060 | review_failed；无最终报告及下载 | 7 / 2 |

完整运行在browser-runs/各UUID目录。正常最终报告通过真实下载，下载字节与服务器report.md完全一致，SHA见索引。截图包括初始页、正常统计、市场输入与指标、fact_value审核意见、返工上限及无最终下载。窄视口下指标卡文字可能显示省略号，完整值以对应run.json为准，不对截图数字修图。项目完成率是样例业务统计。

## 修复前证据

[preflight/index.json](preflight/index.json)、三张旧截图及三个实际运行保留初次源08c9f9c的观察；市场报告实际正确，但禁用表单回退默认显示。observations.md与initial-form-fix-regression.txt保留第一次修复未通过的记录，不算作最终成功。该文本日志仅去除行末空格，断言、状态、错误和通过数不变。

较早CLI suite c9a72995-9709-4d6e-870e-1f10a2735346也是08c9f9c源、八项成功，保留原来源，不覆盖或重新标记成最终源。历史v0.6截图留在原evidence/v0.6；本版报告明确区分历史与新运行。架构和时序图是本地代码绘图，位于docs/report/figures，不作为网页运行截图。
