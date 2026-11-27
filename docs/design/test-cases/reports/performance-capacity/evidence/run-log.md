# 性能测试执行日志摘要

本文件根据本次隔离实验室终端日志、驱动输出、nginx upstream 统计和原始 JSON 归纳。详细数值以 [`P-RUN-01`](P-RUN-01/)、[`P-RUN-02`](P-RUN-02/)、[`P-RUN-03`](P-RUN-03/) 和 [`P-RUN-04`](P-RUN-04/) 中的机器报告为准。

## 2026-11-27 14:00—14:03 环境 smoke

- 首次 smoke 在写入前被 OSS 前缀守卫拒绝：随机临时目录包含下划线，不符合隔离前缀格式；清理后重新生成纯十六进制目录。
- 第二次 smoke 暴露空数据库未执行 Flyway；增加 `db reset` 前置后通过。
- 4 用户／40 商品 smoke：
  - Search 5 HTTP RPS：粗测和确认均通过。
  - IM 2 场景/s、4 个接收 WebSocket：通过。
  - 两个 WS 实例各收到 2 个 `101` 握手，证明 nginx WS 分流生效。
  - IM 期间 `work_stream=0`、worker pending=0。

## 14:04—14:25 默认 capacity 与首批扩容

| 时间 | RUN／配置 | 结果 |
|---|---|---|
| 14:04:08—14:04:13 | seed 100 用户／10,000 商品 | 101 账户、10,000 商品、100 交易对、100 会话；OSS 对象存在 |
| 14:04—14:10 | P-RUN-02：API 1 / WS 1 / worker 1 | 200、400 HTTP RPS 均通过；400 再持续 300 秒通过；P95 17.68 ms |
| 14:10—14:17 | API 2 / WS 1 / worker 1 | 200、400 均通过；400 持续 300 秒通过；P95 19.55 ms |
| 14:17—14:24 | API 4 / WS 1 / worker 1 | 200、400 均通过；400 持续 300 秒通过；P95 19.26 ms |
| 14:24—14:25 | 原计划的 IM 120 秒验证 | 因用户将后续目标改为性能上限而中止；临时依赖与 OSS 前缀正常清理 |

结论：默认 400 HTTP RPS 不由 API 实例数决定；单 API 已通过。

## 14:25—14:45 短档上限与 worker A/B

20 秒档、5 秒预热、同速 20 秒确认，自动 refinement 最终关闭或仅用于一次性边界搜索。

| 场景 | 结果摘要 |
|---|---|
| Search API 1，400→800 | 400 通过；800 实际约 741 RPS 时 in-flight 达 2,045，admission drop 591；P95 3.32 s |
| Search API 2，400→800 | 800 的请求可完整排入，但 P95 476.7 ms；一个本机 late arrival 使该轮标记不可判定 |
| Search API 4，400→800 | 800 P95 2.19 s，尾窗 pending 1,657；API 4 未改善 |
| IM WS 1，200／400／800 场景每秒 | 200、400 通过；400 历史 hint P95 559 ms。800 P95 7.34 s、58 个送达错误、pending 2,032 |
| IM WS 2，200／400／800 | 400 历史 hint P95 110 ms；800 P95 6.82 s、pending 2,047 |
| IM WS 4，200／400／800 | 400 历史 hint P95 240 ms；800 P95 5.14 s、WS 实例分布 25/25/25/25 |
| mixed worker 1，100／150／200 | 100 通过；150 样本不足；200 发布／上传短样本及 503，三档 `work_stream=0`、pending=0 |
| mixed worker 2，100／200 | 100 首轮通过、确认失败后细分；99 通过；200 同样失败；worker 仍为空闲 |

结论：Search 短窗拐点位于 600—800 RPS；IM 稳定档在 400 场景/s，600 已过载；worker 不是 mixed 或 IM 瓶颈。

## 14:52—15:04 定向复测与收窄

第一轮固定 800 测试暴露测试器行为：当粗测通过但同速确认失败时，默认继续做 lower-rate refinement，导致重复长时间试验。按用户“性能上限优先、不关注验证要求”的指示中止，设置 `--capacity-refinements 0` 后只保留单档短测。

