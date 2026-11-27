<!--
Version: 0.1.1
Version-Datetime: 2026-11-27T15:15:00+08:00
-->

# 种子数据与真实接口压测使用说明

本文只覆盖隔离开发/测试环境。`maintenance.jar seed load` 和 `seed demo` 会写入真实 PostgreSQL 和真实 OSS；Rust 驱动只通过真实 HTTP/WebSocket 访问服务，不需要数据库、Redis 或 OSS 凭据。实际性能执行见[TC-PERF-001 性能与容量测试报告](../design/test-cases/reports/performance-capacity/测试报告.md)。

## 1. 隔离环境

演示命令直接使用现有的 `backend/.env.dev`，包括其中的 `OSS_PREFIX`。压测另建 `backend/.env.load`，为本轮设置单独的 PostgreSQL 库、Redis 命名空间和 OSS 前缀。API、调度器、worker 和维护命令使用同一份对应配置。共享桶上的两个前缀应互不包含，例如 `project1/dev` 与 `project1/load/run-01`。

```bash
cp -n backend/.env.dev.example backend/.env.load
# 填入压测目标及凭据，示例
# DATABASE_URL=jdbc:postgresql://127.0.0.1:5432/project1_load_test
# REDIS_NAMESPACE=project1:load:run-01
# OSS_PREFIX=project1/load/run-01
# ALLOWED_ORIGINS=http://127.0.0.1:8080
```

OSS Bucket 须为私有且未开启过版本控制。环境配置含凭据，保存在 Git 忽略范围内。

## 2. 构建

```bash
mvn -f backend/pom.xml install
```

维护工具位于 `backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar`。以下命令从仓库根目录执行。

## 3. 清理顺序与范围

`seed` 不会自行删除数据库、Redis 或共享桶。执行前必须停止 API、调度器和全部 worker，然后按以下顺序清理。示例使用演示配置。准备压测时，把下列环境文件统一换成 `backend/.env.load`。

```bash
# 1) 预览数据库 + Redis 命名空间
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  db reset --env-file="$PWD/backend/.env.dev"
# 核对目标后确认
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  db reset --env-file="$PWD/backend/.env.dev" --confirm "<db 预览令牌>"

# 2) 预览并确认只清理当前部署前缀（推荐；共享桶必须这样做）
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  oss reset --env-file="$PWD/backend/.env.dev" --prefix "$(grep '^OSS_PREFIX=' backend/.env.dev | cut -d= -f2-)"
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  oss reset --env-file="$PWD/backend/.env.dev" --prefix "<同一 OSS_PREFIX>" --confirm "<oss 预览令牌>"
```

- `db reset` 的目标是配置中的专用数据库；成功后重建 Flyway schema，并清空 `REDIS_NAMESPACE:*`。
- `oss reset --prefix` 只列出并删除 `PREFIX/` 下的对象；前缀必须非空且按 `/` 分段，空前缀、以 `/` 结尾或 `a//b` 都会被拒绝。预览令牌覆盖具体前缀，不能跨范围复用。
- 不带 `--prefix` 的 `oss reset` 仍保留原有整桶行为，**仅限该桶专用于当前部署**时使用；共享联调桶禁止使用。
- `seed` 自身还要求 `--prepare-reset`，并在写库前检查配置数据库没有 account/product/file/trade/conversation/case 行、OSS_PREFIX 下没有对象。检查失败会直接退出，不会清理任何东西。
- 失败后的恢复：保持写入停止，重新预览并执行完整清理，再重新 seed。OSS 已上传但数据库未提交的对象只在前缀范围内，按上面的前缀 reset 回收。

## 4. seed load

默认 100 个用户、10,000 个商品；用户、商品、seed 和 tag 是确定性规模参数。服务端会生成：

- 1 个 manager 和 N 个普通账号，共用本次 manifest 中的密码；
- 可搜索、可按分类筛选的公开商品，每个商品有已验证 OSS 图片和 `file_record`/`file_reference`；
- 独立的浏览商品池和交易商品池（两池不相交）；
- 每个用户一条私聊会话，以及与下一用户配对的交易对；
- 通过审核的 `product_audit`/`moderation_case` 行，保证列表/详情读取不依赖未完成审核。

