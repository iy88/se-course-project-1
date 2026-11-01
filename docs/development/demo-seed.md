<!--
Version: 0.3.0
Version-Datetime: 2026-11-02T02:07:32+08:00
-->

# 演示数据与操作路线

本文说明持久 demo-seed 的共享场景目录、现场起点、验证方式和人工边界。当前目录包含 19 个身份、38 个商品、26 笔交易/请求、9 个举报、25 个目录事项、29 个会话、27 条通知、47 个图片/证据文件和 48 条场景；实际数量以 `demo-verify` 的只读结果为准。场景内容、对象 key 与断言由 `backend/app/devtools/demo_scenarios/` 维护（图片/证据素材副本位于该目录 `assets/`，运行期不导入 tests）：seed、只读核验与自动化回归读取同一份目录，不在测试或文档中复制第二套业务事实。完整资格与预期仍以 `docs/requirements` 01—08 及详细 US／UC／SC 材料为准。

## 准备、启动与验证

先确认 `backend/.env.dev` 指向预期的演示数据库与存储（PostgreSQL + OSS 或 SQLite + local），准备相应服务并执行迁移。演示 seed 只向所选目标追加数据，不删除、不接管已有业务数据，也不覆盖人工修改。

```bash
(cd backend && APP_ENV_FILE=.env.dev .venv/bin/python -m app.manage migrate)
(cd backend && .venv/bin/python -m app.manage demo-seed --env-file .env.dev)
(cd backend && .venv/bin/python -m app.manage demo-verify --env-file .env.dev)
./scripts/dev.sh start
```

服务读取同一环境文件；seed 与 verify 必须指向同一目标，否则 manifest 目标绑定检查会拒绝。默认 manifest 位于 `var/demo/manifest.json`，包含演示登录信息与对象 ID，按敏感文件保管（0600）；需要独立演示批次时用 `--manifest <路径>`。manifest 的 `accounts` 给出邮箱和密码，`objects`/`object_kinds` 给出对象 ID 与显式类型，`files` 给出已登记文件 key 与摘要；账户密码以 manifest 为准，不写入文档、日志或终端。

`demo-verify` 是只读入口：不写业务记录、不推进已读、不打印密码、签名 URL、连接串或文件内容。它校验 manifest 版本/目录摘要/目标、账号、对象显式类型、文件真实可读与 `stored_object` 登记、每个场景的对象覆盖、目录初始状态、跨实体不变量，以及公开搜索、受限商品匿名结果、私有交易和非认领管理员事项的只读权限（直接调用只读路由函数，不启动服务）。加 `--skip-api` 可只做数据库/存储检查；`--json` 输出不含秘密的摘要。只读核验针对 seed 初始状态；现场操作或人工修改后应使用另一条记录或重新准备，不能把已改变的状态当作初始核验通过。只读核验通过不代表自动化生命周期动作已执行，后者见隔离回归。 服务启动后会立即运行超时扫描，`trade_timeout` 会按真实规则转为异常并冻结；此后严格初始状态核验报告会提示该变化，demo-seed 重跑不会把它改回。请在首次启动服务前保存初始核验结果。

单独运行共享目录与持久 seed 回归（仅 SQLite/local 临时空间，不读写 `.env.dev` 的业务数据）：

```bash
(cd backend && .venv/bin/python -m pytest tests/test_demo_scenarios_catalog.py tests/test_demo_seed.py -q)
(cd backend && .venv/bin/python -m tests.acceptance_real.catalog --check)
```

真实验收仍使用 `python -m tests.acceptance_real.seed` 的一套隔离入口；它只准备一次性验收身份，不等同于本持久 demo-seed，也不替代本目录的夹具一致性回归。验收的执行结果以真实报告 PASS 为准。

## 开发环境清空后重新演示（不备份）

在仓库根目录执行。以下命令清空 `.env.dev` 的 PostgreSQL 应用表、Redis 配置前缀和两个配置 OSS 桶的当前对象；重置入口已执行迁移，无需重复 migrate。`--confirm` 必须匹配实际库名，下面为当前开发配置；OSS 有非空前缀时只清理该前缀。

