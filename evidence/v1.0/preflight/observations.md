# 修复前实际观察

2026-10-10，产品源08c9f9c329f293b8620d4fafa7643976a9cc0d56。该目录保存最终验收前的真实浏览器截图和运行产物，不能当作修复后的证据。

正常研发Q2运行680f3fcd-4540-4bb4-b69e-1d0b4244804f成功，6次本地模拟HTTP；下载report.md与服务器保存文件字节一致（SHA见index.json）。市场Q2两次运行acbdf85a-6af6-4732-9670-c21d3f40dafb、e1323e4d-32e6-4695-8022-c33e2740a86d均成功，实际需求、正文、指标为市场部及1/0/0/1。但提交后左侧禁用表单显示默认研发需求，形成误导显示；没有生成错误部门报告。

B初次增加稳定widget key及保留测试后，主协调实际全套运行得到593 passed、2 failed（6.27秒）：test_accepted_nondefault_input_stays_visible_until_explicit_new_task的需求保留断言失败；test_uploaded_valid_files_change_statistics_in_ui的上传来源保留断言失败。原assert未删除，继续修复，最终复验见外层索引。此记录不宣称第一次修复已通过。所有调用离线，外部API为0。
