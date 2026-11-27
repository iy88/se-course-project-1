# 批次 D 执行日志

## 2026-11-26 22:14 依赖探针（真实 SMTP）

`SMTP server accepted test message d52cb4a3-b888-4011-984d-6f9b1ebcf087`；PostgreSQL、Redis、OSS 同批通过。环境准入达成。

## 22:20—22:30 账户注册

| 账户 | account_id | 邮箱 | 登录 |
|---|---|---|---|
| `qa-buyer-b` | 1 | <redacted-email> | 200，roles=user |
| `qa-seller` | 2 | <redacted-email> | 200，roles=user |
| `qa-outsider` | 3 | <redacted-email> | 200，roles=user |
| `qa-buyer-a` | 4 | <redacted-email> | 200，roles=user |

偏差与处理：`GET /account/entry-context` 每次调用都会签发新入口令牌（`AccountEntryController` → `EntryTokenService.issue()`），而注册要求验证码与请求时的入口令牌 digest 一致（`AccountService.register` 比对 `entryDigest`）。首次注册尝试因请求后又刷新入口令牌全部返回 422 `VERIFICATION_CODE_INVALID`，`failed_attempts` 保持 0；修正为「请求验证码后不再刷新入口，直接注册」后四个账户均 201。

## 22:30 商品与图片（真实 OSS）

逐件走 `POST /files/uploads` → 签名表单直传 OSS（HTTP 204）→ `POST /files/{id}/completion`（200，`state=verified`）→ `POST /products`。

| product_id | 标题 | 图片 file_id | 审核 audit_id | 事项 case_id | 生命周期 |
|---|---|---|---|---|---|
| 1 | 批次D P1 商品 | 1 | 1 | 1 | pending_review |
| 2 | 批次D P2 待审商品 | 2 | 2 | 2 | pending_review |
| 3 | 批次D P3 举报对象 | 3 | 3 | 3 | pending_review |
| 4 | 批次D P4 冻结对象 | 4 | 4 | 4 | pending_review |

四个商品各带一个待处理分类申请（数码配件／书籍资料／生活用品／运动器材）；`file_reference` 均为 `product/{id}/image`，`file_record.state=verified`；`product_audit` 四条 `pending`。

## 待补

- 两个管理员账户（`account create-manager`，需交互终端）。
- 审核 P1—P4 → 公开；随后 T1 完成交易、T2 进行中、T3 终止与评价／举报数据链。

## 2026-11-26 22:30—22:45 D-RUN-01 / D-RUN-02 前半（接口驱动）

| 执行项 | 结果 | 关键证据 |
|---|---|---|
| D01 评价唯一性 | 7/8 | 双向评价 201；重复 409 REVIEW_ALREADY_SUBMITTED；未完成/已终止 409 TRADE_NOT_COMPLETED；`/me/reviews` 两方向各 1 条 |
| D01 偏差 | 1 | 非参与方提交评价实际 404 RESOURCE_NOT_VISIBLE，契约与 TC-TRD-013 期望 403 ACTION_NOT_ALLOWED |
| D02 评价移除 | 通过 | `trade_review.visible=false`、`content=null`、`rating` 保留；作者收通知；处置行 result_status=applied |
| D02 封禁/冻结边界 | 通过 | 封禁后评价 403 ACCOUNT_WRITE_RESTRICTED；冻结期间评价另一笔已完成交易 201；冻结期间发布商品 409 TRADE_FROZEN；冻结期间会话发送 403 MESSAGE_SEND_FORBIDDEN |
| D03 四类举报 | 通过 | 商品/评论/消息/评价各 201；证据与事项同事务（case_evidence 1 条 submitter_attachment）；本人对象 422 TARGET_INVALID；共享池 report=4 |
| D04 补充/结案/公开 | 通过 | 补充 200；结案 200；结案后补充 409 CASE_CLOSED；公开前 /case-results total=0、公开后 1 且不含身份字段 |
| D05 认领竞争 | 通过 | 并发认领 200/409；非认领人详情 404；重复认领 200 幂等 |
| D06 审核锁后内容 | 通过 | 认领后卖方编辑 version=2，结论 reviewed_content_version=3 且商品转 public |
| D09 多执行回滚 | 6/7 | 含失败执行的整次回滚（商品仍公开、409 TARGET_STATE_CONFLICT）；仅撤公 201；解除 200 restored_scope=[account:2,account:4] |
| D09 偏差 | 1 | 重复解除同一 enforcement（新幂等键）返回 200 重放，契约期望 409 RESTRICTION_NOT_ACTIVE |

## 2026-11-26 23:20—23:46 D16 实时双端（人工浏览器）

- 同账号 `qa-buyer-a` 普通窗口 + InPrivate 窗口，`qa-seller` 第三窗口，均在 `/conversations/trade/2`。
- ① 双端同步：卖方发送后两端会话即时出现、未读计数变化；前端 `realtime.ts` 收到 `event` 只刷新快照与徽标，不弹 toast（属设计）。
- ② 断线补取：A2 断网期间卖方连发三条，恢复后补齐、顺序一致、不重复；数据库 `trade_conversation=2` 共 13 条、`seq` 1—13 连续无空洞。
- ③ 撤销：A1 退出仅该 Session 停推并跳登录，A2 为独立 Session 不受影响；A2 自身退出后卖方再发消息无任何提示。
- 未覆盖：`sync_reset`（超期游标／epoch）与「无权事件只回 cursor_advance」需双实例集成测试（TC-COM-024／025）。
- 为恢复双方会话发送，执行了 case 18 的 `lift`（`restored_scope=[account:2,account:4]`），无剩余冻结。
