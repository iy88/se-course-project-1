<!--
Version: 0.2.2
Version-Datetime: 2026-11-27T16:07:00+08:00
-->

# Rust 真实接口压测

独立 HTTP/WebSocket 性能测试驱动，用于验证 100 名活跃用户、10,000 条商品下的操作延迟和消息送达性能。`maintenance.jar seed load` 批量准备压测数据和资源，Rust 只读取私有 manifest，通过真实 Session Cookie 登录、业务 HTTP 和接收方 WebSocket 操作。服务器使用同一份后端代码和它自己的环境配置，**驱动不需要数据库、Redis、OSS AK 或 JWT 签发密钥**，也不需要读取任何 `.env` 文件；它只依赖目标后端、Redis/数据库已由服务端启动，以及 OSS 上传表单可访问。

运行前准备开发/测试数据库、Redis 前缀、OSS 范围和压测清单。工具读取清单，通过真实 HTTP/WebSocket 业务流程执行测量，并将结果写入指定报告。需要 Rust 1.95+；使用 `cargo build --release --locked` 构建，`Cargo.lock` 固定本次依赖。Linux 服务器请在目标平台构建对应平台的二进制。

从本目录执行：

```bash
cargo build --release --locked
./target/release/campus-loadtest \
  --base-url http://127.0.0.1:8080 \
  --manifest ../var/load/manifest.json \
  --users 100 --warmup-seconds 30 --duration-seconds 120 \
  --think-ms 1000 --min-samples 20 \
  --output ../var/load/report.json
```

从其他工作目录执行时，显式传入 manifest/output 路径。`--base-url` 只接受源站 origin，不带 `/api/v1`；工具自动使用 `/api/v1` 和 `/api/v1/realtime`，可经过反向代理访问。日志不输出账号密码、Cookie、CSRF、响应正文或 OSS 签名 URL。manifest 含测试账号密码，应保持私有、不提交、不公开分享；原始报告位于被 Git 忽略的 `var/load/`。

退出码：`0` 表示本次配置下所有指标通过，`1` 表示错误、断连、样本不足或超阈值，`2` 表示配置/登录/握手/上传准备失败。小规模试跑通过只说明该规模通过；JSON 中的规模达标结果还要求至少 100 用户与 10,000 个预置商品，代表 API/WS 层，不等于浏览器渲染与页面文字显示验收。

运行 `cargo test --locked` 验证协议帧、Cookie/CSRF 提取、manifest v3、ID 解析、消息匹配、百分位与失败判定，`cargo clippy --locked --all-targets -- -D warnings` 检查 Rust 代码。压测工具无自动业务请求重试、无清库、无服务启停或生产部署行为；交易完成状态使用有限次 GET 轮询确认，WebSocket 断线重连属于传输恢复而不是业务重试。

## Manifest v3

当前清单为 `version: 3`。以下摘录展示字段结构，运行时使用维护工具生成的完整清单。

```json
{
  "version": 3,
  "complete": true,
  "mode": "load",
  "run_id": "load-20261127",
  "tag": "dev",
  "password": "seed-password",
  "users": 100,
  "products": 10000,
  "accounts": [{"id": "101", "email": "load-101@example.test"}],
  "product_ids": [1001, 1002],
  "browse_product_ids": [1001],
  "trade_pairs": [
    {"user": "101", "peer": "102", "product_id": 1002, "product_version": 1}
  ],
  "category_ids": [1, 2, 3, 4, 5],
  "conversation_ids": [9001],
  "search_terms": ["校园", "book"],
  "image_base64": "...",
  "image_sha256": "...",
  "image_assets": [{"base64": "...", "sha256": "...", "size_bytes": 1234}],
  "scenarios": []
}
```

- `accounts[].id` 可以是 JSON 字符串或数字；商品、会话、分类和交易对字段使用数字。
- v3 的浏览池 `browse_product_ids` 必须是 `product_ids` 的非空子集；交易对引用的商品必须属于 `product_ids`，且不能出现在浏览池中。这样详情浏览不会因交易完成下架而误报。
- `conversation_ids` 按用户顺序覆盖完整种子 cohort；当前模型仍是购买者与 `(user+1) % users` 的环形会话。
- `trade_pairs.user/peer` 优先按账号 ID 匹配，也兼容用户下标；`product_version` 是种子商品的 `content_version`（通常为 1）。重上架不改变内容版本。
- v1/v2 仍可解析：缺少 v3 字段时回退到旧环形交易分配和完整商品池；新压测应使用 v3。

