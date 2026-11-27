# 性能与容量证据目录

本目录保存 TC-PERF-001 的可复核证据。原始 manifest、Cookie、CSRF、OSS 凭据、随机前缀和完整私有环境已清理；JSON 保留驱动生成的参数、阶段、P50／P95／P99、错误、in-flight、资源和汇总字段。

| 文件 | 内容 |
|---|---|
| [`env-setup.md`](env-setup.md) | 代码版本、二进制摘要、主机、依赖版本、数据隔离、服务拓扑和清理结果 |
| [`commands.md`](commands.md) | 数据库／Redis／OSS 前置、种子、服务启动、nginx 分池、驱动和远端观测命令 |
| [`run-log.md`](run-log.md) | 按时间归纳 smoke、正式容量、上限、worker A/B、测试器偏差和清理过程 |
| [`loadtest-tests.log`](loadtest-tests.log) | `cargo test` 沙箱端口权限失败记录、IM 竞态修复后 31/31 通过及干净 worktree 复跑 |
| [`file-storage-tests.log`](file-storage-tests.log) | Bucket 配置检查收敛、上传签名无 OSSClient 交互、客户端复用上下文及 file-storage 17/17、backend-app 7/7 |
| [`maintenance-tests.log`](maintenance-tests.log) | `maintenance -am` Maven 单测 78/78 通过记录 |
| [`clean-source-build.log`](clean-source-build.log) | 干净提交 `93f612b7` 的后端、维护工具、驱动构建及 SHA-256 |
| [`legacy-issue-34.md`](legacy-issue-34.md) | legacy Python／FastAPI Mac capacity 对照及 Issue #34 链接 |
| [`P-RUN-01/baseline-100u-10k-20261127.json`](P-RUN-01/baseline-100u-10k-20261127.json) | 从干净 PR 提交 `93f612b7` 重建的 100 用户／10,000 商品、30/120 秒稳态报告；移除逐请求 samples，保留全部聚合指标 |
| [`P-RUN-01/clean-source-summary.json`](P-RUN-01/clean-source-summary.json) | 干净 worktree 的宿主、拓扑、进程与运行汇总 |
| [`P-RUN-02/capacity-default-api1-ws1-w1.json`](P-RUN-02/capacity-default-api1-ws1-w1.json) | API 1 的默认 capacity 完整报告 |
| [`P-RUN-02/capacity-api2-ws1-w1-search400.json`](P-RUN-02/capacity-api2-ws1-w1-search400.json) | API 2 的默认 capacity 完整报告 |
| [`P-RUN-02/capacity-api4-ws1-w1-search400.json`](P-RUN-02/capacity-api4-ws1-w1-search400.json) | API 4 的默认 capacity 完整报告 |
| [`P-RUN-03/capacity-limits-20261127.json`](P-RUN-03/capacity-limits-20261127.json) | Search、IM、mixed 的分档边界汇总 |
| [`P-RUN-03/capacity-perf-narrow-20261127.json`](P-RUN-03/capacity-perf-narrow-20261127.json) | 600 RPS Search 与 600 IM 场景/s 的定向收紧汇总 |
| [`P-RUN-03/perf-search-api1-r600.json`](P-RUN-03/perf-search-api1-r600.json) | API 1、Search 600 RPS |
| [`P-RUN-03/perf-search-api1-r800.json`](P-RUN-03/perf-search-api1-r800.json) | API 1、Search 800 RPS 过载 |
| [`P-RUN-03/perf-search-api2-r600.json`](P-RUN-03/perf-search-api2-r600.json) | API 2、Search 600 RPS |
| [`P-RUN-03/perf-search-api2-r800.json`](P-RUN-03/perf-search-api2-r800.json) | API 2、Search 800 RPS 过载 |
| [`P-RUN-03/perf-search-api4-r600.json`](P-RUN-03/perf-search-api4-r600.json) | API 4、Search 600 RPS 过载 |
| [`P-RUN-03/perf-search-api4-r800.json`](P-RUN-03/perf-search-api4-r800.json) | API 4、Search 800 RPS 过载 |
| [`P-RUN-03/perf-im-api2-ws1-r600.json`](P-RUN-03/perf-im-api2-ws1-r600.json) | 单 WS、600 IM 场景/s |
| [`P-RUN-03/perf-im-api2-ws2-r600.json`](P-RUN-03/perf-im-api2-ws2-r600.json) | 双 WS、600 IM 场景/s |
| [`P-RUN-03/perf-im-api2-ws4-r600.json`](P-RUN-03/perf-im-api2-ws4-r600.json) | 四 WS、600 IM 场景/s |
| [`P-RUN-04/worker-ab-summary.json`](P-RUN-04/worker-ab-summary.json) | 从 P-RUN-03 提取的 worker 1／2 mixed A/B、`work_stream` 和 pending 汇总 |

## 证据摘要

- 默认 capacity 的 3 份报告均验证 400 HTTP RPS 持续 300 秒；Search P95 为 17.68／19.55／19.26 ms。
- 干净提交的代表性 100 用户稳态共记录 21,334 个测量 HTTP 请求，177.78 HTTP/s；必需 HTTP 操作 P95 最大值 341.72 ms，`im_delivery` P95 314.74 ms、`im_retrieval` P95 2.44 ms，零 HTTP 错误和零 WS 断连。
- `im_delivery` 从发送 POST 前开始，到接收方正文通过 HTTP 回读并完成 `message_id + seq + body` 校验为止；`im_retrieval` 仅从接收 hint 开始。
- Search 600 RPS 已接近可用边界，800 RPS 过载；API 4 在 600—800 RPS 没有扩容收益。
- API／WS 历史容量档中 IM 400 场景/s 通过、600 场景/s 过载；这些档位来自最终计时修复前驱动，只作相对边界。最终送达证据以 P-RUN-01 为准，浏览器实际显示与目标部署跨实例仍待验收。
- mixed 100 场景/s 通过，200 场景/s 失败；worker 1／2 的 `work_stream=0`、pending=0、CPU 约 1%，只说明本次 mixed 负载不需要扩 worker，不评价 worker 自身饱和容量。

## 隐私与可复现性

- 数据账户来自确定性 seed，但 manifest 及其密码、邮箱、会话和 CSRF 不提交。
- OSS 证据仅保留报告与对象数量摘要，不保留上传策略、签名和完整 URL。
- 压测运行使用真实服务；无需 Mock。SMTP 不在本案例操作配比中，明确未执行。