```bash
set -e
./scripts/dev.sh stop
backend/.venv/bin/python -m app.devtools.reset --env-file .env.dev --execute --confirm campus_market_test --whole-buckets
rm -f var/demo/manifest.json
backend/.venv/bin/python -m app.manage demo-seed --env-file .env.dev
backend/.venv/bin/python -m app.manage demo-verify --env-file .env.dev
./scripts/dev.sh start
```

删除旧 manifest 是因为数据库和文件已清空；这里只删除默认清单，不保留备份。自定义 `--manifest` 时删除并在 seed/verify 中使用对应文件。账号从新清单读取。先核验再启动，避免真实超时扫描推进初始状态。

## manifest 版本与兼容策略

- 当前 manifest `version=2`，同时记录 `catalog_version` 与 `catalog_signature`、目标指纹、场景 key 列表、对象显式类型和文件摘要。旧 `version=1` 明确拒绝，不静默迁移或接管。
- `complete=true` 的 manifest 只有在目录摘要与目标都一致时才走“校验并返回”；目录新增/修改场景会使摘要变化并明确拒绝。请使用新的 manifest 文件重新 seed，不能靠旧 complete 清单跳过新增场景。
- 中断后使用同一 manifest 重跑：已登记文件先校验内容与摘要；已提交事务但最终清单写失败时，按显式对象类型逐项校验后补写完成标记；未提交时清理候选 ID，不接管数据库中的同名记录。
- seed 不删除数据；需要重置共享演示环境时由主代理另行重置数据库/Redis/OSS 并使用新 manifest，本命令不提供删除或覆盖选项。
- 文件先登记 key 再非覆盖上传；上传响应丢失时比较已存在内容，内容不一致即拒绝。manifest 文件权限 0600。

## 身份与入口

| 账号 key | 角色 | 用途 |
|---|---|---|
| `admin`、`admin2` | 管理员 | 审核、举报核查、交易异常与另一管理员权限检查 |
| `seller`、`seller2`、`seller3` | 普通用户 | 普通卖家，覆盖数码、家居、教材与标签维护 |
| `buyer`、`buyer2`、`buyer3`、`outsider` | 普通用户 | 搜索、收藏、评论、竞争请求、举报与越权检查 |
| `frozen_seller`、`frozen_buyer` | 普通用户 | 独立冻结交易，避免冻结账号影响普通路线 |
| `banned`、`ban_seller` | 普通用户 | 封禁与关联交易、解除限制及历史记录 |
| `multi_ban`、`multi_buyer` | 普通用户 | 封禁、商品展示限制与另一事项交易冻结叠加 |
| `timeout_seller`、`timeout_buyer` | 普通用户 | 单方确认超时，由真实扫描任务触发异常 |
| `abnormal_seller`、`abnormal_buyer` | 普通用户 | 已转异常的独立交易，供管理员调整/解冻 |

显示名使用虚构的“专业年级 + 姓名”风格。演示账号使用 `example.com` 地址；注册、找回密码和换邮箱需要真实可收件账号，seed 不预置邮件验证码。受限账户仍可读取本人通知与处置沟通；写操作、交易与相关 IM 按规则拒绝。

## 场景目录（48 条）

每条场景的 `objects` 是现场入口；`state:` 检查的是历史/当前记录，`live:` 检查的是可现场执行或只读打开的入口。互斥分支使用不同商品、交易、商品请求或举报对象，不能把某条终态记录当成可继续操作的起点。

