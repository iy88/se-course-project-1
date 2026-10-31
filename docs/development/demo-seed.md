<!--
Version: 0.1.0
Version-Datetime: 2026-10-31T11:10:47+08:00
-->

# 演示数据与操作路线

本文按现行需求组织演示路线。表中列出操作和预期结果，实际执行结果分别记录。预置数据用于历史展示，现场操作用于观察实际行为；改变状态后使用另一条适合的记录或重新准备数据。完整分支及资格见[浏览器需求覆盖矩阵](浏览器需求覆盖矩阵.md)。

## 准备与启动

先确认 `backend/.env.dev` 指向预期的演示数据库与存储（PostgreSQL + OSS 或 SQLite + local），并准备好相应服务。下面从项目根目录运行；迁移和演示 seed 作用于所选环境，使用前确认目标。演示数据保留在该数据库和存储中，供浏览器登录使用。

```bash
(cd backend && APP_ENV_FILE=.env.dev .venv/bin/python -m app.manage migrate)
(cd backend && .venv/bin/python -m app.manage demo-seed --env-file .env.dev)
./scripts/dev.sh start
```

服务也须读取同一环境文件；若使用其他文件，迁移和 `start` 同样设置 `APP_ENV_FILE`，seed 的 `--env-file` 指向同一文件。默认 manifest 位于 `var/demo/manifest.json`，含演示登录信息，应按敏感文件保管。需要独立的新演示批次时可指定另一持久路径：`--manifest <路径>`；具体账户和对象以生成的 manifest 为准。

manifest 的 `accounts` 给出邮箱和密码，`objects` 给出记录 ID。使用以下身份和记录定位起点；账户密码由 seed 生成，以 manifest 为准。

每个文件先将 key 记入私有 manifest，再写入所选存储。发生中断后，使用同一 manifest 重跑：命令核对并复用已写入文件，补齐尚未完成的写入。成功后的重复执行保留人工修改和业务处理结果。另选 `--manifest` 路径会准备一组独立演示数据。

| 身份或对象 | 用途 |
|---|---|
| `admin`、`admin2` | 管理员认领、处理与另一管理员权限检查 |
| `seller`、`buyer`、`buyer2`、`outsider` | 商品发布、购买竞争、咨询和越权检查 |
| `frozen_seller`、`frozen_buyer` | 独立冻结交易及双方沟通限制 |
| `banned`、`ban_seller` | 封禁与关联请求、交易及解除限制 |
| `timeout_seller`、`timeout_buyer` | 单方确认超时和异常处置 |
| `product_listed`、`product_pending`、`product_rejected`、`product_delisted` | 搜索／收藏、待审、拒绝后重提及审核有效商品重新上架 |
| `trade_request_buyer`、`trade_request_buyer2` | 同一商品上的两条待接受请求，卖方接受一条后观察另一条关闭 |
| `trade_progress`、`trade_confirm`、`trade_completed`、`trade_reviewed`、`trade_disputed` | 待约定、已约定单方确认、完成、已有一方评价及争议历史；对应约定见 `agreement_confirm` |
| `trade_timeout`、`agreement_timeout` | 已超过等待阈值的单方确认历史，启动扫描后观察异常事项 |
| `trade_frozen`、`trade_ban_progress`、`trade_ban_request` | 冻结和封禁关联记录；已关闭请求可查历史 |
| `category`、`category_unused` | 已使用分类（含别名）及未关联分类，分别演示维护与删除 |
| `case_product_review`、`case_report`、`case_report_handled`、`case_dispute_disputed`、`case_dispute_frozen`、`case_ban` | 审核、待处理和已处置举报、争议及封禁事项 |
| `conversation_normal`、交易会话和通知 | 普通私聊与按笔交易分支、独立已读及业务通知 |

建议先查看搜索、收藏及本人业务，再进行审核、请求竞争及交易确认，最后进行举报和限制处置；会改变资格或结束记录的分支使用独立对象。

演示账号使用 example.com 地址；注册、找回密码及换邮箱使用另行注册的真实可收件账号，须真实完成邮箱验证；七天超时可使用 seed 预置的历史确认时间，由现有扫描任务实际判断和转异常；记录该历史时间为演示预置数据。完成确认、认领、审核、冻结和处置等分支由用户或管理员实际操作并观察结果；已有记录仅作为起点和历史展示。

