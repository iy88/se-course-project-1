<!--
Version: 0.1.0
Version-Datetime: 2026-11-26T16:33:00+08:00
-->

# [测试主验证][A] US-01／02／09 账户与商品生命周期

| 字段 | 内容 |
|---|---|
| 负责人 | 袁尚峰（`iy88`） |
| 审查人 | 金婉怡（`GALAXY-JIN`） |
| 分支 | `test/evidence-account-product-iy88` |
| 基线 | `main` 提交 `23d89def`；[执行测试项](https://github.com/iy88/se-course-project-1/blob/docs/test-case-alignment/docs/design/test-cases/执行测试项.md) |
| 人工执行项 | A01—A18 |
| 设计依据 | US-01／02／09 验收条件；ACC-IF、ACC-KD、PRD-IF、PRD-KD、FILE-IF、FILE-KD、R1、CASE-IF |

## 目标

从真实前端完成账户创建、邮箱验证、登录和商品生命周期。人工流程是主验证，按 A-RUN-01—03 连续覆盖 18 项；单元和集成测试用于补充。每个 RUN 开始前先写明对应用户故事、接口和关键设计依据。

## 执行范围

- US-01：A01—A06（注册、邮箱占用、登录退出、重置、改密换绑、封禁）。
- US-02：A07—A13（禁发范围、发布审核、编辑、撤回下架、重上架）。
- US-09：A14—A18（状态可见性、交易中、结束下架、历史权限）。

设计映射和原 TC 对照逐项见[执行测试项](https://github.com/iy88/se-course-project-1/blob/docs/test-case-alignment/docs/design/test-cases/执行测试项.md#批次-a账户与商品生命周期)。

## 真实环境

1. 使用 `backend/.env.dev` 的真实 PostgreSQL、Redis、OSS、SMTP。
2. 先运行 dependency probe，确认 OSS 写读删和真实邮件投递。
3. 启动 `python3 scripts/dev.py start --env-file=backend/.env.dev`。
4. 通过用户端注册卖方、两个买方和无关用户，从测试邮箱取得真实验证码；管理员用 maintenance CLI 创建。
5. 通过管理端建立分类，通过用户端上传真实图片和发布商品。

## 交付

- 一份 `reports/batch-a-account-product/测试报告.md`，按 A-RUN 记录 18 项。
- 真实页面截图、测试邮件、OSS 日志、关键 API／DB 核对和测试命令。
- 缺失的自动测试代码；单测可用 Mock，跨模块事务、并发和真实依赖用集成测试。
- 一个关联 Issue 和一个 Draft PR。

发现问题时单独提缺陷 Issue；修复用独立 PR。原失败证据保留，修复后在批次报告追加复测。

## 完成标准

- [ ] A01—A18 每项在表格中先列设计依据。
- [ ] 账户均由前端和真实 SMTP 验证创建，商品图片走真实 OSS。
- [ ] A-RUN-01—03 页面主流程、状态和权限实际观察完成。
- [ ] 自动测试作为补充，Mock 使用范围与真实依赖边界写清。
- [ ] 批次报告、证据和缺陷／复测记录完整，请求 `GALAXY-JIN` 审查。