```bash
# 基线
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  seed load --env-file="$PWD/backend/.env.load" --prepare-reset \
  --manifest="$PWD/var/load/manifest.json"

# 小规模 smoke（用于先验证环境）
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  seed load --env-file="$PWD/backend/.env.load" --prepare-reset \
  --users 3 --products 300 --tag smoke \
  --manifest="$PWD/var/load/manifest-smoke.json"
```

`--seed N` 控制内容生成的确定性；相同 N、tag、规模在空库上生成相同的顺序/分布，但数据库身份 ID 仍由空库中的插入顺序决定。manifest 默认写到 `var/<mode>/manifest-<run_id>.json`，文件权限为 `0600`。

## 5. seed demo

Demo 使用固定的 9 个用户 + 1 个 manager、24 个商品、3 条私聊、7 笔交易（已完成、进行中、冻结、未约定、待确认）、1 个带附件的商品举报事项和 1 个已处置的评论举报事项。充电宝举报包含 legacy 实物照片和本次根据私聊数据重绘的 PNG 附件。PNG 沿用当前界面的对话气泡样式并标注演示数据。运行主机需安装可显示中文的字体。商品图片来自 `backend/maintenance/src/main/resources/seed-assets/`，会真实上传到当前 `OSS_PREFIX/product_image/`；举报证据上传到 `OSS_PREFIX/case_evidence/`。案件会话、商品评论、收藏、交易会话和 `case_evidence` 都是当前数据库/API 可读取的真实记录，因此现有用户端和管理端会按当前 UI 渲染，不需要额外 mock。

```bash
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  seed demo --env-file="$PWD/backend/.env.dev" --prepare-reset \
  --manifest="$PWD/var/demo/manifest.json"
```

Demo 的账号邮箱、显示名、manager、全部实际 ID 和各场景键都在 manifest 的 `manager`/`accounts`/`scenarios` 中；密码只在 manifest 的 `password` 字段。不要在终端、Issue 或日志中打印 manifest 内容。

演示时按 manifest 的别名找账号、按场景键找对应记录。

| 业务线 | 账号 | 从哪里开始 |
|---|---|---|
| 商品发布与审核 | `seller`、`manager` | 查看 `product_lamp_pending`，切换管理端，在审核待办打开 `case_review_lamp_pending`。 |
| 私聊与交易 | `buyer`、`seller` | 打开 `chat_seller_buyer`，再查看已完成交易与进行中的交易，分别展示历史和待确认动作。 |
| 交易异常 | `buyer3`、`manager` | 打开 `trade_trade_stand_frozen`，查看冻结原因和对应治理事项。 |
| 商品举报与申辩 | `outsider`、`manager`、`seller2` | 打开 `report_powerbank`，查看核查依据和证据附件。用 `seller2` 打开同一事项，通过 `powerbank_seller_appeal` 对应的线程提交申辩。 |
| 评论举报处置 | `buyer2`、`manager` | 打开 `report_kindle_comment`，查看评论目标、询问与作者说明；`buyer2` 的评论已按同一事项的处置记录移除，`case_kindle_comment` 和 `conversation_kindle_comment` 可直接定位事项与线程。 |

## 6. manifest v3

Manifest 是私有文件（0600），先写入 `complete:false`，在数据库计数、商品图片引用、文件元数据和 OSS 抽样校验通过后才原子替换为 `complete:true`。主要字段：

| 字段 | 含义 |
|---|---|
| `version` / `format_version` | 当前为 3 |
| `mode` / `run_id` / `tag` | 模式、run-bound 标识、标签 |
| `password` | 本次全部 seed 账号的登录密码 |
| `manager` / `accounts` | 账号别名、实际账号 ID（字符串）、邮箱、显示名、角色 |
| `product_ids` / `browse_product_ids` | 全部商品与浏览池 |
| `trade_pairs` | `{user, peer, product_id, product_version}`，user/peer 为实际账号 ID |
| `category_ids` / `conversation_ids` / `search_terms` | 分类、私聊、搜索分布 |
| `image_base64` / `image_sha256` / `image_assets` | Rust 上传测试用图片及摘要 |
| `scenarios` | demo 的产品/交易/案件/会话场景键与实际 ID |
| `target` | 非敏感目标描述（数据库、桶、前缀、Redis 命名空间） |

