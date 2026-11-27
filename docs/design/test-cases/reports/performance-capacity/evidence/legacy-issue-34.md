# legacy Mac capacity 对照

来源：[Issue #34](https://github.com/iy88/se-course-project-1/issues/34) 的 comments。2026-11-27 使用只读 `gh issue view` 重新核对。

## 环境

- Apple M5 Pro，18 逻辑 CPU，macOS arm64。
- Python／FastAPI 后端，单 Uvicorn worker；Rust 驱动与后端同机 loopback。
- 本机 PostgreSQL／Redis，远端 OSS 双 Bucket。
- 100 用户、10,000 商品；30 秒预热、120 秒采样、think 1 秒。

## capacity 结果

| 场景 | 结果 |
|---|---|
| single search 400 HTTP RPS | 提高测试器在途上限后持续 300 秒通过；P95 32.9 ms、P99 73.7 ms |
| mixed 100 场景/s | 持续 300 秒通过，约 150 HTTP RPS |
| mixed 225 场景/s | 持续 300 秒通过，约 337.5 总 HTTP RPS；应用 326.25、OSS PUT 11.25 |
| mixed 250 场景/s | 失败；2 次 transport `connection_reset` |
| 100 用户稳态 | 正式采样 P95 20—108 ms；IM 发送 P95 28—33 ms、送达 P95 23—28 ms |

## 与 main 的可比性

- Search 400 RPS 均通过；main 的 P95 约 18—20 ms，低于 legacy 的 32.9 ms。
- mixed 不能直接按场景/s 对齐：main 增加上传生命周期、交易版本检查、接收方 WebSocket hint 后 HTTP 回读等操作，单位场景的 HTTP 和外部 I/O 组成不同。
- legacy 的 225 场景/s 是高吞吐参考，不是 main 必须达到的无条件 SLA；main 在 200 场景/s 的失败证据用于定位当前发布/上传与共享后端边界。