| 场景 | 结果摘要 |
|---|---|
| Search API 1，600 RPS | 粗测 P95 221 ms、pending 10；确认 P95 18.7 ms、pending 11，仅 1 个本机 late arrival |
| Search API 2，600 RPS | 粗测 P95 2,191 ms，确认 P95 23.8 ms；两窗均可排空，但冷窗已明显排队 |
| Search API 4，600 RPS | P95 4,713 ms、pending 2,546；增加至 4 实例反而过载 |
| IM WS 1／2／4，600 场景/s | 历史 hint P95 10.07／10.12／8.71 s；错误 492／527／85；全部过载 |

定向结果支持以下运行建议：

- 默认 Single Search 400 HTTP RPS 使用 API 1 已够；如需冗余或覆盖 600 RPS 附近余量，使用 API 2。该结论不泛化到任意业务组合。
- IM 在 400 场景/s 使用 WS 2；WS 4 无进一步收益。
- 不建议 API 4／WS 4；不建议增加 worker。

## 15:04—15:10 初次复验与清理

- `cargo test --locked --manifest-path loadtest/Cargo.toml`：
  - 沙箱内首跑 23/29，通过；6 个需绑定 loopback 临时端口的测试被系统权限拒绝。
  - 在本地网络权限下重跑，当时 29/29 通过，0 failed。
- 正式超上限档因用户需求变更只做短窗，不再做 300 秒长期验证；默认 400 RPS 的 300 秒证据不受影响。
- OSS 前缀经删除与二次检查为空；临时 PostgreSQL、Redis、JVM、nginx、manifest 和报告目录均已清理。

## 15:20—16:07 review 修正、稳定性修复与最终干净源码复跑

- PR review 指出两项 P1：
  - 首次 P-RUN-01 的后端 JAR 来自含 PR 外未提交案件改动的开发工作树。
  - WS hint 可能先于发送 HTTP 响应到达，旧实现可在 expected `message_id` 尚未绑定时提前完成送达。
- 修复 IM 关联：
  - 提前到达时缓存 hint 的真实到达时刻、message_id 与 seq；不提前完成。
  - 发送响应返回后核对发送端与接收端 message_id／seq，再由 HTTP 回读正文并核对 body。
  - ID 或 seq 不匹配返回失败结果，不记为送达。
  - 新增“WS 先于 HTTP 响应”和 ID／seq 不匹配单测；loadtest 31/31 通过。
- Re-review 指出 IM 竞态修复误把 HTTP 回读开始作为送达计时起点，导致 `im_delivery` 与 `im_retrieval` 近似相等。提交 `c07f13e7` 恢复发送前 `Instant`，在正文 HTTP 回读完成时冻结样本；若 hint 先到，等待发送响应的额外时间不计入已完成的端到端耗时。
- 并行 capacity 测试的临时目录加入唯一监听端口名，提交 `5f411e50`；连续 3 次 cargo test 均 31/31，Clippy 通过。
- 计时修正后的干净预跑中，上传授权和完成核验仍分别重复查询 Bucket ACL／versioning：
  - 两次计时修复后预跑分别出现 5 与 19 个约 5 秒的 OSS 元数据超时；第三次预跑被中止，OSS 前缀经二次检查为空。
  - `acfa5d37` 从上传授权、完成核验和清理路径移除重复 bucket 配置查询，只保留部署依赖探针的一次性校验。
  - 改后复跑不再出现 upload lease 的 bucket 检查超时，但仍有 10 个 completion 503 和 1 个上传连接中断；独立探测 OSS 根端点 20 次为 47—192 ms，未发现网络级持续抖动。
  - `93f612b7` 将上传控制器改为复用进程级 OSS 客户端并在关闭时释放，避免每请求创建／销毁 SDK 客户端。
- 最终从干净提交 `93f612b7f9963b919cc45a473cb60ad2de97f664` 重建后端、maintenance 与 release 驱动：
  - 执行 P-RUN-01：100 用户／10,000 商品、30/120 秒、think 1 秒，1 scheduler／1 worker／1 API／1 WS。
  - 结果：21,334 HTTP 请求、177.78 HTTP/s；零 HTTP 错误、零 WS 断连、零重连失败。
  - 必需 HTTP 操作 P95 最大 341.72 ms；`im_delivery` P95 314.74 ms、`im_retrieval` P95 2.44 ms，两项分别表示“发送 POST 开始→接收方正文回读完成”和“接收方 hint→正文回读完成”。
  - 562 次上传授权、对象上传、完成核验和发布全部成功；worker 与 scheduler 峰值 CPU 约 1%。
- P-RUN-02／03 容量结果保留首次实验数据，并在报告中注明实际被测 JAR 摘要与“不证明 PR 外业务改动／完整客户端”的边界。
