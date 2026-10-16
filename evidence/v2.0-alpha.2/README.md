# v2.0-alpha.2 实际浏览器证据

2026-10-16，127.0.0.1:8530，合成材料，无付费模型调用。

| 文件 | 可核对的事实 |
|---|---|
| demo-materials.jpg | 技术部案例显式加载后5份v1材料 |
| docx-preview.jpg | DOCX中文正文与表格、来源位置 |
| csv-mapping.jpg | 手动CSV上传、字段映射和实际5条快照 |
| validation-error.jpg | 错误映射产生具体行错误，阻止确认 |
| deduplicated.jpg | 正确映射后复用v1，仍5个版本 |
| local-api.jpg | 4条满意度从本地接口冻结确认，来源标记及6个版本 |
| materials-mobile.jpg | 390px窄屏列表及详情，页面宽度无溢出 |
| current-demo.jpg | 最终演示空间6份材料和DOCX来源预览 |
| normal-isolated.jpg | 同一演示服务normal空间0份材料，与demo空间隔离 |

部分截图为完整页面，需滚动查看；这不是统计或五角色自动报告演示。演示前后正常服务数据库SHA-256均为`d6322280bae8c30f96a16dda1d23d0bcbe42aef6fb31de5446542d77f726dffa`，核对后才升级正常服务。自动测试另用临时数据库。
