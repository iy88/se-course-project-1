<!--
Version: 0.1.4
Version-Datetime: 2026-11-18T20:13:23+08:00
-->

# ADR-010 RESTful 契约与技术栈

| 字段 | 内容 |
|---|---|
| 编号/标题 | ADR-010 RESTful 契约与技术栈 |
| 协作入口 | [任务 Issue](https://github.com/iy88/se-course-project-1/issues/38) |
| 背景 | FR-01—FR-14；独立前端与类型检查。 关联 Q：按实际问题登记。 |
| 比较 | 见下表可行方案及影响 |
| 决定 | RESTful、snake_case、字符串对外 ID、整数分及 UTC 时间；后端技术映射见本 ADR 的 Spring Data JPA 与 PostgreSQL 决定；Vue 3／TypeScript／Rsbuild（Rspack）；Oxlint／Oxfmt；Axios XHR 请求与 OpenAPI 类型生成；所选后端技术栈的严格类型与静态检查。 |
| 理由 | 公共语义支持独立模块及前端细化，静态检查与白盒审查衔接。 |
| 代价 | 需要维护接口与模型映射、错误码和版本兼容。 |
| 验证 | 类型及契约检查，复杂业务链及输入边界运行验证。 预期由对应任务的实际审查人核验，执行版本、环境、命令和结果在任务证据中登记。 结果位置随任务证据登记。 |
| 确认 | 本会话已明确采纳；确认姓名：袁尚峰；实际确认日期按会话记录登记，整理日期2026-11-13；交叉复核姓名及日期待登记。 |
| 重新评估条件 | 语言框架、客户端或契约范围变化。 |
| 替代关系 | 首次登记；后续替代关联新旧 ADR |

## 可行方案比较

| 方案 | 收益与代价 |
|---|---|
| 方案 A | 各模块独立定义字段和错误，初始自由，增加对接差异 |
| 方案 B | 统一 RESTful、数据表示和类型契约，模块专注业务字段 |

持久模型与外部传输模型分别定义，配合静态及运行验证。

## 2026-11-17 应用技术栈边界调整

袁尚峰要求在Python／Java之间完成选择前采用技术栈独立的应用架构。保留既有协议、前端与基础设施决定；原Python框架和工具作为候选映射，后端语言及框架在编码阶段准入前完成选型，候选为Python与Java；选型结果在本ADR后续决定中记录，并同步实现计划、工具链与部署材料。原Python候选映射包括FastAPI、Pydantic、SQLAlchemy、Alembic、Taskiq、Pyright及Ruff。端口与事务、锁序、幂等、事件及任务语义采用[统一说明](../../architecture/07-技术栈独立的应用架构.md)。

## Spring Data JPA 与 PostgreSQL

袁尚峰于 2026-11-18 确认采用 Spring Boot 4.1.2、Maven、Spring Data JPA 和 Hibernate ORM 的方案。通过 `spring-boot-starter-data-jpa` 引入持久层，Hibernate 采用 Spring Boot 管理的 `7.4.13.Final`。OpenJDK 27 为本轮兼容性验证基线。生产继续采用 [ADR-011](ADR-011-单机多实例CI-CD.md) 的 Jenkins 发布、systemd 进程和 Nginx 流量切换。

| 场景 | 实现约定 |
|---|---|
| 常规实体读写 | JPA 实体及 Spring Data Repository。对外 DTO 由用例所需字段组装，关闭 `spring.jpa.open-in-view`。 |
| 锁序与 PostgreSQL 专用操作 | 在公共用例事务中采用原生查询或同数据源的 `JdbcTemplate`，明确控制取锁、重查及写入时机。SQL 需要读取未落库的实体修改时，在已审查的步骤显式 flush。 |
| 跨模块原子性 | 用例通过 Spring 事务管理统一提交或回滚。锁序、幂等、主体变更、审计和待投递事件采用[公共事务契约](../../detailed-design/key-designs/公共事务与权限.md)。 |
| 表结构与迁移 | Flyway SQL 维护表、主外键、部分唯一索引和业务约束；Hibernate 使用 `ddl-auto=validate` 核对现有表结构。 |

实测采用 macOS arm64、Homebrew OpenJDK 27.0.1.1、Maven 3.10.1、Spring Boot 4.1.2、Hibernate 7.4.13.Final 和本地临时 PostgreSQL 18.7。独立探针执行 `mvn verify`，通过实体写入、JPA 悲观写锁、显式 flush 后 JDBC 读取、同事务回滚 JPA 修改及 JDBC 事件写入。Hibernate 7.4 [官方兼容表](https://hibernate.org/orm/releases/7.4/#compatibility)列至 Java 26。目标 Linux JDK、Jenkins 和真实多连接竞争列入 S1 环境及集成核验，实测结果随对应版本登记。

## Vue 3、Rsbuild 与 Oxc

袁尚峰于 2026-11-18 确认采用 Rsbuild + Oxc，并以 Axios 作为前端 XHR 客户端。用户端与管理端分别采用 Vue 3、TypeScript 和 Rsbuild 的官方 Vue 插件，独立维护开发服务和构建入口。共享 API 类型根据同一份 OpenAPI 契约生成。用户端以移动布局为主，复用同一路由与功能适配桌面。管理端面向桌面。

从 [Rsbuild 官方脚手架](https://rsbuild.rs/guide/start/quick-start)的 `vue-ts` 模板分别生成两个应用。在仓库的前端目录执行以下命令。

```bash
npx -y create-rsbuild@latest user-web --template vue-ts --no-git
npx -y create-rsbuild@latest admin-web --template vue-ts --no-git
```

首次生成时在实现 PR 登记 CLI、模板、Node.js 和包管理器版本，提交依赖清单与锁文件。CI 用锁文件安装依赖。两个应用共用前端的 Oxlint 与 Oxfmt 配置，分别运行 `vue-tsc` 与 Rsbuild 构建。Oxlint 检查 JavaScript、TypeScript 和 Vue 单文件组件的脚本，Oxfmt 检查格式，Vue 模板中的类型由 `vue-tsc` 检查。Vue 模板 lint 规则当前超出 Oxlint 的支持范围。见 [Oxc 兼容性说明](https://oxc.rs/compatibility.html)。

两个浏览器应用使用共享的 [Axios 实例封装](https://axios-http.com/docs/instance)，配置 `adapter: 'xhr'`，使用同源 `/api/v1` 及统一错误处理。袁尚峰于 2026-11-18 确认开发由 Rsbuild 代理，生产由 Nginx 反代，后端 HTTP 安全入口集中校验 Origin 和 CSRF，规则见[共享接口约定](../../detailed-design/02-共享接口约定.md#身份与权限)。已登录写请求由 Axios 从 `__Host-se_csrf` 读取并通过 `X-CSRF-Token` 传送。公开账户入口使用入口接口返回的 Token，该请求显式发送入口 Token 并关闭 Session Cookie 到 CSRF 请求头的自动填充。OSS 预签名直传使用独立请求配置，发送签名要求的请求方法和头字段，站内认证、CSRF 和幂等拦截器仅绑定站内 API 实例。

macOS arm64 临时探针使用 Node.js 26.12.1、npm 12.2.1 和 create-rsbuild 2.3.3，生成并安装 Vue 3.5.45、Rsbuild 2.3.3、Axios 1.21.1、Oxlint 1.94.0、Oxfmt 0.79.0。示例源码通过 Oxlint、Oxfmt 格式检查及 `npm run build`（`vue-tsc` 与 Rsbuild）。Axios 的 XHR 配置在 Node.js 中完成实例构造检查。浏览器 XHR、会话、CSRF、双应用共享配置和目标 Linux 工具链随 S1 骨架验证。