## 演示路线与需求映射

以下每行列出一组故事及其同号主用例；操作均由对应角色实际执行，结果需当场观察。多个互斥分支使用不同记录。

| 用户故事／用例 | 触发、分支及预期结果 | 场景 |
|---|---|---|
| US-01 / UC-C01 | 用户登录、退出，验证邮箱注册、找回及修改密码、换邮箱和显示名称；错误凭证、重复邮箱或未验证邮箱应被拒绝，封禁后保留合格只读及管理沟通。邮箱流程需可用的真实收件环境。 | SC-01 |
| US-02 / UC-C02 | 卖方查看禁发范围并发布，管理员认领审核通过或拒绝；卖方看原因后修改重提。另演示允许的编辑、主动下架关闭待请求、符合资格重新上架；锁单期间下架及关键修改被拒绝。 | SC-02、SC-10 |
| US-03 / UC-C03 | 买方以关键词、多标签及价格组合查询、查看详情；无匹配显示空结果，别名定位同一分类，受限商品不泄露详情。 | SC-03、SC-10 |
| US-04 / UC-C04 | 买方收藏、评论和发起普通私聊，卖方回复；请求后进入独立交易分支。取消收藏、删除本人评论、查看失效收藏及各会话独立未读；无权回复或发送受限时拒绝。 | SC-03、SC-04、SC-11 |
| US-05 / UC-C05 | 两名买方对同一商品请求，卖方接受一条后锁单并关闭另一条；另演示拒绝、撤回、首次约定的同意／拒绝、约定变更、双方确认、阶段性取消和争议。未经同意的变更保留原约定；单方确认不等于完成。 | SC-05、SC-06、SC-09、SC-11 |
| US-06 / UC-C06 | 生效约定后双方各提交一次交付与支付完成声明，查看当前确认与历史；需更正时向管理事项说明，由认领管理员留据处理，用户不直接改写历史。 | SC-05、SC-06 |
| US-07 / UC-C07 | 双方在完成交易后分别评价；重复评价或未完成交易评价被拒。对有效对象提交举报、未结时补充，结案后只读；查询本人评价和匿名处理结果。 | SC-07、SC-12 |
| US-08 / UC-C08 | 管理员认领审核／举报，核查并记录通过、拒绝、不处置或实际处置理由；问询、说明、申辩和回复分别留痕。另一管理员不能重复认领；封禁／解除、冻结／恢复按资格及其他限制核对。 | SC-02、SC-06、SC-07、SC-09 |
| US-09 / UC-C09 | 对照公开、交易中、下架及受限制商品查看状态和可用操作；接受请求后锁单，结束后默认下架，卖方符合资格可明确继续上架。 | SC-02、SC-03、SC-05、SC-06、SC-09 |
| US-10 / UC-C10 | 管理员分别选择时间范围和全部，查看完成交易及查询时点账户、商品、待办、交易统计；未选择范围不应当作默认全部。 | SC-08 |
| US-11 / UC-C11 | 实际触发审核、请求或处理事件后查看对应通知和待办；打开具体通知才标记该通知已读，聊天已读独立计算，进入通知不代替业务确认。 | SC-11 |
| US-12 / UC-C12 | 分别以买卖双方查看我的商品、交易、收藏、发表／收到评价、举报和管理沟通；结束记录只读，收到举报仅展示已实际处置事项且不暴露举报人。 | SC-12 |
| US-13 / UC-C13 | 管理员新建分类、改名及维护别名；卖方申请标签随商品审核通过生效。关联过商品的分类停用，未关联分类可逻辑删除；原归属及历史保留。 | SC-10、SC-03 |
| US-14 / UC-C14 | 有效约定后单方确认，使用已到期的历史确认起点，由系统任务触发异常和冻结；管理员认领、留依据处理及通知，恢复时清当前确认并保留历史。争议结束旧计时，恢复不自动开始新计时；不伪造双方确认。 | SC-09、SC-05、SC-06、SC-11 |