| 场景 key | 中文标题 | 角色 | 起始状态 | 允许操作与预期 | 映射 |
|---|---|---|---|---|---|
| `product.pending_unclaimed` | 商品待审核且未被认领 | seller, admin | 护眼台灯处于待审核，审核事项在共享池等待认领，标签申请待处理。 | admin 认领审核事项；admin 通过或拒绝并填写原因。预期：认领后其他管理员不能重复处理；拒绝时保留原因并允许修改重提 | US-02, UC-C02, SC-02 |
| `product.pending_claimed_edit` | 已认领待审商品仍可编辑 | seller, admin, admin2 | 机械键盘待审核，审核事项已被 admin 认领；卖家已补充键帽与配件说明。 | admin2 尝试处理被 403 拒绝；admin 按最新内容通过并处理标签。预期：认领不阻止卖家编辑；审核结论依据结论时最新内容 | US-02, US-08, UC-C02, UC-C08, SC-02 |
| `product.rejected_resubmit` | 审核拒绝后修改重提 | seller2, admin | 胶片相机 9 天前被拒绝，原因要求补充镜头近照与快门测光说明。 | seller2 修改描述和图片后调用重提；形成新的 pending 审核记录与新事项。预期：旧拒绝记录保留；重提后商品重新待审核，旧事项不可再处理 | US-02, UC-C02, SC-02 |
| `product.withdrawn_resubmit` | 认领前撤回后可重提 | seller3, admin | 四层书架的审核事项在认领前被卖家撤回，商品已下架，审核记录 withdrawn。 | seller3 查看撤回记录；修改后重提，形成新 pending 记录。预期：撤回后旧审核入口失效；仅“撤回形成的已下架”可重提，普通下架走上架 | US-02, UC-C02, SC-02 |
| `product.review_history` | 重提后的审核历史与最新状态 | seller2, admin | 显示器先被拒绝，卖家补充亮机照片后重提，当前待审核。 | seller2 查看两条审核记录；admin 按最新内容审核。预期：历史结论不覆盖；最新 pending 记录对应新事项 | US-02, UC-C02, SC-02 |
| `product.tag_alias` | 标签申请映射为已有分类别名 | seller, admin | 教材商品审核通过时，“课本”申请映射到“教材书籍”的已有别名。 | seller 查看申请结果；buyer 用“课本”检索定位到教材。预期：别名不重复计标签；同一分类主名与别名指向同一标签 | US-13, UC-C13, SC-10 |
| `product.tag_new` | 标签申请批准为新分类 | seller3, admin | 折叠自行车的“骑行装备”申请在商品通过时批准为新分类。 | seller 查看结果；buyer 按新分类检索。预期：新分类与商品关联生效；重复申请应映射而不是重复建类 | US-13, UC-C13, SC-10 |
| `product.tag_rejected` | 标签申请被拒绝并说明原因 | seller, admin | 羽毛球拍的“球类”申请在商品通过时被拒绝。 | seller 查看拒绝原因；商品分类保持运动户外。预期：拒绝不影响商品通过；拒绝原因必须可见 | US-13, UC-C13, SC-10 |
| `product.edit_notify` | 编辑历史与买方通知 | seller, buyer2 | 收纳架价格从 30 元改为 25 元，存在待接受请求的买方。 | seller 查看编辑历史；buyer2 查看通知。预期：编辑不重建审核；编辑不关闭未结束请求 | US-02, US-11, UC-C02, UC-C11, SC-02, SC-11 |
| `product.market_search` | 搜索、详情、收藏与评论 | buyer, buyer2, seller | 山地车公开在售，买方已收藏并评论询问磕碰与交付时间。 | buyer 按关键词/分类别名/价格检索；打开详情查看评论与收藏。预期：非公开商品不出现在结果；收藏仅本人可见 | US-03, US-04, UC-C03, UC-C04, SC-03 |
| `product.comments` | 评论回复、删除与越权 | buyer3, seller2, buyer2 | Kindle 在售，含卖方回复与一条被管理员移除的评论。 | buyer3 新发评论；seller2 回复。预期：仅卖方或本人可删除/回复规则；逻辑删除保留历史 | US-04, UC-C04, SC-04 |
| `product.delisted_favorite` | 已下架商品与失效收藏 | seller, buyer | 电饭煲已下架 10 天，买方收藏仍在但不开放交易。 | buyer 查看收藏并尝试进入详情；seller 重新上架。预期：下架不删除收藏；重新上架后恢复公开资格需符合规则 | US-03, US-09, UC-C03, UC-C09, SC-03, SC-09 |
| `product.restricted_result` | 受限商品只返回匿名处置结果 | seller2, buyer, admin | 充电宝因鼓包被举报核查后停止公开，公开入口只返回匿名结果。 | buyer 从原入口读取匿名结果；seller2 查看本人受限状态并申辩。预期：详情不泄露受限正文；公开结果不显示举报人 | US-03, US-08, US-12, UC-C03, UC-C08, UC-C12, SC-07, SC-12 |
| `product.category_correction` | 管理员纠正商品分类并留痕 | seller3, admin | 投影仪原先关联生活家居，管理员按实际用途纠正为数码电子。 | seller3 查看前后分类；admin 再次维护分类。预期：纠正不改商品审核结论；历史前后内容保留 | US-13, UC-C13, SC-10 |
| `product.avatar_review` | 头像待审核 | outsider, admin | 用户上传的头像进入待审核事项，原头像继续可用。 | admin 认领并处理；outsider 继续使用原头像。预期：审核期间不阻断普通浏览 | US-01, US-08, UC-C01, UC-C08, SC-01 |
| `trade.compete_requests` | 两买方竞争请求与锁单关闭 | seller, buyer, buyer2 | 降噪耳机公开在售，两名买方各有一条待接受请求。 | seller 接受 buyer 的请求；另一条自动关闭并通知。预期：接受后不能继续接受另一条；锁单商品不可再请求 | US-05, US-11, UC-C05, UC-C11, SC-05, SC-11 |
| `trade.request_rejected` | 卖方拒绝请求 | seller, buyer | 榨汁机的一条请求已被卖方拒绝并说明原因。 | buyer 查看拒绝原因；branch 只读。预期：拒绝结束该请求；不改变商品公开状态 | US-05, UC-C05, SC-05 |
| `trade.request_withdrawn` | 买方撤回请求 | seller2, buyer3 | 蓝牙音箱的一条请求已被买方撤回。 | buyer3 查看历史；seller2 查看通知。预期：撤回结束请求；商品仍公开 | US-05, UC-C05, SC-05 |
| `trade.agreement_multiround` | 多轮约定拒绝后重新提案 | seller, buyer | 人体工学椅交易进行中，第 1 轮 330 元提案被卖方拒绝，第 2 轮 350 元待买方确认。 | buyer 拒绝第 2 轮；seller 再提第 3 轮。预期：拒绝只结束提案；确认新约定清当前确认与旧计时 | US-05, UC-C05, SC-05 |
| `trade.confirm_single` | 单方完成确认与等待 | seller, buyer2 | 微波炉交易已按第 2 轮约定 250 元完成交付，买方提交完成确认，卖方尚未确认。 | seller 提交本人确认；交易完成并下架商品。预期：每方一次当前确认；双方确认才完成 | US-06, UC-C06, SC-05 |
| `trade.completed_reviews` | 双方完成与双向评价 | seller, buyer | 球拍交易 5 天前完成，双方各提交一条评价。 | buyer 查看发表/收到评价；seller 查看评价。预期：仅完成后可评价；每方每笔一次 | US-06, US-07, US-12, UC-C06, UC-C07, UC-C12, SC-07, SC-12 |
| `trade.review_one_side` | 仅一方已评价 | seller, buyer3 | 相机交易已完成，买方已评价，卖方尚未评价。 | seller 提交评价；buyer3 查看收到评价。预期：评价按发表/收到分别读取 | US-07, UC-C07, SC-07 |
| `trade.dispute_open` | 争议处理中与单方解决确认 | seller, buyer2, admin | 保温杯交付后因杯口磕碰进入争议，管理员已认领并问询。 | buyer2 再次尝试确认解决显示已确认；seller 确认解决恢复。预期：争议保持锁单；双方确认才恢复 | US-06, US-08, UC-C06, UC-C08, SC-06 |
| `trade.dispute_recovered` | 争议恢复保留历史清当前确认 | seller3, buyer3, admin | 书架缺层板争议经补送后双方确认解决，交易恢复进行中。 | buyer3 重新提交完成确认；seller 再确认完成。预期：恢复本身不启动计时；旧确认保留为历史 | US-06, UC-C06, SC-06 |
| `trade.frozen_recovery` | 交易冻结、暂停计时与有依据解冻 | frozen_seller, frozen_buyer, admin | 显示器支架交易因底座裂纹争议被冻结，买方已确认，等待计时暂停。 | admin 解除冻结；剩余等待续算。预期：冻结期间不按自然时间累计；解冻保留当前确认 | US-08, US-14, UC-C08, UC-C14, SC-09 |
| `trade.cancel_direct` | 首约前买方直接取消 | seller3, buyer2 | 桌面风扇已接受请求但尚无有效约定，买方直接取消，交易终止。 | buyer2 查看取消记录；对照有约定的取消需同意。预期：首约前买方可直接取消；终止后商品默认下架 | US-05, UC-C05, SC-05 |
| `trade.cancel_agreed` | 约定后取消需双方同意 | seller2, buyer | 折叠桌已约定，卖方申请取消，买方同意后终止。 | buyer 查看终止原因；对照不同意取消与撤回申请。预期：约定后任一方不能单方取消 | US-05, UC-C05, SC-05 |
| `trade.cancel_pending` | 取消申请待对方同意 | seller, buyer3 | 煮蛋器已约定，卖方发起取消申请，买方尚未同意。 | buyer3 同意取消；交易终止并下架商品。预期：未同意不自动终止；终止后清取消申请字段 | US-05, UC-C05, SC-05 |
| `trade.cancel_refused` | 拒绝取消与撤回申请 | seller3, buyer | 空气炸锅已约定，卖方申请取消，买方明确不同意；申请仍待处理。 | seller3 撤回取消申请；交易继续。预期：不同意不改变交易状态；申请人可撤回 | US-05, UC-C05, SC-05 |
| `trade.timeout_scan` | 单方确认超时由扫描转异常 | timeout_seller, timeout_buyer, admin | 三脚架交易买方 8 天前提交确认，卖方未回应，尚未被扫描。 | 启动真实扫描任务；交易转 abnormal 并冻结。预期：扫描按阈值实际判断；不预置异常结果 | US-14, US-11, UC-C14, UC-C11, SC-09 |
| `trade.ban_side` | 封禁交易方与解除后恢复 | banned, ban_seller, admin | 马骁因账户封禁，其进行中交易被冻结，等待计时暂停。 | admin 解除封禁；交易解冻并续算等待。预期：封禁禁写保读；解冻须先解除封禁 | US-08, UC-C08, SC-07 |
| `trade.abnormal_admin` | 管理员调整异常交易并解冻 | abnormal_seller, abnormal_buyer, admin | 打印机交易因单方确认超时转异常并冻结，管理员已认领。 | admin 调整回进行中；确认历史保留、当前清空。预期：调整不伪造双方确认；恢复不启动计时 | US-14, US-08, UC-C14, UC-C08, SC-09 |
| `trade.admin_complete` | 管理员有依据调整完成 | seller2, buyer2, admin | 咖啡机争议经管理员核实双方已完成交付与付款，交易调整为完成。 | admin 查看调整依据；buyer2 查看完成状态与评价入口。预期：管理员可调整完成；不得伪造双方确认记录 | US-06, US-08, UC-C06, UC-C08, SC-06 |
| `trade.admin_terminate` | 管理员有依据终止交易 | seller3, buyer2, admin | 路由器交易双方协商不再交付，管理员已认领并核实。 | admin 查看终止依据；buyer2 查看终止状态。预期：管理员调整终止不记录为完成；历史约定与转移保留 | US-06, US-08, UC-C06, UC-C08, SC-06 |
| `trade.multi_restriction` | 封禁与其他限制叠加 | multi_ban, multi_buyer, admin | 严可因举报核查被封禁，商品停止展示；同时另一起争议冻结其交易。 | admin 解除封禁；商品展示恢复。预期：解除封禁不误清其他限制；封禁与交易冻结分别留据 | US-08, UC-C08, SC-07 |
| `report.product_pending` | 商品举报待核查且可补充 | outsider, seller2, admin | Kindle 被举报描述与图片不符，事项在共享池，举报人已补充证据。 | admin 认领并问询；举报人继续补充。预期：未结举报可在原事项补充；管理员认领唯一 | US-07, US-08, UC-C07, UC-C08, SC-07 |
| `report.product_processing` | 举报核查问询与说明 | buyer2, seller, admin | 收纳架交付时间举报已认领，管理员已问询，卖方已说明，等待结论。 | admin 形成不予处理或处置结论；举报人收到结论。预期：问询不改变状态；说明须由被问询人提交 | US-07, US-08, UC-C07, UC-C08, SC-07 |
| `report.product_handled_appeal` | 实际处置、匿名结果与多轮申辩 | buyer, seller2, admin | 充电宝举报已认定违规，商品停止公开，卖方已申辩，管理员回复维持。 | buyer 查看匿名结果；seller2 查看申辩与回复。预期：公开结果不泄露举报人；结案后不接受补充或重报 | US-07, US-08, US-12, UC-C07, UC-C08, UC-C12, SC-07, SC-12 |
| `report.comment_handled` | 评论举报实际处置与作者申辩 | buyer, buyer2, admin | Kindle 评论被移除，评论作者已申辩，管理员回复维持。 | buyer2 查看申辩记录；buyer 查看结果。预期：仅移除实际违规评论；结案后补充被拒 | US-07, US-08, UC-C07, UC-C08, SC-07 |
| `report.message_handled` | 消息举报核查与处置后解冻 | seller3, buyer2, admin | 交易分支消息引导站外转账被举报，管理员处置时冻结交易，核实后解冻。 | admin 查看消息处置记录；双方查看解冻通知。预期：消息处置不删除原始消息；解冻按依据 | US-07, US-08, UC-C07, UC-C08, SC-07 |
| `report.review_handled` | 评价举报、移除与作者申辩 | seller2, buyer3, admin | 含人身攻击的交易评价被移除，作者申辩后维持。 | buyer3 查看申辩结果；seller2 查看评价状态。预期：评价逻辑删除；维持结论不改历史 | US-07, US-08, UC-C07, UC-C08, SC-07 |
| `report.user_handled_appeal` | 用户举报封禁与申辩 | buyer2, multi_ban, admin | 严可因多次骚扰被封禁，已申辩，管理员维持封禁。 | multi_ban 查看申辩；admin 解除封禁查看其他限制。预期：封禁保读；申辩不自动撤销处置 | US-07, US-08, UC-C07, UC-C08, SC-07 |
| `report.unfounded_closed` | 举报不予处理后的只读与拒绝重报 | buyer3, seller, admin | 榨汁机举报经核查证据不足，不予处理，公开结果为空，举报人已收到结论原因。 | buyer3 再次举报同一对象被 409；补充说明被 409。预期：已结举报只读；不向被举报人通知 | US-07, US-08, UC-C07, UC-C08, SC-07 |
| `report.user_pending` | 用户举报待核查 | buyer2, outsider, admin | 用户举报评论区广告，事项尚未认领。 | admin 认领；按用户对象核查。预期：用户举报同样进入共享池 | US-07, UC-C07, SC-07 |
| `notification.reads_todos` | 通知已读、待办与聊天已读独立 | seller, buyer, buyer2, buyer3 | 卖家有多条未读通知与两个交易分支不同未读；普通私聊另有未读。 | seller 打开一条通知标读；进入会话不自动标读。预期：通知已读不办结业务；聊天已读独立 | US-11, US-12, UC-C11, UC-C12, SC-11, SC-12 |
| `stats.range` | 统计按显式时间范围 | admin | 在 40 天内有多笔完成交易，可分别按最近 7 天、30 天与全部统计。 | admin 不选范围查看状态数；admin 选择显式范围核对完成数。预期：不选范围不当作默认全部；范围按结果确认时间 | US-10, UC-C10, SC-08 |
| `category.maintenance` | 分类改名、别名、停用与删除 | admin, buyer | 数码电子有主名与别名；旧书交流已停用但仍被商品历史关联；待整理分类未被关联。 | admin 改名保留旧别名；停用已使用分类。预期：已关联分类只停用不删除；逻辑删除保留历史 | US-13, UC-C13, SC-10 |
| `account.profile_permissions` | 登录身份、只读封禁与管理员权限 | buyer, banned, admin, admin2, outsider | 普通用户、受限用户与两名管理员共存；封禁用户保留只读与处置沟通。 | banned 尝试发布商品被拒绝；banned 读取通知与处置沟通。预期：封禁禁写保读；管理员权限按认领事项 | US-01, US-08, US-12, UC-C01, UC-C08, UC-C12, SC-01, SC-12 |


