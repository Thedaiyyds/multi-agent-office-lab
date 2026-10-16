# v2.0-alpha.1 实施计划

2026-10-16，依据 `docs/proposals/v2.0-review/development-spec.md`，用户已授权实施。

本版交付可实际操作的首页、报告任务、新建/编辑草稿和持久化，供用户审查界面。材料解析、指标工具、五角色运行、审核与导出依次在 alpha.2–alpha.5 实施；当前版本不把这些能力显示为已完成。主要界面经用户认可后进入 alpha.2，遵循说明书第14节的阶段门槛。

## 分工与开发步骤

| 工作 | 责任角色 | 文件范围 | 退出条件 |
| --- | --- | --- | --- |
| 冻结接口和阶段范围 | 主协调者 | 本计划、依赖配置 | 日期半开区间、空间、版本和错误契约一致 |
| 数据库存储与 API | A 后端 Agent | src/office_agents/workbench、tests/test_workbench_api.py | 真实草稿、重启持久、空间隔离、409 冲突、输入校验 |
| 页面及交互 | B 前端 Agent | frontend | 空白首页、新建、搜索、详情、编辑、演示入口、可访问布局 |
| 独立测试与审查 | C 质量 Agent | docs/releases/v2.0-alpha.1-test-plan.md | 明确测试结果与尚未验证项，发现问题反馈修复 |
| 集成与发布 | 主协调者 | 启动入口、CI、README、发布记录 | 锁定依赖、构建、离线回归、浏览器检查、PR/CI/merge/tag |

## 共享接口

- 所有业务路由位于 `/api/v1`。请求头 `X-Workspace: normal|demo`，默认 normal；返回记录包含 workspace。跨空间按不存在处理。
- `GET /reports` 返回 `{items: Report[]}`；支持 search、status。新建 `POST /reports`，读取 `GET /reports/{id}`，保存 `PATCH /reports/{id}/draft`。
- Report 字段：id、workspace、title、department、start_date、end_date、focus、sections、version、status、created_at、updated_at。
- 创建字段：title、department、start_date、end_date、focus、sections。日期采用 `[start_date,end_date)`；至少一个章节，重点可空。
- 编辑增加 expected_version；旧版本返回 409，不能无提示覆盖。新建使用幂等键，防止请求结果未知后的重复创建。
- `GET /health` 检查服务；`GET /system` 返回版本、能力列表、模型是否已配置，不返回密钥、模型 URL 或本地绝对路径。

## 本版验收

1. 空数据库没有报告案例、虚构统计、故障开关和原始 JSON。
2. 草稿经 API 保存后刷新、重启可读取；数据库保存在 outputs/workbench（Git 忽略）。
3. 正常与演示的列表、读取、编辑均隔离；切换空间不串入未保存表单。
4. 同版本两次写入中仅第一次成功；失败保留输入、可显式刷新。
5. 真实浏览器检查首页、新建、保存、编辑、搜索、演示隔离、窄屏和键盘操作。
6. 依赖锁、前端构建、API测试、旧版离线回归及 CI 均通过后合并；如实记录未完成项。

全程默认离线，不发送新的模型请求。AI 分工如实记录，Git 不伪造三名人类作者。