启动校验：`complete=true`、版本 1–3、`users == accounts.len()`、`products == product_ids.len()`、`users` 与清单完整 cohort 一致、`conversation_ids.len() == users`、至少 1 个分类、每个请求用户都有交易 fixture（steady/mixed）、manifest 是 0600 普通文件、基础图片与 `image_assets` 的 SHA-256/大小一致、交易池与浏览池不重叠、v3 浏览池非空。分类数不再强制为 5。

## 认证、Cookie 与 CSRF

每个虚拟用户独立执行：

1. `GET /api/v1/account/entry-context`，从 `Set-Cookie` 读取 `__Host-se_entry`，从响应体读取 `csrf_token`（也兼容 `csrfToken`）。
2. `POST /api/v1/account/session`，body `{email,password}`，带精确 `Origin`（来自 `--base-url`）、`X-CSRF-Token: <entry csrf>` 和 `Cookie: __Host-se_entry=...`。
3. 从响应 `Set-Cookie` 捕获 `__Host-se_session` 与 `__Host-se_csrf`，并校验 `account.account_id`（兼容 `accountId`）等于 manifest 账号 ID。

之后所有请求都带 `Cookie: __Host-se_session=...`。所有非安全方法（POST/PUT/PATCH/DELETE）还带精确 `Origin` 和会话 `X-CSRF-Token`。以下写请求带 `Idempotency-Key`：商品创建、文件上传授权与完成、交易创建/接受/约定/决定/完成确认、会话发送与已读进度。驱动不保存或打印凭据。

## 实时协议 v1

1. `GET /api/v1/account/events/head`（会话 Cookie）读取 `{epoch,head_seq,replay_floor}`。
2. 连接 `ws(s)://<ws-origin>/api/v1/realtime`，请求头带 `Origin`（仍为 API origin）和会话 `Cookie`。
3. 首帧：

```json
{"type":"hello","protocol_version":1,"csrf_token":"...","cursor":{"epoch":"...","after_seq":123}}
```

直连独立角色时可传 `--base-url http://127.0.0.1:8080 --ws-base-url http://127.0.0.1:8002`：登录和 events head 仍走 API origin，WebSocket 直连指定 WS origin，`Origin` 仍为 API origin；经过同一 Nginx origin 时不需要此参数。

4. 服务端帧：
   - `hello_ok {epoch,head_seq,replay_floor,...}`：只记录 epoch/恢复边界，**不 ACK head_seq**。
   - `ping {nonce}`：立即回 `{"type":"pong","nonce":"..."}`；应用层心跳是文本帧。
   - `event {epoch,event_id,account_seq,event_type,schema_version,occurred_at,data:{...}}`：连续 `account_seq` 去重后回 `{"type":"ack","epoch":...,"through_seq":account_seq}`。
   - `cursor_advance {epoch,from_seq,through_seq}`：推进本连接游标并 ACK `through_seq`。
   - `sync_reset {epoch,head_seq,replay_floor}`：切换 epoch/head，回 `{"type":"resume","epoch":...,"after_seq":head_seq}`；压测驱动不需要 UI 快照重载。
5. 传输中断、`4400`、`4409`、`4503` 使用 250ms 起、最大 5s 的指数退避重连，保留同一 epoch 的已确认游标并复用现有 Cookie/CSRF；重连前重新读取 head，epoch 变化或低于 replay floor 时从服务端当前 head 恢复。`4401`/`4403` 是认证/权限终止，记录失败并停止该用户的实时任务。
6. 计划内关停发送 Close 并正常退出，不计为 `ws_disconnect`；非计划断线和重连失败分别计入报告并导致本轮失败。

同机 100 用户时仍需按目标环境确认 `IM_HELLO_TIMEOUT_SECONDS`、`IM_IDLE_SECONDS`、`IM_ACCOUNT_CONNECTION_LIMIT`/`IM_SESSION_CONNECTION_LIMIT` 和反向代理连接限制，并让目标环境把驱动 Origin 加入允许来源。生产环境不得放宽来源。

## 消息送达测量