特别检查：SC-04 的普通聊天与各交易分支分别标读；SC-05 的多请求关闭、拒绝、撤回、阶段性取消及变更确认分别使用独立记录；SC-06 的争议恢复保留历史、重新确认才开始完整等待；SC-07 的问询、实际处置与申辩不要混同；SC-08 的统计时间范围要显式选择；SC-09 的超时使用预置历史时间并由实际任务触发；SC-10 的分类变更保留身份和历史；SC-11 的通知、聊天各自已读；SC-12 的本人入口按权限读取。各条结果以实际演示记录为准。

## 子用例逐项路线

表中的起点是推荐记录；需要相同前置条件的互斥动作时，先通过界面创建另一条记录。邮箱操作使用可接收邮件的地址。表内描述为现场动作和预期，执行记录另行填写。

| 子用例 | 账号与起点 | 现场动作及预期 |
|---|---|---|
| UC-C01-01 | buyer；登录账户；注册和换邮箱另备真实邮箱 | 未注册、邮箱可用；验证当前注册邮箱由本人控制；未验证或验证失败拒绝创建，验证通过且邮箱唯一、必填资料有效后分配唯一用户ID，保存唯一登录邮箱，创建账户 |
| UC-C01-02 | buyer；登录账户；注册和换邮箱另备真实邮箱 | 账户已存在；校验邮箱与密码，有效时进入本人账户；错误时拒绝，首版不设登录失败次数阈值，不因失败次数自动锁定账户 |
| UC-C01-03 | buyer；登录账户；注册和换邮箱另备真实邮箱 | 已登录；结束本次登录访问，后续业务访问重新验证身份 |
| UC-C01-04 | 新注册的真实可收件账号 | 忘记密码；验证绑定邮箱后设置新密码，用户ID及历史保持 |
| UC-C01-05 | buyer；登录账户；注册和换邮箱另备真实邮箱 | 已登录并能验证当前密码；验证当前密码后更新，保留原用户ID |
| UC-C01-06 | 新注册的真实可收件账号及另一可收件邮箱 | 已登录且可验证新旧邮箱；验证两邮箱及新邮箱唯一性，成功后用新邮箱登录，ID及历史保持 |
| UC-C01-07 | buyer；登录账户；注册和换邮箱另备真实邮箱 | 已登录本人账户；按内容规则修改显示名称，历史操作主体及当时名称保留 |
| UC-C02-01 | seller、admin；product_pending / product_rejected / product_delisted | 查看禁发范围须已登录；提交须本人有发布资格；可先独立查看当前禁发范围；选择发布时填写商品及标签／申请，校验后进入待审核，等待认领 |
| UC-C02-02 | seller、admin；product_pending / product_rejected / product_delisted | 本人商品已有审核结论；读取当次结果、拒绝原因及关联通知 |
| UC-C02-03 | seller、admin；product_pending / product_rejected / product_delisted | 本人商品审核未通过，或待审核时撤回后处于已下架且尚未经审核通过；修改后重提，进入待审核及共享待处理池，形成新的审核记录，旧记录保留 |
| UC-C02-04 | seller、admin；product_pending / product_rejected / product_delisted | 本人商品允许编辑；保存前后内容，保持展示和有效请求，并通知未结束请求的相关买方 |
| UC-C02-05 | seller、admin；product_pending / product_rejected / product_delisted | 本人商品无未结束锁单交易；置已下架，关闭待接受请求、注明原因并归档分支 |
| UC-C02-06 | seller、admin；product_pending / product_rejected / product_delisted | 本人商品处于已下架状态、审核有效且当前账户及商品限制允许；恢复公开可交易，后续交易记录及分支独立 |
| UC-C03-01 | buyer；product_listed、category（含别名） | 已登录；匹配关键词并返回当前公开可交易商品 |
| UC-C03-02 | buyer；product_listed、category（含别名） | 已登录并选择分类；解析主名／别名，多标签全部匹配，与其他条件同时生效 |
| UC-C03-03 | buyer；product_listed、category（含别名） | 已登录并设定价格区间；包含端点匹配价格，与关键词及标签共同过滤 |
| UC-C03-04 | buyer；product_listed、category（含别名） | 有商品入口；重新校验展示资格，展示当前详情及可操作范围 |
| UC-C03-05 | buyer；product_listed、category（含别名） | 当前条件无匹配；返回空列表和无匹配商品提示，隐藏非公开商品 |
| UC-C04-01 | buyer、seller、outsider；product_listed、conversation_normal | 已登录、未封禁且商品可收藏；保存本人收藏关系，保持他人不可见 |
| UC-C04-02 | buyer、seller、outsider；product_listed、conversation_normal | 已存在本人收藏且未封禁；取消该收藏，失效商品仍可取消而不开放其内容 |
| UC-C04-03 | buyer、seller、outsider；product_listed、conversation_normal | 已登录本人账户；展示本人清单；交易中且有公开详情资格的收藏保持有效，失效项用通用提示且无公开详情入口 |
| UC-C04-04 | buyer、seller、outsider；product_listed、conversation_normal | 商品公开可交易或交易中且账户有资格；发表商品页评论，独立于收藏与私聊 |
| UC-C04-05 | buyer、seller、outsider；product_listed、conversation_normal | 该商品卖方且商品仍允许评论；回复买方评论；其他买方不能代卖方回复 |
| UC-C04-06 | buyer、seller、outsider；product_listed、conversation_normal | 本人已有评论或认领事项需移除违规内容；按作者或管理权限逻辑删除／移除并保留相关历史 |
| UC-C04-07 | buyer、seller、outsider；product_listed、conversation_normal | 双方为不同用户、发送资格允许；从个人页等入口建立或复用双人普通私聊，不依赖请求 |
| UC-C04-08 | buyer、seller、outsider；product_listed、conversation_normal | 会话／分支存在且当前资格允许；按各自归属保存或展示文字消息，仅已展示消息标读 |
| UC-C05-01 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 非本人商品公开可交易、无本人重复有效请求、资格允许；创建待接受记录和专属交易分支，通知卖方但暂不锁单 |
| UC-C05-02 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 本人为卖方且请求仍待接受、资格允许；接受一条并锁单，关闭其他待接受请求及通知相应买方 |
| UC-C05-03 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 本人为卖方且请求待接受；拒绝并通知，保留已拒绝历史，归档对应分支 |
| UC-C05-04 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 本人为买方且卖方未接受；撤回并通知卖方，旧入口不可继续接受 |
| UC-C05-05 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 交易有生效约定、进行中且资格允许；保存本方交付与支付统一确认；单方记进度，双确认后完成 |
| UC-C05-06 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 本人为交易一方且资格允许；填写说明进入有争议，保持锁单，结束原等待计时 |
| UC-C05-07 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 已接受交易且未冻结、资格允许；约定前买方可直接取消、卖方申请须买方同意；约定后双方同意，生效后已终止 |
| UC-C05-08 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 进行中尚无有效约定且资格允许；提出交付时间／文字地点／方式及金额／支付方式／时点，另一方同意后生效，拒绝只结束提案 |
| UC-C05-09 | buyer、buyer2、seller；trade_request_buyer / trade_request_buyer2 / trade_progress / trade_confirm | 进行中已有有效约定且资格允许；提出新安排，对方同意后替换并清空当前确认、结束旧计时；未同意沿用原安排及确认／计时，保存历史；生效后重新单方完成确认才开始完整7天等待 |
| UC-C06-01 | buyer、seller、admin；trade_confirm / trade_completed | 与UC-C05-05相同的有效约定及资格；执行同一次完成声明，保存用户ID、时间及可选说明，不新增第二个确认步骤 |
| UC-C06-02 | buyer、seller、admin；trade_confirm / trade_completed | 本人为交易参与者或认领管理员有必要访问资格；读取当前有效确认及历次确认，区分重置标记与保留历史 |
| UC-C06-03 | buyer、seller、admin；trade_confirm / trade_completed | 已提交记录确需更正；向对应管理事项说明，由认领管理员留据处理，用户不自行改写原记录 |
| UC-C07-01 | buyer、buyer2、admin；trade_completed、report / case_report | 交易完成、本人为双方之一且未封禁；每方每笔提交唯一1—5分及文字评价，重复或未完成拒绝 |
| UC-C07-02 | buyer、buyer2、admin；trade_completed、report / case_report | 已登录且本人为评价者或被评价者；在“我的评价”按发表／收到读取并关联交易；拒绝其他用户越权读取，不提供商品页公开展示 |
| UC-C07-03 | buyer、buyer2、admin；trade_completed、report / case_report | 未封禁且可定位有效举报对象；填写对象及原因，可选证据，创建举报并进入共享池 |
| UC-C07-04 | buyer、buyer2、admin；trade_completed、report / case_report | 本人举报已有处理结果；查看本人进度，管理员确认后读取匿名公开结论及本人通知 |
| UC-C07-05 | buyer、buyer2、admin；trade_completed、report / case_report | 同对象已有本人未结举报，或原举报已结案；未结补充原事项，不重复新建；已结案归档只读，拒绝补充或重新提交 |
| UC-C08-01 | admin、admin2、seller、banned；case_product_review / case_report / case_ban / case_dispute_frozen | 管理员发起问询，或认定举报有效并实际处置；被询问用户从问询通知提交说明；受处置用户从处置通知或本人事项入口提交申辩；管理员原事项回复并告知；未处置不主动告知被举报人 |
| UC-C08-02 | admin、admin2、seller、banned；case_product_review / case_report / case_ban / case_dispute_frozen | 管理员登录、事项待认领；校验同一事项唯一认领，保存认领归属 |
| UC-C08-03 | admin、admin2、seller、banned；case_product_review / case_report / case_ban / case_dispute_frozen | 本人认领事项；在必要范围核查证据，记录不予处理或实际处置结论及理由 |
| UC-C08-04 | admin、admin2、seller、banned；case_product_review / case_report / case_ban / case_dispute_frozen | 认领事项有账户限制处置依据；记录封禁或有依据解除，通知实际范围并保留其他限制 |
| UC-C08-05 | admin、admin2、seller、banned；case_product_review / case_report / case_ban / case_dispute_frozen | 认领事项涉及交易且有处置依据；冻结交易或有依据解除；双方限制与管理员处理资格分别校验 |
| UC-C08-06 | admin、admin2、seller、banned；case_product_review / case_report / case_ban / case_dispute_frozen | 本人认领待审商品；读取当次商品及申请标签，记录通过／拒绝与原因，联动展示并通知发布者 |
| UC-C09-01 | buyer、seller；product_listed / product_delisted、trade_progress | 有商品访问资格；读取生命周期及展示资格，明确当前允许的请求／评论／维护操作 |
| UC-C09-02 | buyer、seller；product_listed / product_delisted、trade_progress | 接受请求、交易结束或处置事件生效；读取商品联动结果；结束默认下架，有资格明确继续才公开 |
| UC-C10-01 | admin；预置商品、交易和事项 | 管理员已登录；显式选范围或全部，按结果确认时间统计完成交易 |
| UC-C10-02 | admin；预置商品、交易和事项 | 管理员已登录；按查询时点读取用户、各状态商品、审核／举报待办及交易状态数，封禁数单列 |
| UC-C11-01 | buyer、seller、admin；通知、trade_request_buyer / case_product_review | 对应业务事件已生效且接收人有资格；产生关联原事项的站内通知，多个入口不重复创建业务 |
| UC-C11-02 | buyer、seller、admin；通知、trade_request_buyer / case_product_review | 本人有相关通知或管理员有共享池事项；查看待办并进入当前事项，业务操作在原入口明确执行 |
| UC-C11-03 | buyer、seller、admin；通知、trade_request_buyer / case_product_review | 打开具体通知；仅该通知自动标已读；列表和其他分支不标读，聊天单独计算 |
| UC-C12-01 | buyer、seller、banned；预置商品、交易、收藏、report / case_ban | 本人有发布记录；查全部状态商品、审核原因及关联请求，按资格继续维护 |
| UC-C12-02 | buyer、seller、banned；预置商品、交易、收藏、report / case_ban | 本人有买卖交易及收藏记录；聚合两种身份的全部请求／交易与本人收藏，结束交易只读 |
| UC-C12-03 | buyer、seller、banned；预置商品、交易、收藏、report / case_ban | 本人有评价或举报及处置沟通；分我发表／收到评价、我的举报／我收到的举报，收到事项仅已实际处置且隐去举报人 |
| UC-C13-01 | admin、seller；category / category_unused、product_pending | 管理员有分类管理资格或卖方随商品申请；管理员可主动创建，卖方申请随商品通过生效，初始条目由管理员准备 |
| UC-C13-02 | admin、seller；category / category_unused、product_pending | 管理员维护已有分类；改主名保留旧别名，分类身份、商品归属及交易历史保持 |
| UC-C13-03 | admin、seller；category / category_unused、product_pending | 分类曾或未关联商品；关联过仅停用，未关联可逻辑删除，有在售时停用标签仍可筛选 |
| UC-C13-04 | admin、seller；category / category_unused、product_pending | 管理员维护别名或纠正分类有依据；主名别名指同一分类，移除别名不改归属；纠类留前后内容并通知卖方，不改交易约定 |
| UC-C14-01 | timeout_buyer、timeout_seller、admin、admin2；trade_timeout 及扫描产生的事项 | 已有有效约定且单方完成确认后7天未回应；系统内部触发异常及冻结、保持锁单；争议已结束计时则不按旧计时触发 |
| UC-C14-02 | timeout_buyer、timeout_seller、admin、admin2；trade_timeout 及扫描产生的事项 | 异常事项待认领；进入共享池，由一名管理员认领并按必要范围访问 |
| UC-C14-03 | timeout_buyer、timeout_seller、admin、admin2；trade_timeout 及扫描产生的事项 | 本人认领异常事项；核查留据调整状态并通知；恢复保留有效约定、清当前确认，结束解本笔冻结而保留其他限制 |

