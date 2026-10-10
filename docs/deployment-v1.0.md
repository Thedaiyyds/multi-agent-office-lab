# v1.0 安装、运行与复现

v1.0.0 是当前课程交付版。使用 Python 3.12、uv 与仓库锁文件；首次获取运行时、依赖和源码需要网络，下面的离线业务运行不访问外部模型。不需要先创建 `.env`，也不需要提供 API 密钥。

## 获取与安装

```bash
git clone https://github.com/Thedaiyyds/multi-agent-office-lab.git
cd multi-agent-office-lab
git checkout v1.0.0
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked python -c 'import office_agents; print(office_agents.__version__)'
git rev-parse HEAD
```

上面的标签命令用于正式发布后复现；开发审查时应改为实际 PR 的 commit SHA，不能把计划中的标签当成已经发布的结果。实际发布与验证状态见 [本版验收记录](validation-v1.0.md)。Python 3.13 在声明范围内，但课程复现统一采用 Python 3.12。

## 一条命令做八场景验收

```bash
uv run --locked office-agents acceptance --output-dir outputs/acceptance
```

命令只执行真实原图、确定性本地 HTTP 夹具、工具、审核和导出，不加载模型环境配置；没有 `live` 选项。每次建立新的 suite UUID 目录，不覆盖上次运行。终端列出每个场景的实际状态和 PASS/FAIL，并给出 JSON 索引位置。整体检查通过返回 0；任一检查未达预期或安装/写入失败返回 1。

八个场景为研发 Q2、研发 Q1、市场 Q2、错误字段上传、缺关键需求、错误事实返工、持续错误达到上限、模拟模型超时。`needs_input`、`review_failed`、`failed` 和 `input_rejected` 是部分场景的预期业务结果，只有实际状态、请求次数、审核及无最终报告等检查均通过，该场景才记为 PASS。PASS 不等于每个业务任务都生成报告。

查看生成索引及对应 `run.json`、`events.jsonl`、逐轮草稿和审核意见；成功流程才有最终 `report.md`。全部自动 `outputs/` 被 Git 忽略，精选实测证据位于 [v1.0 证据目录](../evidence/v1.0/README.md)。本地夹具请求数不是付费 API 次数，mock 的模型 token usage 记录为不可用。

## 启动网页工作台

```bash
uv run --locked streamlit run app.py --server.address 127.0.0.1
```

打开终端显示的网址，默认 `http://127.0.0.1:8501`。若端口占用可追加 `--server.port 8517`，并访问对应端口；按 Ctrl+C 停止服务。默认选择“离线模拟”与“实验样例”，按 [现场演示步骤](demo-v1.0.md) 输入需求。页面及 CLI 使用同一 LangGraph 工作流、数据统计与最终导出门禁。

每个页面会话只保留一个任务；终态后点“新建任务”才能再次提交。后台执行时修改、页面轮询或下载不会追加模型请求。服务器重启或新浏览器会话不承诺恢复原任务。输出按 UUID 保存在本地 `outputs/web/`，输入暂存结束后清理。

## 可选的真实模型与报告重建

只有显式选择真实模式才使用本地配置；参考 [模型配置说明](setup.md)。使用已有有效的服务地址、模型标识及密钥，不把密钥放在报告、截图和 Git 中。真实运行会产生用量，验收命令始终保持离线。历史 DeepSeek 实测对应原版本，详见 [v0.5 实际记录](validation-v0.5.md)，不能视为 v1.0 新增真实调用。

如需由可编辑 Markdown 重新生成实验报告 Word，使用独立报告依赖组：

```bash
uv sync --locked --group report
uv run --locked --group report python scripts/build_experiment_report.py
```

普通网页和 CLI 不需要报告依赖组。脚本只重建项目实验报告；本版业务报告仍导出 Markdown。提交前按 [提交清单](submission-v1.0.md) 填好身份信息并检查重新生成后的版面。

## 回归与排错

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

| 现象 | 处理 |
| --- | --- |
| `uv` 或 Python 未安装 | 先安装 uv，再运行上述 Python 安装及锁文件同步命令；不要直接替换锁定依赖版本 |
| 锁文件与声明不一致 | 确认检出完整版本/PR；不要用无锁安装掩盖版本不一致 |
| 网页端口占用 | 停止旧服务或显式选新端口，访问终端实际显示的网址 |
| 上传被拒绝 | 上传三个固定名文件，检查 UTF-8、字段和业务值、每文件 2MiB 限制；等上传列表完整后再提交 |
| 无最终报告 | 看实际状态及每轮意见；补齐关键需求，修复数据或草稿后新建任务，失败产物不能作为审核通过报告 |
| 页面保留旧任务 | 终态点击“新建任务”；运行中不能重置，也不要通过重复提交来促使更新 |
| 验收写入失败 | 使用可写目录，查看安全错误与真实退出码；不要手工把索引改成通过 |

若遇到测试超时，保留命令、实际 SHA 和原始日志后复现；不能删掉断言或将未复现的原因写成已证实。历史 AppTest 初始化慢问题与实际修复边界见 [v0.6 验收](validation-v0.6.md)。本版的实际检查数量和新克隆结果由协调者完成后记录在 v1.0 验收文档。