## 现场操作顺序

建议按“查看公开面 → 认领与审核 → 请求与交易 → 争议/超时/冻结 → 举报与处置 → 通知/统计/分类”的顺序演示。会改变资格或结束记录的分支使用独立对象；现场改变后改用另一条适合的记录，不重置共享环境。

| 需求入口 | 建议现场起点 |
|---|---|
| US-01 / UC-C01 | `buyer` 登录、改显示名；`banned` 对照只读与管理沟通；`outsider` 头像待审 |
| US-02 / UC-C02 | `case_review_product_lamp` 认领/拒绝；`case_review_product_keyboard` 通过并处理标签；重提相机/显示器 |
| US-03 / UC-C03 | `product_bike` 关键词与分类别名搜索；`product_kindle` 评论；`product_rice_cooker` 失效收藏 |
| US-04 / UC-C04 | `conversation_normal` 与 `conversation_trade_compete_a` 分别标读；`product_kindle` 评论回复权限 |
| US-05 / UC-C05 | `trade_compete_a/b` 接受与关闭；`trade_progress` 多轮约定；`trade_cancel_pending/refused` 取消 |
| US-06 / UC-C06 | `trade_confirm` 单方到双方完成；`trade_recovered` 争议恢复；`trade_admin_complete/terminated` 调整留据 |
| US-07 / UC-C07 | `report_product_pending` 补充；`report_product_processing` 形成结论；`report_unfounded` 重报/补充拒绝 |
| US-08 / UC-C08 | 各事项认领；`report_product_handled`、`report_comment_handled`、`report_review_handled` 申辩与回复 |
| US-09 / UC-C09 | `product_rice_cooker` 下架/收藏；`product_powerbank` 受限入口；结束交易默认下架 |
| US-10 / UC-C10 | `stats.range` 最近 7/30 天与全部；不选范围不当作默认全部 |
| US-11 / UC-C11 | `notif_seller_compete_a` 标读；`conversation_normal` 会话标读；待办按事项派生 |
| US-12 / UC-C12 | `trade_completed` 评价；`report_unfounded` 我的举报；`product_powerbank` 收到举报展示 |
| US-13 / UC-C13 | `product_textbook` 别名；`product_folding_bike` 新标签；`product_racket` 拒绝；`category_digital` 改名/停用 |
| US-14 / UC-C14 | `trade_timeout` 启动扫描；`trade_abnormal_admin` 调整/解冻；`trade_frozen` 暂停续算 |

