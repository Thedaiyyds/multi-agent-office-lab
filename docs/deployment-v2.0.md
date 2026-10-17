# 新版工作台安装与启动

新版统一使用 React/FastAPI 工作台，地址为 http://127.0.0.1:8520。课程操作见[普通案例演示](report-example.md)。

## 环境

- macOS 或 Linux；Windows 使用 WSL2。当前执行队列使用 Unix `fcntl` 进程锁，未验证原生 Windows。
- Git、Bash、uv、Node.js 22.12+ 或 24，以及 npm。项目复现使用 Python 3.12，由 uv 获取或选择已有运行时。
- 首次下载源码、运行时和依赖需要网络。依赖缓存齐备后可离线安装；“离线模拟”表示业务不向外部模型服务发送请求。

PDF使用仓库随附的OFL中文字体，不需要安装Office、系统中文字体或外部PDF服务。

## 首次运行

```bash
git clone https://github.com/Thedaiyyds/multi-agent-office-lab.git
cd multi-agent-office-lab
bash scripts/start_workbench.sh
```

脚本安装锁定Python依赖，运行`npm ci`及前端构建，再启动本机服务。打开 **http://127.0.0.1:8520**，保持终端运行。按Ctrl+C停止。

先免费体验时无需创建`.env`：点击“新建报告”，主动选择“离线模拟（不调用模型）”，按[普通案例](report-example.md)提交需求。离线角色回复由本地夹具提供，实际图调度、数据工具、审核、修订和PDF渲染仍会执行；页面与报告明确标识模式。

## 以后启动与停止

源码、依赖及前端构建均未变化时，在项目根目录执行：

```bash
uv run --locked office-workbench
```

更新代码后重新运行`bash scripts/start_workbench.sh`，确保锁依赖与前端构建匹配。不要在同一数据目录同时启动两个后台执行服务；队列进程锁会拒绝重复接管。若8520已占用，先回到原启动终端停止旧进程，然后再启动。

数据位于项目的`outputs/workbench/`：SQLite业务记录、材料原件、报告修订和交付文件均保留。重启后可查看已完成任务和下载已有文件；原在途任务会标记中断，不自动重发模型请求。保留整个目录才能一起保留数据库与文件。普通关闭、更新及演示不需要删除此目录。

## 真实模型配置

```bash
cp .env.example .env
```

在本地编辑`.env`，填写兼容模型服务的`LLM_BASE_URL`、`LLM_MODEL`和`LLM_API_KEY`，然后重启服务。已有`.env`时直接编辑，避免覆盖已有配置。

页面“系统设置”仅显示配置状态，不显示密钥。选择“真实模型协作”后会按服务器预算调用已配置服务，产生API用量；没有配置时不会静默切换模拟。日常查看、刷新、下载及本地文件重导出不发出新模型请求。运行失败先查看角色与静态错误，避免无目的重复提交。

`.env`、`outputs/`、用户材料和生成文件不上传Git；课堂只展示合成材料及已脱敏证据。

## 开发和离线验收

安装与构建完成后可执行：

```bash
uv run --locked pytest -q tests/test_workbench_execution_acceptance.py tests/test_workbench_delivery_acceptance.py
npm --prefix frontend test
npm --prefix frontend run build
```

专项测试使用临时数据库、普通合成材料和本地MockTransport。它们不会使用正在运行服务的正常任务或真实模型密钥；其中`mode=live`的适配器测试也由显式MockTransport拦截，不是外部供应商成功证据。

需要前端热更新时，开发者分别在两个终端运行：

```bash
uv run --locked office-workbench --api-only
```

```bash
npm --prefix frontend run dev
```

这是开发方式，课堂演示继续使用首次运行步骤的正常8520入口。历史Streamlit和旧版CLI文档保留为历史基线。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 提示uv、node或npm不存在 | 安装环境后重新打开终端，再运行启动脚本 |
| Python3.12或依赖下载失败 | 检查网络及包源；有完整缓存时可用uv的`--offline`安装 |
| 前端页面缺失或显示旧界面 | 停服务后重新运行完整启动脚本，浏览器再刷新 |
| 真实模式“开始协作”不可用 | 查看系统设置配置状态，或主动改用离线模拟 |
| Manager提示补充信息 | 需求写明唯一部门、年份季度或明确起止日期 |
| Data提示缺材料 | 选择本次已确认材料，或明确勾选系统本地虚构样例接口 |
| 修改后不能下载新稿 | 先进行Checker审核与Manager验收；旧合格历史仍可下载 |
| PDF或Markdown文件损坏 | 在合格修订点击“生成 / 重试文件”；不会重跑模型 |
| 服务重启后原任务中断 | 回看已保存过程，确认业务后明确提交新任务；系统不自动重发付费请求 |

实际新源码副本安装结果见[alpha.6复现记录](validation-v2.0-alpha.6.md)。