发送方 `POST /api/v1/conversations/chat/{conversationId}/messages`，带 `Idempotency-Key` 和 body `{"body":"..."}`；响应给出 `seq` 与 `message_id`。发送前登记待匹配内容，接收方 WebSocket 收到消息 hint 后：

1. 读取 `data.conversation_kind`、`conversation_id`、`message_id`、`message_seq`。
2. 用接收方 Cookie 执行 `GET /api/v1/conversations/{kind}/{id}/messages?after_seq=<seq-1>&limit=20`。
3. 只有返回项的 `message_id`、`seq` 与 hint 一致，且 `body` 等于发送内容时才完成待匹配送达。

WebSocket hint 可能先于发送 POST 的 HTTP 响应到达。此时驱动保存 hint 的真实到达时刻与 `message_id`／`message_seq`，不提前完成样本；发送响应返回后再与响应中的 `message_id`／`seq` 核对。ID 或序号不一致记为送达失败，body 仍须通过接收方 HTTP 回读精确匹配。

报告分别给出：

- `im_send`：发送 POST 的 HTTP 延迟。
- `im_delivery`：发送 POST 开始 → 接收方正文通过 HTTP 回读并完成校验。
- `im_retrieval`：接收方收到 hint → GET 回读验证完成，单独延迟。

hint 早于发送响应时，驱动在正文回读完成时冻结端到端耗时；等待发送响应的额外时间不计入该已完成样本。验证后会追加一次已读进度 `POST /api/v1/conversations/chat/{id}/read-progress`（`displayed_seq`），并以观察项 `im_read` 单独记录；其延迟、样本量和错误仍保留在操作指标中，错误会影响总判定。未匹配的消息不会自动重试，超时即失败。

## 当前 HTTP 契约

- 列表/搜索：`GET /api/v1/products?keyword=...&category_ids=...&page=&page_size=20`；首页为 `GET /api/v1/products?page_size=20`。
- 详情：`GET /api/v1/products/{id}`。响应 `id` 是十进制字符串，图片字段是 `images` 数组（对象含 `file_id/url`），搜索项字段是 `thumbnail`。
- 上传授权：`POST /api/v1/files/uploads`，body `{"purpose":"product_image","declared_size":N,"declared_content_type":"image/jpeg"}`（SNAKE_CASE 契约），带 `Idempotency-Key`。响应 `file_id`、`upload:{method:"POST",url,fields}`。
- OSS 上传：独立 `multipart/form-data` POST，发送全部签名字段，二进制字段名 `file`，`Content-Type: image/jpeg`；不携带应用 Cookie、Origin、CSRF 或 Authorization。
- 上传完成：`POST /api/v1/files/{fileId}/completion`，body `{}`，带 `Idempotency-Key`。
- 发布：`POST /api/v1/products`，body `{title,description,price_cents,image_file_ids:[...],category_ids:[...]}`（SNAKE_CASE 契约），带 `Idempotency-Key`；响应 `id` 字符串和 `lifecycle_state == "pending_review"`。
- 交易：`POST /api/v1/products/{productId}/purchase-requests` body `{note,expected_product_version}`；`POST /api/v1/trades/{tradeId}/accept` body `{expected_version}`；GET trade 取新鲜 `id`/`version`；`POST /api/v1/trades/{id}/agreements` body `{delivery_at,delivery_place_text,delivery_method,amount_cents,payment_method,payment_timing,expected_version}`；`POST .../agreements/{aid}/decisions` body `{decision:"accept",expected_version}`；`POST .../completion-confirmations` body `{note,expected_version}`；GET trade 直到 `status=="completed"`；最后 `POST /api/v1/products/{pid}/on-shelf` body `{expected_version}` 重新上架。每个写请求前都重新 GET 交易版本，写请求均带 `Idempotency-Key`。
- 会话发送/已读：`POST /api/v1/conversations/chat/{id}/messages` body `{"body":"..."}`，`POST .../read-progress` body `{"displayed_seq":N}`，均带 `Idempotency-Key`。

## 请求强度与容量探测

`--mode capacity` 使用固定到达速率，与 steady 的“请求结束后再等待”模型分开。两个 case 分别执行：

```bash
# 单接口：搜索，目标单位 HTTP RPS
./target/release/campus-loadtest --mode capacity --capacity-case single \
  --single-operation search --base-url http://127.0.0.1:8080 --manifest ../var/load/manifest.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --output ../var/load/capacity-single.json

# 混合业务：目标单位场景启动次数/秒，另报实际 HTTP RPS
./target/release/campus-loadtest --mode capacity --capacity-case mixed \
  --base-url http://127.0.0.1:8080 --manifest ../var/load/manifest.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --output ../var/load/capacity-mixed.json
```

