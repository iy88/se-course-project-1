<!--
Version: 0.1.0
Version-Datetime: 2026-11-06T19:32:01+08:00
-->

# Rust 真实接口压测

独立 HTTP/WebSocket 驱动，面向 [issue #34](https://github.com/iy88/se-course-project-1/issues/34)。Python 后端负责批量准备真实数据与资源，Rust 只读取私有 manifest，通过真实登录、业务 HTTP 和接收方 WebSocket 操作。服务器使用同一份代码和自己的 `backend/.env.dev`，不需要 Rust 访问数据库、Redis、OSS AK 或 JWT 签发密钥。

完整的资源清空、播种、服务启动、负载口径与本地证据见[压测运行说明](../docs/development/load-testing.md)。需要 Rust 1.95+（本轮已验证版本）；使用 `cargo build --release --locked` 构建，`Cargo.lock` 固定本次依赖。Linux 服务器请在目标平台构建，不直接复制 macOS 二进制。

从本目录执行：

```bash
cargo build --release --locked
./target/release/campus-loadtest \
  --base-url http://127.0.0.1:8000 \
  --manifest ../var/load/manifest.json \
  --users 100 --warmup-seconds 30 --duration-seconds 120 \
  --think-ms 1000 --min-samples 20 \
  --output ../var/load/report.json
```

从其他工作目录执行时，显式传入 manifest/output 路径。`--base-url` 只接受源站 origin，不带 `/api/v1`；工具自动使用 `/api/v1` 与 `/ws`，可经过反向代理访问。日志不输出账号密码、JWT、响应正文或 OSS 签名 URL。manifest 含测试账号密码，应保持私有、不提交、不上传到 issue；原始报告位于被 Git 忽略的 `var/load/`。

退出码：`0` 表示本次配置下所有指标通过，`1` 表示错误、断连、样本不足或超阈值，`2` 表示配置/登录/握手等准备失败。小规模试跑通过只说明该规模通过；JSON 中的 `issue_34_api_ws_passed` 还要求至少 100 用户与 10,000 个预置商品。该字段代表 API/WS 层，不等于浏览器渲染与页面文字显示验收。

运行 `cargo test --locked` 验证百分位算法、缺项/样本不足/错误/延迟超限的失败判定，`cargo clippy --locked --all-targets -- -D warnings` 检查 Rust 代码。压测工具无自动重试、清库、服务启停或生产部署行为。

竞态属于同一工具：`--mode race --race-rounds 5` 使用同一manifest与真实服务，覆盖抢单、重复请求、并发完成、请求与接受竞争、重复上传确认、并发发布及事务回滚。预期业务冲突与非预期错误分别判定；它输出独立报告，不作为稳态P95结论。`main.rs`只保留参数入口，具体职责分散到config/model/http/scenarios/ws/races/diagnostics/report/runner。

默认HTTP总超时60秒，显式禁用自动重试；报告v2保留脱敏错误分类、请求关联ID与起始偏移。预热请求错误会使整轮passed为false，同时单独给出steady_state_passed。seed v2支持8种图片与不同关键词，Rust兼容历史v1清单；v1数据需重新seed才能得到新分布。


## 请求强度与容量探测

`--mode capacity` 使用固定到达速率，与steady的“请求结束后再等待”模型分开。两个case分别执行：

```bash
# 单接口：搜索，目标单位HTTP RPS
./target/release/campus-loadtest --mode capacity --capacity-case single \
  --single-operation search --manifest ../var/load/manifest.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --output ../var/load/capacity-single.json

# 混合业务：目标单位场景启动次数/秒，另报实际HTTP RPS
./target/release/campus-loadtest --mode capacity --capacity-case mixed \
  --manifest ../var/load/manifest.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --output ../var/load/capacity-mixed.json
```

默认每档5秒预热+30秒采样；通过后翻倍升压，首次业务指标失败后在区间内最多细测3次，再对候选强度持续验证300秒。最高强度仍通过时只给已验证下界，不宣称测到了系统上限。在途上限、调度丢弃、数据池耗尽和样本不足均为不确定结果，不当作服务端容量边界。

单接口支持home/search/detail/publish/im。单接口发布复用该用户已播种的图片，只发一次POST /products，后端自身的OSS验证仍在接口耗时内；混合发布包含上传全流程，交易保持完整步骤依赖。mixed沿用30%首页、25%搜索、25%详情、5%发布、5%交易、10%IM；不使用think-ms节流，每项任务由预定时间发起。详情池与交易池分开，未完成/失败交易的商品不复用。

报告包含目标/实际发送/窗口内完成速率、排空时间、延迟/错误、调度延迟、跳过和在途上限次数、积压曲线。每档完整样本另存到输出旁的独立stages目录，汇总报告引用其路径。`--monitor-pid <本机后端PID>`可加入本机后端CPU/RSS采样；发压进程默认采样。数据库只读监控见开发文档。

保护与判定：默认最多2048个在途场景；SLA/错误预算明确失败时停止新增任务，按实际采样时长计算速率，并保留drain样本。单接口同时报告“预定到达→完成”的P95，混合业务完整流程延迟另列。达到配置最高强度并不等于已测得上限；未完成300秒持续验证的候选不会作为长期通过档位。
