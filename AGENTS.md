<!--
Version: 0.2.12
Version-Datetime: 2026-11-19T17:12:17+08:00
-->

# Project1 实现协作规范

## 任务与变更边界

- Before starting implementation, list the planned deliverables and verification steps in the conversation. Check the list against the request and the phase requirements for omissions.

- 开工前核对工作区、分支和任务 Issue。以最新 `main` 中的已确认需求、接口和业务规则为实现依据，从 [README](README.md) 查阅项目入口和操作命令。
- 按任务 Issue 约定的范围和分支实施。涉及需求、共享契约、模块归属、迁移或依赖的变更时，先核对受影响的调用方，需要业务或架构决策时向用户确认。
- 业务模块维护各自拥有的状态。跨模块用例按公共约定处理资格、事务、锁、幂等、审计和事件。由所属模块集中实现可推导规则，数据库约束承载必要不变量。
- 配置变更同步样例。凭据留在对应环境，日志、提交和交接记录使用脱敏信息。
- Reuse existing frameworks and mature third-party libraries in frontend and backend code. Keep project code focused on business rules and integration.
- Limit UI and API copy to actions, results, and errors. Use layout, controls, and essential labels to guide users.
- Write code comments in English when a contract, constraint, or implementation choice needs explanation. Keep comments and documentation concise and factual.

## GitHub 协作

- 新实现分支以最新 `main` 为基础，PR 默认指向 `main`。按 Issue 约定复用分支和 Draft PR，分多个单一职责 commit 交付。
- 推送前核对 Git 远端，推送后核对远端提交，再更新 Issue／PR 中的版本和证据链接。提交、推送、发布、合并及部署按相应授权执行。
- 金婉怡、孙含佳和张新悦的 PR 请求袁尚峰（`iy88`）审查。公共契约交由金婉怡交叉复核。部署、服务器、迁移执行及回退由袁尚峰负责。
- Issue 和 PR 使用原生状态和任务清单跟踪进度。正文直接记录修改、影响、验证结果与证据。

<a id="工作中的基线变更传播与交接强制"></a>

## 验证与交接

- 开发阶段优先单元测试，业务链路以人工前后端联合验证为主，按需补充集成测试。数据库并发用真实 PostgreSQL 多连接验证。系统测试和验收在开发完成后进行。
- 本地联调沿用任务约定的环境配置。记录实际运行的环境、命令和结果，区分模拟依赖与真实依赖的验证。提交前执行受影响的检查。
- 变更相关文档时同步源文件、生成物和引用。已有版本元数据的文档在提交时登记版本和实际带时区时间。
- 交接记录包含输入版本、改动、实际验证、跨模块影响及后续条件。协作修改时保留他人现有工作。