默认从配置上限的一半开始（向上取整，`--capacity-start-rate` 可显式覆盖），每档 5 秒预热 + 30 秒采样；通过后翻倍升压。首次业务指标失败后采用整数二分：取通过/失败边界之间的整数中点，直到相邻整数（默认 resolution=1）或达到细测预算（默认 12 次），再对候选强度持续验证 300 秒。最高强度仍通过时只给已验证下界，不宣称测到了系统上限。在途上限、调度丢弃、数据池耗尽、WebSocket 断连和样本不足均为不确定结果，不当作服务端容量边界。

单接口支持 home/search/detail/publish/im。单接口发布在准备阶段为每个用户上传一次图片并复用其 `file_id`，采样时只发 `POST /products`；混合发布执行完整上传、完成、发布流程。混合交易使用 manifest 交易池，按购买者轮转租借；失败的交易 fixture 隔离，不静默复用。single IM 的必需项为 `im_send`、`im_delivery`、`im_retrieval`。

报告包含目标/实际发送/窗口内完成速率、排空时间、延迟/错误、调度延迟、跳过和在途上限次数、积压曲线。每档完整样本另存到输出旁的独立 `*-stages-*` 目录，汇总报告引用其路径。`--monitor-pid <本机后端PID>` 可加入本机后端 CPU/RSS 采样；发压进程默认采样。数据库只读监控见开发文档。

保护与判定：默认最多 2048 个在途场景；SLA/错误预算明确失败时停止新增任务，按实际采样时长计算速率，并保留 drain 样本。单接口同时报告“预定到达→完成”的 P95，混合业务完整流程延迟另列。达到配置最高强度并不等于已测得上限；未完成 300 秒持续验证的候选不会作为长期通过档位。容量阶段会把 WebSocket 断连/重连失败记为不确定结果，而不是服务容量。

## 稳态、竞态与报告

稳态默认 20 槽循环，按用户下标错开：6 首页、5 搜索、5 详情、1 发布、1 完整交易、2 IM；每个场景结束后 sleep `--think-ms`。请求/送达样本按操作开始时间归入 warmup、measured 或 drain；最终在途请求排空。`format_version: 2` 保留现有报告字段，并新增 `websocket_reconnect_failures`；必需操作包含 `home/search/detail/publish`、交易各步骤、`im_send/im_delivery/im_retrieval`。无自动业务重试；HTTP 错误、IM 匹配失败、断连、样本不足或 P95 超限都会使通过结果为 false。

竞态属于同一工具：`--mode race --race-rounds 5` 使用同一 manifest 与真实服务，覆盖同幂等键重复请求、抢单、并发完成、请求与接受竞争、重复上传确认、并发发布及事务回滚。预期业务冲突（409）与未预期错误分别判定；它输出独立报告，不作为稳态 P95 结论。每轮使用一个独立交易对，因此 race 轮数不能超过 manifest 交易对数量；请求-接受竞争轮会留下一个进行中的交易和占用商品，需重新 seed 才能复用。

## 覆盖边界

- 覆盖真实 Session/CSRF、HTTP API、OSS 签名上传和接收方 WebSocket；不覆盖浏览器渲染、页面文字、WAN 模拟、SMTP、支付/交付和数据库/Redis 内部指标。
- 驱动不需要 DB/Redis/OSS AK，但目标环境必须已启动对应依赖；OSS 不可达会使发布场景失败，而不是被重试隐藏。
- 单 worker 容量数据不能直接外推多 worker；历史 100 用户/400 混合场景数据也不代表 split 后的容量。
- v1/v2 清单只保证解析和旧环形交易回退；当前 seed/验收应使用 v3。
- Session 过期或服务端返回 4401/4403 时驱动不会重新登录，会记录失败并停止该用户实时任务；长稳压测应保证会话有效期覆盖整轮。
- 交易完成后商品自动下架，驱动用 manifest `product_version` 重新上架；被编辑过 `content_version` 的商品不能直接复用该固定版本。
- 发布和交易会累积数据；驱动不清库，重复使用同一 seed 前应重新准备。
