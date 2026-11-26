<!--
Version: 0.1.0
Version-Datetime: 2026-11-26T23:30:00+08:00
-->

# [测试主验证][C] US-05／06／14 交易与异常处理 执行报告

## 基本信息

| 字段 | 内容 |
|---|---|
| 批次 | C |
| 负责人／审查人 | 孙含佳（`shjj11`）／袁尚峰（`iy88`） |
| 用户故事 | US-05、US-06、US-14 |
| 执行项 | C01—C18（共 18 项） |
| 代码版本 | 分支 `test/evidence-trade-exception-shjj11`；被测代码 `main` |
| 环境 | 用户端；管理端；API；PostgreSQL；Redis；OSS；SMTP；浏览器：待登记 |
| 依赖类型 | 全部真实（PostgreSQL／Redis／OSS／SMTP 均为本批独立实例） |

## 环境准备

| 检查 | 命令或页面 | 实际结果 | 证据 |
|---|---|---|---|
| PostgreSQL | 本批独立测试库（不与其他批次共用） | 待执行 | `evidence/RUN-C1/` |
| Redis | 本批独立命名空间前缀 | 待执行 | `evidence/RUN-C1/` |
| OSS | 私有、关闭版本控制，写读删通过 | 待执行 | `evidence/RUN-C1/` |
| SMTP | 测试邮箱收到验证码 | 待执行 | `evidence/RUN-C1/` |
| 服务启动 | `java -jar backend-app/target/backend-app-*.jar --env-file=backend/.env.<本批>` | 待执行 | `evidence/RUN-C1/` |

## 测试账户与基础数据

| 对象 | 创建方式 | 标识／用途 | 清理方式 |
|---|---|---|---|
| 卖方 | 前端注册 + 真实验证邮件 | 待登记 | 本批库内直接删除 |
| 买方 A／B（竞争买方） | 前端注册 + 真实验证邮件 | 待登记 | 本批库内直接删除 |
| 管理员 | `maintenance account create-manager` | 待登记 | 本批库内直接删除 |
| 分类／商品／图片 | 管理端／用户端创建 | 待登记 | 连带清理 |

敏感值使用角色缩写或测试 ID，不写真实邮箱、密码、验证码。

## 执行流程

### RUN-C1：C01—C09 交易主链路

| 字段 | 内容 |
|---|---|
| 覆盖执行项 | C01—C09 |
| 覆盖原 TC | TC-TRD-001—005、009—012、014—016；TC-COM-001、002、010；TC-CASE-005 |
| 设计依据 | US-05 验收条件；TRD-IF API-TRD-001—011、013；TRD-KD 转换与计时表；R1 接受／完成／终止调用；C1 幂等与锁序；CASE-IF CASE-007 |
| 前置条件 | 卖方与买方 A／B 已注册并登录；存在公开在售商品 |
| 合成数据 | 商品由卖方发布；竞争买方向同一商品发起请求 |
| 前端步骤 | 待记录（两个浏览器上下文） |
| 接口／DB／Redis／OSS 核对 | 交易状态、占用索引、`trade_pending_buyer_idx`／`trade_product_occupancy_idx` 实际值 |
| 实际结果 | 待执行 |
| 结论 | 未执行 |
| 缺陷 | 见「缺陷登记」 |
| 证据 | `evidence/RUN-C1/` |

### RUN-C2：C10—C12 边界与可见性

| 字段 | 内容 |
|---|---|
| 覆盖执行项 | C10—C12 |
| 覆盖原 TC | TC-TRD-010、011、015、016；TC-COM-001 |
| 设计依据 | TRD-KD「尚无有效约定」转换、TradeConfirmation、ConfirmationWait；C1 幂等；CASE-KD 管理范围 |
| 前置条件 | 存在待约定与已约定两种状态的交易 |
| 合成数据 | 复用 RUN-C1 数据并新增一笔未形成约定的交易 |
| 前端步骤 | 待记录 |
| 接口／DB／Redis／OSS 核对 | 确认记录的用户、时间、说明与约定版本 |
| 实际结果 | 待执行 |
| 结论 | 未执行 |
| 缺陷 | 见「缺陷登记」 |
| 证据 | `evidence/RUN-C2/` |

### RUN-C3：C13—C18 超时、冻结与恢复

| 字段 | 内容 |
|---|---|
| 覆盖执行项 | C13—C18 |
| 覆盖原 TC | TC-TRD-006、007、008、011、012、014；TC-CASE-001、005、007；TC-COM-003、010 |
| 设计依据 | TRD-KD「超时、重试与异常恢复」「计时规则」；CASE-KD 异常与争议事项、认领与处理权限、处置后申辩；R2B 账户与交易限制、部分恢复 |
| 前置条件 | 单方确认的交易；可用受控时钟推进 7 天 |
| 合成数据 | 超时与冻结所需的确认记录、事项与处置记录 |
| 前端步骤 | 待记录 |
| 接口／DB／Redis／OSS 核对 | 冻结来源计数、计时起止、占用与归档状态、通知与实时摘要 |
| 实际结果 | 待执行 |
| 结论 | 未执行 |
| 缺陷 | 见「缺陷登记」 |
| 证据 | `evidence/RUN-C3/` |

## 执行项结果