## 场景顺序

| 场景 | 起点与现场顺序 |
|---|---|
| SC-01 | `buyer` 登录、退出、改密和改名；另用真实邮箱注册、重置及换邮箱；用 `banned` 对照限制及管理沟通。 |
| SC-02 | `seller` 查看禁发范围并提交商品；`admin` 认领 `case_product_review` 审核；卖方查看 `product_rejected` 原因后重提，再用 `product_delisted` 上架。另用锁单商品检查禁止下架。 |
| SC-03 | `buyer` 检索 `product_listed`，以 `category` 主名及别名、价格组合筛选，收藏并对照下架及空结果。 |
| SC-04 | `buyer`、`seller` 查看商品评论和 `conversation_normal`，再进入 `trade_request_buyer` 分支；比较各会话未读、回复权限及受限发送。 |
| SC-05 | `seller` 接受 `trade_request_buyer`，观察另一请求关闭；对 `trade_progress` 提案、确认约定并完成交易；另建请求演示拒绝、撤回和取消，用 `trade_confirm` 演示变更及单方确认。 |
| SC-06 | `buyer2`、`seller` 查看 `trade_disputed`；`admin` 认领 `case_dispute_disputed` 并处理恢复，检查锁单、有效约定与确认历史；另用 `trade_frozen` 检查限制。 |
| SC-07 | `buyer`、`seller` 对 `trade_completed` 互评，并以 `trade_reviewed` 查看已有评价；`buyer2` 查看并补充 `report`，`admin` 认领 `case_report` 处置；`banned` 和 `case_ban` 展示封禁历史、申辩和解除。 |
| SC-08 | `admin` 打开统计，分别选全部及指定范围，核对预置商品、交易、待办和封禁账户计数；对照空范围及无权限角色。 |
| SC-09 | 启动扫描处理 `trade_timeout` 的到期历史，`admin` 认领新异常事项；双方检查冻结限制，管理员留据恢复或终止。用独立记录对照仅解除冻结和恢复的确认／计时差异。 |
| SC-10 | `admin` 维护 `category` 的主名与别名，停用已使用分类；处理 `product_pending` 标签申请，另对 `category_unused` 演示删除及普通用户权限拒绝。 |
| SC-11 | `seller` 访问请求通知列表并打开具体通知，对照 `conversation_normal` 与交易分支未读，再处理 `trade_request_buyer`；旧入口重新检查状态。 |
| SC-12 | `seller`、`buyer` 查看本人商品、交易、收藏和评价；`buyer2` 查看 `report`，`banned` 查看 `case_ban` 管理沟通；对照他人私有记录及结束记录只读。 |
