# v0.6 详细开发计划

日期 2026-10-10。基线 v0.5.0 / main `1a8349f611c291a5cf8261c76753c42f4c81bd4a`；分支 `feature/v0.6-web`。用户授权开发、上传 Git、每版 PR → CI/评审 → merge → 标签，本版发布 v0.6.0。真实开发者一人，三个 AI Agent 负责实际模块开发及交叉审查。

## 目标与实现决定

- Streamlit 单页办公工作台：需求输入、样例与自有文件上传、运行模式与预算、当前角色状态、需求/大纲/指标来源/审核/逐轮草稿/最终报告、Markdown 下载。PDF、账号与公网部署留后续；只启动本机服务。
- 复用 v0.5 的 run_workflow、AgentSession、save_workflow，不复制编排或放宽最终导出门禁。新增可选事件观察回调，真实 node_started 在执行前发布；工具、HTTP与node_finished来自实际记录，不能用计时动画假装进度。
- 每个浏览器会话持有一个 RunController；后台线程不调用 Streamlit。锁保护任务接纳和快照，同一控制器有任务时重复提交返回原任务，不产生新请求。fragment 定时只读快照，修改页面、下载、刷新不触发模型。终态后点“新建任务”才允许再提交。服务器重启/新浏览器会话不恢复后台任务，不声称跨重启 exactly-once。
- 输入先做文件白名单、2 MiB/文件、UTF-8、CSV字段/行数/业务值校验，再启动模型。必须上传 projects.csv、achievements.csv、issues.txt 三个固定文件，不接受路径、重复名或未知名。样例与上传均在接纳时冻结字节，实际执行在隔离临时目录，结束清理；结果按 run_id 独立保存，避免后续选择覆盖输入。
- 上传业务材料只存在本机会话/运行产物，显示数据来源类型；页面不展示密钥或原服务错误正文。后台异常返回固定安全文本，失败不提供最终报告下载；通过现有最终门禁才读取 report.md 生成下载。不要把原统计2/3展示成开发完成率。
- 默认 mock，不读取 .env、不调用外部模型；live须页面明确选择，读取现有本地配置，无密钥输入框。默认零网络重试；预算和实际用量分开显示，未知用量记不可用。故障实验为明确标记的可选入口，保存注入前后记录，不冒充模型自然错误。

## AI 分工与交叉审查

| 负责者 | 独占范围 | 开发交付 | 交叉审查 |
| --- | --- | --- | --- |
| 主协调 | web_schemas.py、workflow事件回调、CSV并发边界、依赖/CI、集成/浏览器、文档证据、PR发布 | 统一接口；独立整体验证与发布 | 汇总修复、最终验收 |
| AI A：任务运行 | web_runtime.py、test_web_runtime.py | 有界后台任务、线程安全防重、独立快照、隔离执行及安全下载 | 审 B 上传边界与临时材料 |
| AI B：上传数据 | web_uploads.py、test_web_uploads.py | 固定文件输入、复用原验证、字节冻结及安全错误 | 审 C 页面输入、模式和下载 |
| AI C：页面与UI测试 | app.py、web_ui.py、test_web_app.py | 中文页面、真实进度轮询、分层结果/下载、Streamlit AppTest | 审 A 重复提交、失败状态与预算 |

共享目录按文件范围分工；Agent不切分支、不提交Git、不读取密钥或调用真实API。主协调先提交计划/接口，再集成。每人运行模块测试并对另一个模块独立审查，修复闭环记在 review-v0.6.md。

## 阶段和验收条件

| 阶段 | 具体工作 | 验收 |
| --- | --- | --- |
| 1 计划与契约 | 固定上传/选项/快照/下载结构；选择兼容Python版本的Streamlit并锁依赖 | 计划先提交、独占范围明确 |
| 2 并行实现 | A后台与防重；B输入验证；C页面与AppTest；协调加实际事件回调 | 页面调用真实原图，各模块可单独测试 |
| 3 交叉审查 | 上传路径/格式/大小/数据错误、线程及会话隔离、无重复调用、失败不能下载最终报告、异常脱敏 | 问题修复并补有意义回归 |
| 4 综合与浏览器 | 样例成功、合法上传后统计变化、缺数据、错误输入阻断、返工修复/上限、页面rerun/下载、真实进度事件 | 后端测试/AppTest通过，浏览器看到与产物相同的真实运行结果 |
| 5 证据与发布 | 归档实际代码SHA/命令/测试/UI证据；GitHub新克隆；PR与精确提交CI；merge、v0.6.0 | 复现不依赖未提交必要文件，远端标签对应合并提交 |

本版复用 v0.5 已验证的真实DeepSeek接入，不默认再次付费；离线页面/HTTP夹具足以验证集成，不把mock输出或旧实测冒充本版新增真实API验收。如果必要实测，最多一次、请求/输出硬预算明确、零重试，先离线排查，不自动重复。

## 交付与限制

README真实启动命令 `uv run --locked streamlit run app.py --server.address 127.0.0.1`；新增页面使用、架构、审查、验收文档及精选 evidence/v0.6。实际浏览器截图仅在工具访问允许且真正捕获后归档，未捕获必须明确说明；图和终端文本不能替代截图。网页原型无用户鉴权/跨进程队列/持久任务恢复；课程最终报告和三人组队要求仍按老师要求处理。

Streamlit API依据官方文档核对：[fragment](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)、[文件上传](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader)、[AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)。具体测试数量、实际结果和发布状态按validation-v0.6.md记录，不把计划当成果。