| 执行项 | 场景摘要 | 覆盖原 TC | 结果 | 缺陷／备注 | 证据 |
|---|---|---|---|---|---|
| C01 | 重复购买请求与本人商品请求 | TC-TRD-001、002；TC-COM-002 | 通过 | 重复请求 409 REQUEST_DUPLICATE；本人商品 403 ACTION_NOT_ALLOWED；DB 待接受请求数为 1 | [证据](evidence/RUN-C1/RUN-C1-steps.md) |
| C02 | 两买方竞争，卖方先后／同时接受 | TC-TRD-001；TC-COM-002 | 通过 | 接受其中一笔后另一笔 closed（other_user_locked）；商品 occupied_by_trade_id 指向该交易且 lifecycle_state=in_trade | [证据](evidence/RUN-C1/RUN-C1-steps.md) |
| C03 | 接受前撤回与卖方拒绝 | TC-TRD-002、003、005 | 通过 | 撤回后 status=withdrawn；拒绝后 status=rejected | [证据](evidence/RUN-C1/RUN-C1-steps.md) |
| C04 | 首次约定双方同意／拒绝 |TC-TRD-004、005 | 通过 | 卖方提出、买方同意后约定 effective；另一组拒绝后 rejected 且交易保持待约定 | [证据](evidence/RUN-C1/RUN-C1b-steps.md) |
| C05 | 已有单方确认时变更约定 |TC-TRD-004、005、015 | 通过 | 变更约定携带 base_agreement_id、version_no=2，同意后生效 | [证据](evidence/RUN-C1/RUN-C1b-steps.md) |
| C06 | 首约前取消、协商终止与拒绝 |TC-TRD-009 | 通过 | 首约前买方取消返回 mode=direct，交易 terminated／cancelled | [证据](evidence/RUN-C1/RUN-C1b-steps.md) |
| C07 | 双方完成确认后下架与归档 |TC-TRD-010、015；TC-COM-001 | 通过 | 单方确认仅记录仍 in_progress；双方确认后 completed、商品 off_shelf、占用释放 | [证据](evidence/RUN-C1/RUN-C1b-steps.md) |
| C08 | 争议发起、双方确认解决、恢复 |TC-TRD-008、011；TC-COM-010 | 通过 | 争议 disputed；双方确认解决后 resolved 且交易恢复 in_progress | [证据](evidence/RUN-C1/RUN-C1b-steps.md) |
| C09 | 管理员完成／终止，再调整已完成交易 | TC-TRD-012、014；TC-CASE-005 | 未执行 | | |
| C10 | 无有效约定时提交完成确认被拒 | TC-TRD-010；TC-COM-001 | 未执行 | | |
| C11 | 单方确认只记进度，双方确认完成 | TC-TRD-010、015、016 | 未执行 | | |
| C12 | 确认历史可见性与管理员范围 | TC-TRD-010、011、016 | 未执行 | | |
| C13 | 受控时钟推进 7 天触发异常与事项 | TC-TRD-006；TC-CASE-001 | 未执行 | | |
| C14 | 等待中争议被视为回应 | TC-TRD-008、011；TC-COM-010 | 未执行 | | |
| C15 | 管理员认领共享池异常事项 | TC-CASE-001、005 | 未执行 | | |
| C16 | 冻结期间操作与消息被拒 | TC-TRD-006、007；TC-COM-003 | 未执行 | | |
| C17 | 解冻恢复不重启计时 | TC-TRD-011；TC-CASE-007 | 未执行 | | |
| C18 | 异常交易完成／终止后再恢复被拒 | TC-TRD-011、012、014；TC-CASE-005 | 未执行 | | |

## 自动测试补充

| 测试位置 | 对应执行项 | 命令 | 结果 |
|---|---|---|---|
| 待登记 | C02／C07／C08（并发与事务） | `mvn -o -pl backend-app test -Dit.envFile=<本批 env>` | 待执行 |

## 缺陷登记

| Issue | 现象 | 影响执行项 | 状态 |
|---|---|---|---|
| #162 | 上传失败提示把对象存储跨域拦截误报为网络问题 | 与本批证据上传路径相关（发现于执行准备阶段） | 修复 PR #163 待合入；桶 CORS 白名单需主账号补充 |
| #142 | 纠类缺少依据返回 422 | 与本批无直接关系（B 批记录） | 已由 #143 修复并合入 `main` |

## 证据索引

| RUN | 目录 | 内容 |
|---|---|---|
| C1 | `evidence/RUN-C1/` | 页面截图、网络摘要、DB 核对、通知与实时摘要 |
| C2 | `evidence/RUN-C2/` | 同上，含确认历史 |
| C3 | `evidence/RUN-C3/` | 同上，含受控时钟与冻结来源核对 |

证据规范见 [证据目录说明](../证据目录说明.md)：每个 RUN 一个目录，文件按 `RUN-C<编号>-<内容>.<扩展名>` 命名，提交前脱敏（邮箱、验证码、密码、Cookie、CSRF、AccessKey、带签名 URL 一律不提交）。

## 状态

- 执行进度：C01—C08 已通过；C09 与 RUN-C2、RUN-C3 待执行。
- 本分支已提交环境与账号准备、报告骨架，以及 RUN-C1 的步骤、网络、DB 证据；后续按 RUN 逐步补齐页面截图与 OSS／Redis 结果。
- 完成后请求 `iy88` 审查，并在 #138 说明通过／失败项与复测结论。
