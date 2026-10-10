# v0.6 实际协作与审查

真实开发者一人；A/B/C是本轮实际分派的AI Agent，不是三名人类作者。计划在实现前提交于eab10c9，独占文件开发，主协调集成，不伪造人类提交或评审身份。

| 角色 | 已实现与模块验证 | 实际交叉审查 |
| --- | --- | --- |
| A 任务运行 | web_runtime.py；18项测试。后台原图、线程接纳锁、防重、冻结选项与数据、深拷贝快照、清理、预算与导出门禁 | 审B上传源码与33项测试：白名单、内容校验、xb拒绝覆盖、回滚及清理无阻断 |
| B 上传数据 | web_uploads.py；33项测试，与原工具回归共97项。3固定文件、大小/UTF8/字段/业务值、样例/上传字节快照 | 独立执行C页面11项初版AppTest；发现错误表残留并要求修复 |
| C 页面与UI验收 | app.py、web_ui.py、test_web_app.py；13项初版AppTest。中文输入、真实进度、审核/来源/草稿/下载、模式与预算 | 独立运行A18项runtime测试；锁、防重、预算、脱敏、清理和final门禁无阻断；反馈来源测试索引错误并闭环 |
| 主协调 | 共享契约、依赖锁、真实图事件观察者、CSV并发锁、4项独立HTTP级集成、浏览器原生上传/下载及截图、Git复现与发布 | 检查页面生命周期、实际统计变化、下载字节和全部状态，不放宽v0.5审核规则 |

## 发现与修复

| 发现 | 修复与证据 |
| --- | --- |
| 节点开始事件旧实现只在动作完成后形成，不能用于网页实时运行状态 | on_event在动作前发送真实node_started，节点结束后发送实际HTTP/tool/finish；观察者收到深拷贝，异常不能改写记录或重放请求。test_workflow_observer的HTTP handler在真正请求前核对角色开始事件，坏观察者不影响6次请求正常完成 |
| CSV field_size_limit是进程全局，网页预检和多个任务可能并行更改 | 修改/解析/恢复整个区域加RLock，模型执行保持独立；原大字段/恢复测试及双会话真实图集成通过 |
| 新的配置错误仍可能显示旧上传问题表 | B指出，C在新的安全错误分支清除旧office_input_issues，补空需求及旧错误清除回归 |
| 表单首次提交后未冻结；新建任务按钮在fragment外可能一直禁用 | 主协调指出，C成功接纳后fullrerun冻结表单，把新建按钮放入轮询fragment，终态自动启用。test_active_task_freezes_form_and_terminal_poll_enables_new_task及浏览器初次/返工/新任务操作通过 |
| 样例选择可能被已有上传字节错误阻止 | 页面明确选择样例时忽略旧上传控件值并显示说明；底层prepare_input仍拒绝直接混合模式，独立入口边界不放宽。对应AppTest及浏览器从上传转回样例通过 |
| 来源SHA测试按列表首项取projects来源，排序改变时误判 | C反馈，A改为按source_id查询；独立自有数据/原样例同时执行，完成数和SHA分别一致 |
| 产物识别名与下载文件名可能混淆 | Snapshot.name保持canonical report.md/相对路径；浏览器download filename加runUUID前缀，UI按name与双completed门禁识别最终产物。下载bytes与实际导出逐字节一致 |

后台异常安全固定文本，不包含原异常、Pydantic输入payload或服务错误正文。主协调的provider401夹具确认无final下载、实际1HTTP停止、private文本不出现在审计/错误。8线程并发提交16次仅接纳1任务；等待真实首个HTTP的独立测试看到Manager running，并验证活跃reset拒绝。独立会话分别统计研发/市场，UUID、来源和下载不共用。

## 测试边界与后续复现

AppTest默认使用真实controller和mock原图；上传控件由夹具替换，实际内容验证和统计没有被替换。浏览器验收另用真实原生input[type=file]和浏览器下载，核对结果/导出字节并捕获实际页面，不将AppTest冒充原生浏览器操作。

新克隆第一次完整运行出现一个AppTest第二次run超时，其余573项通过，日志保留在 [初次新克隆失败](../evidence/v0.6/clean-clone-initial-failure.txt)。C对原克隆进行了12次独立首UI测试、6轮完整套件及一次冷pycache套件，均未再现超时；原失败没有线程栈，无法断言是rerun竞态、死锁或冷导入。随后仅改测试生命周期：在pytest主线程初始化首次表格渲染所需pandas/pyarrow，teardown等待后台任务结束，保留20秒超时、实际表格与全部原图断言。5轮独立13项UI复测和全574项通过，见 [AppTest复测](../evidence/v0.6/app-rechecks.txt)。产品源码未因该问题修改。新克隆启用faulthandler_timeout=10留潜在失败栈；具体复现与最终状态见 [validation-v0.6](validation-v0.6.md)，不删除失败记录或据此直接声称首次复现成功。

当前防重保证只覆盖同一RunController/页面会话，不覆盖服务器重启、不同会话或重新打开页面后的新任务。最终报告有受约束事实说明，建议仍需人工评估；没有新增真实付费模型验收，本版API用量按实际记录为0。截图是明确标记offline_mock的实际网页；不能冒充live模型输出或三人组队完成。
