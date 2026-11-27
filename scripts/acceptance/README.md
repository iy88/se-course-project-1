# 验收补充断言脚本

`batch-b-assertions.mjs` 用真实接口与真实 PostgreSQL 复核 B 批中无法只靠页面判断的断言：唯一性、幂等、权限、未读推进、版本递增与交易快照不变。脚本不读取仓库内的任何凭据，账号密码和数据库连接都来自环境变量。

## 前置条件

- 验收栈已启动：API `127.0.0.1:8080`、管理端来源 `127.0.0.1:3001`，数据库完成迁移。
- 验收库中存在报告“测试账户与基础数据”一节列出的对象，且处于以下状态：
  - 账户：买方 A `4`、买方 B `5`、卖方 `3`、管理员 A `1`；脚本默认使用测试域邮箱，可用环境变量覆盖。
  - 商品 `4` 公开、可被收藏；分类 `4`、`7` 有效且在售商品中可选；分类 `6` 有效；分类 `4` 有一个可移除的别名（脚本会先创建“幂等别名”再移除）。
  - 商品 `2` 处于交易中，交易 `2` 有约定和历史快照；商品 `4` 与 `2` 的纠类依据分别引用事项 `5` 与 `2`。
  - 商品 `1` 有评论 `1`，评论 `9` 已由作者删除。
- 本机 PATH 中有 `psql`，并可用 `PG*` 变量连接验收库。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `ACCEPTANCE_PASSWORD` | 是 | 测试账户统一密码；只放在当前终端环境，不写入仓库 |
| `PGHOST` `PGPORT` `PGDATABASE` `PGUSER` `PGPASSWORD` | 是 | 验收库连接；`PGPASSWORD` 为数据库应用账号密码 |
| `ACCEPTANCE_API_BASE` | 否 | 默认 `http://127.0.0.1:8080/api/v1` |
| `ACCEPTANCE_WEB_ORIGIN` | 否 | 默认 `http://127.0.0.1:3001`，用作请求 `Origin` |
| `ACCEPTANCE_BUYER_A` `ACCEPTANCE_BUYER_B` `ACCEPTANCE_SELLER` `ACCEPTANCE_MANAGER` | 否 | 默认测试域账号，见报告账号表 |
| `ACCEPTANCE_LOG` | 否 | 写入日志的路径；不设置时只输出到终端 |

## 运行

```bash
cd <repo>
ACCEPTANCE_PASSWORD="$TEST_PASSWORD" \
PGHOST=127.0.0.1 PGPORT=5432 PGDATABASE=project1_acceptance \
PGUSER=project1_dev_app PGPASSWORD="$DB_PASSWORD" \
ACCEPTANCE_LOG=docs/design/test-cases/reports/batch-b-catalog-interaction/evidence/B-RUN-00-环境/automated-assertions.log \
node scripts/acceptance/batch-b-assertions.mjs
```

最后一个输出行为 `SUMMARY total=19 pass=19 fail=0`。任一断言失败时进程退出码为 1，并打印 `FAIL` 行及实际值。

## 覆盖的断言

| 执行项 | 断言 |
|---|---|
| B01 | 商品可挂多个分类；同时选择两个分类只返回全部命中；只命中其一不返回；数据库关联数量正确 |
| B05 | 重复收藏返回首次时间；同一账户与商品唯一记录；取消再收藏仍一条且商品行不变 |
| B08 | 非卖方回复 403 `COMMENT_REPLY_NOT_ALLOWED`；作者删除后行保留、正文不再公开 |
| B10 | 发送推进本人已读；接收方产生未读；提交已读进度后归零 |
| B13 | 重复分类名 409 `CATEGORY_NAME_CONFLICT`；冲突后分类行不变 |
| B14 | 重复移除同一别名两次均 204，停用时间不变 |
| B17 | 交易中纠类成功且内容版本递增；交易行、约定与购买商品快照哈希不变 |
| B18 | 管理端曾关联计数与数据库一致 |

脚本会把日志追加到 `ACCEPTANCE_LOG`，便于登记到测试报告；日志只含断言结果与业务字段，不含密码或连接串。