## 特别检查

- SC-04：普通私聊和逐笔交易分支分别保存已读；打开通知不改变任一聊天未读；打开会话历史也不自动推进已读，必须显式提交“已展示消息”。
- SC-05：竞争请求接受后其余自动关闭；约定多轮拒绝只结束提案，新约定确认后清当前完成确认并结束旧计时，历史仍可读。
- SC-06：争议保持锁单；恢复后旧确认保留为非当前、当前标记清空、不自动开始计时；管理员调整完成/终止不伪造双方确认。
- SC-07：问询、说明、申辩、管理员回复分属同一事项沟通，不混同普通 IM；已结举报只读，不能补充或重新提交；不予处理时 `public_result=null`，不主动通知被举报人。
- SC-09：超时用预置历史确认时间由真实扫描任务触发异常并冻结；冻结暂停等待，解冻按剩余续算；封禁解除不误清另一事项的展示限制或交易冻结。
- SC-10：分类改名保留旧别名；已关联分类只停用；未关联分类可逻辑删除；标签通过/别名/拒绝结果各自可见。
- SC-12：本人入口按权限读取商品/交易/收藏/评价/举报；公开结果不泄露举报人；管理员私聊读取仅限事项必要范围。

## 人工边界与未覆盖

- 实际付款、交付和线下验货由当事人完成；消息中的“已付款/已转账”是当事人声明，平台不托管、不认定资金结果。
- 注册、找回密码、换邮箱、真实邮件送达依赖可用 SMTP 与真实收件箱，seed 不预置验证码；退出后的服务端吊销范围沿用现行实现。
- 持久 seed 只准备状态和历史；生命周期动作在隔离回归中执行，真实服务上的现场点击结果需人工观察，不能由 seed 标记或静态目录替代。
- 图片与证据使用现有 13 张演示素材，多条实例可复用，不能当作真实实拍或真实举报证据；未调用外部生成。真实资源核验与隔离回归分别记录。