不要把 manifest 复制到仓库、聊天或公共日志。每次运行使用新 `run_id`；旧 manifest 不能复用为“complete”证据。

## 7. Rust 驱动

```bash
cargo build --release --locked --manifest-path loadtest/Cargo.toml
./loadtest/target/release/campus-loadtest \
  --base-url http://127.0.0.1:8080 \
  --manifest var/load/manifest.json \
  --users 100 --warmup-seconds 30 --duration-seconds 120 \
  --think-ms 1000 --min-samples 20 \
  --output var/load/report.json
```

小规模 smoke：

```bash
./loadtest/target/release/campus-loadtest \
  --base-url http://127.0.0.1:8080 \
  --manifest var/load/manifest-smoke.json \
  --users 3 --warmup-seconds 5 --duration-seconds 60 \
  --think-ms 200 --min-samples 3 \
  --output var/load/report-smoke.json
```

驱动使用当前契约：先取 `GET /api/v1/account/entry-context`，用 entry CSRF 调 `POST /api/v1/account/session`，随后每个用户使用自己的 `__Host-se_session` Cookie 和 `__Host-se_csrf`；所有非安全请求带 `Origin` 和 `X-CSRF-Token`。实时连接直接连 `/api/v1/realtime`，首帧为 `hello {protocol_version:1, csrf_token, cursor}`，处理 `hello_ok`、`sync_reset`/`resume`、`event`、`cursor_advance`、`ping`/`pong`，并按 `through_seq` ACK。IM 在收到 hint 后用接收方 Cookie 调消息接口取实际消息，再完成 `im_delivery`/`im_retrieval` 匹配。上传走当前 POST policy 表单，发布/交易/会话使用当前路径、字段和字符串 ID。

容量与竞态：

```bash
./loadtest/target/release/campus-loadtest --mode capacity --capacity-case mixed \
  --base-url http://127.0.0.1:8080 --manifest var/load/manifest.json --capacity-start-rate 25 --capacity-max-rate 400 \
  --capacity-stage-seconds 30 --capacity-warmup-seconds 5 \
  --capacity-validation-seconds 60 --capacity-max-arrivals 100000 \
  --capacity-max-samples 300000 --output var/load/capacity.json

./loadtest/target/release/campus-loadtest --mode race --race-rounds 5 \
  --base-url http://127.0.0.1:8080 --manifest var/load/manifest.json --users 100 --output var/load/race.json
```

同机多用户需要核对服务端与反向代理的 WebSocket 连接限制和握手超时；Origin 必须精确匹配 `ALLOWED_ORIGINS`，不要在非隔离环境放宽来源校验。

## 8. 最终清理与证据保留

停掉该环境的 API、调度器、worker 和压测进程。按第 3 节对本轮数据库、Redis 命名空间和 OSS 前缀分别执行预览和确认，再验证前缀为空。删除本次 manifest、含逐请求样本的大型原始报告、容量阶段临时文件和云凭据；将脱敏后的聚合报告、环境、命令、RUN 日志和边界结论复制到 `docs/design/test-cases/reports/performance-capacity/evidence/`。不得用本地 `var/` 路径作为正式报告的唯一证据。需要恢复演示时，用演示环境配置重新执行 `seed demo`。

## 9. 覆盖边界

- 压测是 API + 真实 WebSocket 驱动的闭环模型，不包含浏览器渲染、首屏/水合、图片实际解码、WAN 延迟仿真、SMTP 和外部支付/物流。
- 100 用户/10,000 商品的结论只在本次 manifest 确实达到该规模时成立；小规模 smoke 通过不代表容量结论。
- capacity 给出的是本次到达速率下的验证下界/边界，不宣称服务端绝对上限；race 是冲突语义检查，不作为稳态 P95 结论。
- seed 的真实 OSS 上传和真实数据库写入需要已配置的隔离资源；本地构建/单测不访问真实桶。没有真实 OSS/数据库/SMTP 的检查只能证明编译和静态/单元契约。
- seed demo 只覆盖目录中的代表性业务分支，不替代全量验收场景；未实现的通知/审阅待办深度以 manifest 的 `scenarios` 为准。
