# v0.4 实际验收记录

验收日期 2026-10-09，基线 v0.3.0 `3d50b52283d431690387393d42c127ffa4d19bc5`。详细计划见 [plan-v0.4](plan-v0.4.md)，三 AI 角色交叉审查与实际修复见 [review-v0.4](review-v0.4.md)。

## 实现和离线验收

`office-agents run` 真正使用 StateGraph：Manager 需求传给 Planner/Data，实际大纲及工具统计传给 Writer，实际草稿和前序结果传给 Checker。专用会话共用预算，输入深拷贝保护权威事实；异常条件终止后续节点。`agent-demo` 继续保留独立角色的固定样例，不能冒充完整编排。

每次在独立 run_id 目录保存 run.json、events.jsonl、nodes/ 和已有草稿。五节点完成且通过审核与最终复核才导出 report.md；需求/数据不足为 needs_input，审核拒绝为 review_failed，调用或预算失败为 failed，均不生成最终报告。revision_count=0，自动返工在 v0.5 实现。

最终生产代码 `131eb83a0a3f1f4aed2b33021d77f6650a022831`：**402 passed**，Ruff、格式、Git diff 检查通过。从 GitHub 新克隆并获取最终生产代码，在没有 .env 的目录实际执行 uv sync --locked、Ruff、格式、402 项测试、mock 完整链路，全部退出 0；没有复制本地配置。实际命令及输出见 [clean-clone.txt](../evidence/v0.4/clean-clone.txt)、[clean-clone.json](../evidence/v0.4/clean-clone.json)。

七份归档的离线案例使用当时生产源 `9a207c56c02d3501316f0165f1973148cf8d3758`。真实图、工具和程序检查实际执行，HTTP 响应是本地脚本，外部模型请求为 0。索引见 [mock-acceptance.json](../evidence/v0.4/mock-acceptance.json)。后续日期提示和导出披露修复由最终测试与新克隆另行验证，旧案例不冒充最终代码的再次运行。

| 案例 | 项目 / 完成 / 完成率 / 成果 | 状态 | 本地 HTTP 次数 |
| --- | --- | --- | --- |
| 研发部 Q2 | 3 / 2 / 2/3 / 2 | completed | 6 |
| 市场部 Q2 | 1 / 0 / 0 / 1 | completed | 6 |
| 研发部 Q1 | 2 / 1 / 0.5 / 1 | completed | 6 |
| 缺需求 | 不调用工具 | needs_input | 1 |
| 财务部无匹配数据 | 0 / 0 / null / 0 | needs_input | 4 |
| 错指标且缺章节 | 权威数据不改，审核拒绝 | review_failed | 6 |
| 请求预算 1 | Manager 后停止 | failed | 1 |

测试还覆盖 CSV 实际变化后报告随之变化、自定义章节和大纲编号传递、无年份不猜、非法工具范围/路径在执行前拒绝、HTTP/超时/非法 JSON/工具异常安全失败、运行不覆盖、篡改事实/来源/渲染/节点输出无法绕过导出门禁。

## 真实模型联调

使用已配置的 DeepSeek V4 Pro，零重试、thinking disabled，数据仅为仓库模拟材料。证据见 [live-acceptance.json](../evidence/v0.4/live-acceptance.json)。

首次需求“生成研发部2026年第二季度工作报告”在 Manager 本地校验停止：源 `9a207c5`，run_id `de056d93-6c7f-4e60-ab86-aa7b7edcb4da`，1 请求/372 tokens，无下游或最终报告。原始响应没有保存，无法确定具体失败字段；不断言它是某种日期错误。[失败记录](../evidence/v0.4/live-initial-failure.json) 原样保留。随后离线补强从原文提取的日期范围提示与固定安全诊断，仍严格校验模型输出，不自动修正答案。

完整实测输入明确给出部门、ISO 半开范围和四个章节：

```bash
uv run --locked office-agents run --mode live --profile deepseek --request '生成研发部2026年第二季度工作报告。日期范围为2026-04-01（含）至2026-07-01（不含）；章节依次为工作概况、主要成果、问题与风险、后续计划。' --output-dir outputs/v0.4-live
```

源 `eaf45d796b34d4d19c4de31c49c2c4f7c00bed58`，run_id `787bcbe9-2196-4d0d-a5f5-e00a15934f7c`，completed，五角色均 passed。17 事件包含 10 节点开始/结束、6 模型请求、1 实际本地工具执行。四核心指标及来源复查正确：3 项目、2 完成、2/3 完成率、2 成果；文件 SHA256 和原始物理行号可追溯。

| 验证 | 请求数 | 输入 tokens | 输出 tokens | 总 tokens | 输出预留上限 |
| --- | --- | --- | --- | --- | --- |
| 首次 Manager 拒绝 | 1 | 279 | 93 | 372 | 256 |
| 完整五节点 | 6 | 2984 | 995 | 3979 | 1984 |
| 本版累计 | **7** | **3263** | **1088** | **4351** | **2240** |

reasoning_tokens 服务未返回，记 null，不能当作 0。实际终端输出见 [live-cli-output.txt](../evidence/v0.4/live-cli-output.txt)，已校验业务状态和节点见 [原始运行](../evidence/v0.4/live/787bcbe9-2196-4d0d-a5f5-e00a15934f7c/run.json)。无需重复付费查看。

## 审核限制和报告展示

人工阅读发现真实 Writer 的“整体工作按计划推进”“资源分配紧张”等正文缺乏本次输入支持，而真实 Checker 仍 passed。这是实际漏判：四项结构化指标正确不保证所有自由正文断言可靠。

最终导出仅声明四结构化指标/来源程序校验及 Checker 模型审核通过，正文逐段标记“模型叙述（待人工核实）”。这是披露范围，**不是纠正或消除幻觉**。实际文字、事实行、建议、原草稿、节点和事件未改写；强化正文事实约束作为 v0.5 工作。

保存的同一 WorkflowResult 离线再导出到新的根目录，没有新增 API 请求。[当前展示报告](../evidence/v0.4/export-recheck/787bcbe9-2196-4d0d-a5f5-e00a15934f7c/report.md) 由 `ef146aa99dde6b2e1403da9e46a337dfd5e44594` 生成；最终代码 `131eb83` 再次在新临时目录导出并逐文件比较，产物完全相同。原流程 SHA、导出 SHA、最终复验 SHA 分开记录，不覆盖历史，也不把重新导出冒充新模型运行。

## 发布与课程材料

feature 分支通过独立 PR、CI 和交叉评审后合并；实际发布以 GitHub PR 和 v0.4.0 标签为准。提交前检查 .env 被忽略、模板密钥为空、候选文件没有本地实际密钥；归档仅使用模拟数据。

架构/时序见 [architecture-v0.4](architecture-v0.4.md)，使用见 [workflow-usage](workflow-usage.md)。JSON 与终端文字是真实记录，**本次未捕获实验截图**；截图与最终课程报告仍需后续整理。三 AI 协助角色不等于三名人类组员。
