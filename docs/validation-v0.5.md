# v0.5 实际验收记录

验收日期 2026-10-09，基线 v0.4.0 `0c4c9a101608110dc75bbe1427a5da2e62f865ee`。计划先提交于 `8b34045`；生产实现及下列实测源码为 `05194a8b827e6f7ada2a4e8491d4f3a67ec54ee6`。实际分工、交叉审查和修复见 [review-v0.5](review-v0.5.md)，路线与阶段见 [plan-v0.5](plan-v0.5.md)。后续证据与文档提交不改变上述实测源代码。

## 实现和离线验证

首次草稿之后最多开始两次真正的 Writer 返工。Checker 输出的 actual draft/review 传给下一轮 Writer，要求、大纲、指标、来源保持不变；程序不自动改正模型草稿。revision_count 计已开始的返工尝试，Writer 随后失败也计入。网络重试单独计数且默认关闭，每个逻辑请求最多一次、会话最多两次，每次尝试均受 HTTP 和输出预留预算限制。

完整 run 采用 constrained 正文，章节说明必须逐字符符合无数字模板；四项数值通过结构化声明与指标核对并固定渲染。v0.4 实测中“资源紧张”“按计划完成”这类无依据的自由正文在本版独立回归中被程序拒绝，保留错误原稿再请求修复。建议仍需人工评估，不是通用自然语言事实验证。独立 agent-demo 兼容旧自由正文，不据此声称具备相同约束。

**504 项测试通过**，Ruff、格式和 Git diff 检查通过；包括 HTTP 级独立验收、实际图循环、真实上一草稿与反馈传递、原数据不变、零/一/两次返工、程序/模型审核拒绝、非法 JSON、工具失败、网络/预算边界、未审核版本保留、不覆盖旧运行、来源/节点/历史/HTTP 账本篡改不能导出最终报告。

GitHub 新克隆 `05194a8`，没有 .env，清除模型环境配置后实际执行锁定依赖安装、Ruff、格式、504 项测试、普通 mock 完整运行及 bad-fact mock 返工，全部通过。实际命令和输出见 [clean-clone.txt](../evidence/v0.5/clean-clone.txt)、[clean-clone.json](../evidence/v0.5/clean-clone.json)。

九份离线运行归档索引见 [mock-acceptance.json](../evidence/v0.5/mock-acceptance.json)，外部模型请求全部为 0；模型 HTTP 来自脚本，图、数据工具、审核、导出实际执行。

| 场景 | 最终状态 | 已开始返工 | 本地 HTTP 尝试 | 关键证据 |
| --- | --- | --- | --- | --- |
| 正常研发部 Q2 | completed | 0 | 6 | 四指标 3 / 2 / 2/3 / 2 |
| 首次错项目数 | completed | 1 | 7 | 原生成3，实验注入4，拒绝后修复3 |
| 首次缺章节 | completed | 1 | 7 | 原稿、反馈与修复后的完整章节均保存 |
| 每轮持续错误 | review_failed | 2 | 7 | 三轮全部拒绝，无 report.md |
| 财务部无数据 | needs_input | 0 | 4 | 完成率 null，不进入 Writer |
| 缺关键需求 | needs_input | 0 | 1 | Manager 停止 |
| 返工 Checker 请求预算不足 | failed | 1 | 6 | revisions/01/draft.md 待审核，无该轮 review.json |
| Manager 模拟超时后重试 | completed | 0 | 7 | 网络重试1，业务返工0 |
| 持续模拟503 | failed | 0 | 2 | 即使会话额度2，单请求仍只重试1次 |

最后两例通过 tests/test_v05_integration.py 的 HTTP 故障夹具执行，不冒充 CLI 或真实服务故障。前七例保存 CLI 命令、退出码与实际输出。

## 一次真实 DeepSeek 返工验收

使用用户已配置的 DeepSeek V4 Pro，仅仓库模拟材料；thinking disabled、retry_budget=0、HTTP硬预算8、输出预留硬预算3008，输入另计。只执行下列一次实测，没有追加正常流程付费运行。

```bash
uv run --locked office-agents workflow-test --mode live --profile deepseek --case bad-fact --request '生成研发部2026年第二季度工作报告。日期范围为2026-04-01（含）至2026-07-01（不含）；章节依次为工作概况、主要成果、问题与风险、后续计划。' --max-requests 8 --max-output-tokens 3008 --retry-budget 0 --output-dir outputs/v0.5-live
```

run_id `c20640f6-d1a5-4319-a41b-d54be75415ce`，completed，退出0。五角色实际协作，Writer/Checker各执行两轮；初轮项目数原生成3，故意注入4，程序审核返回 fact_value 及修改意见，**不发送 Checker HTTP**。下一 Writer 实际收到坏草稿及反馈，把项目数恢复为3；最后通过程序检查和真实 Checker 模型复审，才导出 report.md。人工注入明确记录，不能视为模型自然犯错证据。

| 实际 HTTP | 业务返工 | 网络重试 | 输入 tokens | 输出 tokens | 总 tokens | 输出预留 |
| --- | --- | --- | --- | --- | --- | --- |
| **7** | **1** | **0** | **4418** | **1357** | **5775** | **2752** |

reasoning_tokens 未返回，记 null / unavailable。预留输出2752不是实际输出1357，也不是包括输入的总用量5775。用量、预算、指标与来源记录见 [live-acceptance.json](../evidence/v0.5/live-acceptance.json)，终端输出见 [live-cli-output.txt](../evidence/v0.5/live-cli-output.txt)。

[完整实测目录](../evidence/v0.5/live/c20640f6-d1a5-4319-a41b-d54be75415ce/run.json) 含原模型生成结果、注入后草稿、两轮审核、实际节点和事件；[初次草稿](../evidence/v0.5/live/c20640f6-d1a5-4319-a41b-d54be75415ce/revisions/00/draft.md)、[修复草稿](../evidence/v0.5/live/c20640f6-d1a5-4319-a41b-d54be75415ce/revisions/01/draft.md)、[最终报告](../evidence/v0.5/live/c20640f6-d1a5-4319-a41b-d54be75415ce/report.md) 可直接查看，无需再次调用API。

独立复查最终导出门禁、正文模板、来源 SHA256/原始行号与四项指标正确，所有 Writer/Checker 输入的权威数据一致。最终四指标是项目3、完成2、完成率2/3、成果2；无无依据的自由历史正文。此次模型没有输出建议，因此不把它作为建议质量验收；未来建议可行性仍需人工判断。

## 发布和剩余课程材料

版本通过独立 PR、GitHub CI 和交叉审查后合并 main，发布 v0.5.0；实际结果以对应 GitHub PR 与 Git 标签为准。提交前核查 .env 被忽略、模板密钥为空、提交候选内容不含本地实际密钥，归档仅用仓库模拟数据，没有原始提供方响应或推理内容。

本版是命令行系统，网页在 v0.6。本次没有捕获实际运行截图；JSON/终端文字和 Mermaid 图不能冒充截图。最终课程实验报告、实际运行截图与老师要求的三人组队仍需按课程要求处理，AI A/B/C 是实际辅助分工而非三个虚构人类作者。
