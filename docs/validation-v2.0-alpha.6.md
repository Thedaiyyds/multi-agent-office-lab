# v2.0-alpha.6 安装与普通场景独立复现

2026-10-17。本记录区分精确alpha.5发布源码复现、alpha.6新测试增量、最终alpha.6提交与真实模型验收；不能互相代替。

## 干净源码副本

从已合并发布的`v2.0-alpha.5`提交`f39dee89f7f6954dcfd422ef0a5040d679950a37`执行本地`git archive`，解包至临时目录。副本初始没有`.env`、`.venv`、`node_modules`、前端`dist`或业务输出；没有复制开发者配置与正常数据库。使用新的虚拟环境和新安装的前端依赖，包缓存可复用，因此不声称是在无缓存的新机器上验证。

本机：macOS arm64，Python3.12.15、uv0.12.23、Node24.15.0、npm11.12.1。没有启动另一个业务端口；正常API、执行队列、SQLite和真实本地PDF通过TestClient及临时数据库验证。

锁文件SHA256：

```text
uv.lock                      ca92b776bc56c4ce921cf58d584eacd679d3e4412b05a7b6d8d8d54bfa5e0ae3
frontend/package-lock.json   545861f7b5248dd707ba69330019fb49b602044e87dab91e1ea7bdf8ec8c2c24
```

## 实际执行

| 命令 | 实际结果与边界 |
| --- | --- |
| `uv sync --locked --offline --python 3.12` | 成功，创建新.venv，从缓存安装锁定依赖 |
| `npm --offline ci` | 默认npm缓存缺Vite6.4.4，明确ENOTCACHED失败；没有自动联网 |
| `npm --offline --cache /private/tmp/office-v2-npm-cache ci` | 改用开发时已有的完整包缓存，安装82个包成功；该缓存路径是本次机器环境，不是用户必备目录 |
| `uv run --locked --offline pytest -q tests/test_workbench_execution_acceptance.py tests/test_workbench_delivery_acceptance.py` | 精确alpha.5副本47项通过，14.60秒 |
| `npm test` | 精确alpha.5副本13项客户端测试通过 |
| `npm run build` | 精确alpha.5副本TypeScript及Vite6.4.4生产构建通过 |
| alpha.6新增重启闭环测试叠加到副本后执行`pytest -q tests/test_workbench_delivery_acceptance.py -k restart` | 1项通过，0.69秒；这项明确是新测试增量，不称为alpha.5原始文件 |

“离线”在本次还包括安装时使用`--offline`，没有为缓存缺失隐式改成联网。首次无缓存的用户仍需联网获取依赖，按[正常启动说明](deployment-v2.0.md)运行即可。所有角色请求均由显式MockTransport提供，测试不读取真实密钥，不产生付费模型请求；这不是DeepSeek端到端成功证据。

副本目录及完整机器JSON摘要暂存于`/private/tmp/office-alpha6-repro-37l46yfk/`，是独立开发验收目录，不是新增产品演示空间。

## 业务链路覆盖

技术部Q2与行政部Q1普通材料经正常导入/确认接口进入临时正常数据库，实际LangGraph运行Manager→Planner→Data→Writer→Checker→Manager。审核合格后自动生成两格式文件。测试直接用标准库计算快照/文件哈希，用pypdf解析真实PDF文本并检查嵌入字体流；没有用伪PDF替代渲染器。

技术场景核对项目4/完成2/成果3；考勤样本计划32、实际28、请假4小时，样本87.5%，季度覆盖与整体率未定义。行政场景核对同量表4份反馈均值4.0，不编造历史提升。两个场景均保留来源、限制和模式标识。

新增重启闭环依次验证：首次正常图6次本地脚本回复→MD/PDF合格快照→关闭整个应用→同库新建应用→旧文件字节与运行用量不变，启动及查看不发出任何新角色请求→编辑形成待审核新修订→只执行Checker与Manager两次本地脚本请求→新修订可下载且旧合格版本仍以历史方式保留。

已有独立交付测试继续覆盖非法编辑、双角色拒绝、预算与幂等、空间404、文件损坏重导出、需求变更状态及取消晚到返回；新增重启测试本机单项通过。副本重启后的模型请求数由独立脚本Provider记录，不通过猜测日志或页面动画判断。

## 最终alpha.6提交核验

待主协调者形成alpha.6候选提交后，从该精确提交再生成无.env新源码副本，做短回归核验，并补入实际SHA及结果。当前上述47项是alpha.5精确基线，不提前写为alpha.6最终提交通过。

浏览器正常8520、新版归档页、最终真实模型场景与最终CI由主协调者统一验收并记录，避免多人争用同一页面或重复付费调用。正式版课程报告需使用最终实测数据；本记录不宣称所有实验验收已完成。
