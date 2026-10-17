# v2.0-alpha.4 五角色执行开发计划

2026-10-16。alpha.3已通过PR12合并及标签发布；依用户已给出的授权直接继续。实施以R2及原指导书功能为准，不增加额外端口或独立演示流程。

## 用户可见目标

正常新建报告页用一段自然需求和已授权材料点击“开始协作”，Manager解析主题与部门/期间后才建立报告，Planner输出数据维度，Data使用本次所选文件或明确授权的固定本地接口，Writer消费大纲/事实，Checker审核并最多两次返工，Manager最终验收。运行记录、逐轮稿、意见和用量持久保存，可刷新读取；本版正文先预览，正式MD/PDF交付在alpha.5。

## 分工

| 角色 | 范围 | 内容 |
|---|---|---|
| 执行后端Agent | execution.py、test_workbench_execution.py | LangGraph/角色严格契约、单worker、台账、预算、取消/重启中断与接口 |
| 前端Agent | Cooperation.tsx、App/API/CSS | 自然语言入口、运行详情/历史、真实状态、明确模式、防重与轮询 |
| 独立质量Agent | execution_acceptance测试、review文档 | 两业务场景与反例、程序审核不被模型覆盖、隔离/预算/异常审查 |
| 主协调者 | api集成、固定本地源、版本及发布 | 正常接口冻结、构造测试注入、浏览器、回归、PR/CI/merge/tag |

## 运行契约

POST /api/v1/runs接收user_text、material_ids（允许空）、mode(live默认或明确offline_mock)、可选report_id/expected_version/use_local_api、请求/输出预算和返工上限，并使用Idempotency-Key。同键同内容复用，同键异内容409。缺需求/材料进入needs_input，不产生假部门或假日期。已有报告运行绑定保存版本，最终版本改变不能宣称当前合格。

GET /runs/{id}与GET /runs（可按report_id筛选）只读；POST /runs/{id}/cancel阻止后续调用，不保证撤销在途供应商费用。快照包含真实事件、节点输入/输出、统计/大纲/正文、逐轮审核、Manager验收和预算/usage；role日志不是计时动画。单worker串行执行；进程锁避免同库重复worker。重启后未知在途任务标中断，不自动重放付费请求。

每次HTTP调用前事务预留一次请求和角色输出上限，默认请求预算12、输出5568 tokens、重试0；Writer最多1024、Manager256、Planner384、Data192、Checker256。最多两次业务返工，实际供应商usage未知时保持null。测试明确MockTransport，不能读取真实.env或网络；真实模式配置缺失不降级mock。

固定本地接口可在normal普通任务经明确授权调用，响应冻结后再统计，保留dataset_id/哈希/源文件映射；不接收外部URL或任意路径。没有授权的源不可由模型自行添加。Writer只用受限事实/片段引用，程序渲染数值表；Checker程序错误即使模型说通过仍拒绝。

## 退出条件

1. 普通技术/行政材料自然文本触发真实五角色图，Manager末尾验收，Data确实使用Planner的数据组。
2. 两场景离线验证、数字篡改/引用错误/错误章节/返工超限/缺信息/缺材料/模型异常正确停点；没有假成功。
3. 幂等并发、报告版本409、空间404、预算耗尽、取消、重启与历史读取通过独立测试。
4. 浏览器正常8520运行、刷新/历史/取消/失败以及390px布局通过；完整输出仍待alpha.5不得提前宣布实验完成。
5. 全仓回归、Ruff、前端测试/构建、旧版离线验收，交叉审查无阻断，PR与CI后merge/tag，直接继续已授权后续阶段。
