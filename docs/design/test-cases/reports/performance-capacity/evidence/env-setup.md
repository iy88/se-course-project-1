# 性能与容量测试环境准备

记录时间：2026-11-27T14:00—16:07 +08:00。

## 代码与产物

| 项目 | 实际值 |
|---|---|
| 干净复跑基线 | PR 提交 `93f612b7f9963b919cc45a473cb60ad2de97f664`；从该提交建立独立 detached worktree `/private/tmp/p1-pr178-clean`，不携带其他未提交改动 |
| 后端 JAR（P-RUN-01） | `backend-app-0.0.1-SNAPSHOT.jar`；SHA-256 `12b22171026b22ccc387927a17bacac90611f952b80edbbd2e4c13d1fedb13fd` |
| 维护 JAR | `maintenance-0.0.1-SNAPSHOT.jar`；SHA-256 `2e81331c41232cf33c0e1af40470906ae5f7c59dc4a4560640139873df82aae5` |
| 压测驱动（P-RUN-01） | `loadtest/target/release/campus-loadtest` 0.1.0；SHA-256 `5551b87ccb064f0976ed98b1c06e13d9ba66f1038d7670fe995331c7933c2d2a` |
| 容量档驱动（P-RUN-02／03） | 初审前驱动；SHA-256 `8f32db78418de9d033db0086416418bc9d5e6889e49eec17d885a5633745906f` |
| Java | OpenJDK 27.0.1.1 |
| 自动化测试 | loadtest 31/31；file-storage 17/17；backend-app 上下文 7/7；Clippy 无 warning |

后端 JAR 使用可复现构建时间，文件系统时间固定为 1980-02-01，不能据此判断构建时刻；以摘要和报告参数为准。

## 版本对应与未混入改动

初审指出，首次 P-RUN-01 使用的后端 JAR 来自含其他未提交改动的开发工作树。该 JAR 的旧摘要为 `125d57f4…`，额外后端源码改动集中在案件公开聚合结果：

- 删除 `CaseResultController` 与跨事项 `CaseQueries.results`；
- 调整案件详情公开字段及相关案件测试。

这些文件不属于压测驱动的登录、商品、交易、上传、会话或实时 WebSocket 路径。为同时覆盖复审要求和实测中发现的问题，最终 P-RUN-01 基于 `93f612b7` 重建并完整复跑，该提交包含：

- 从发送 POST 前计时、到接收方正文 HTTP 回读完成才结束的 `im_delivery` 口径；
- WS hint 早到时冻结正文回读完成时刻，发送响应返回后再核对 ID／seq／body；
- bucket ACL／versioning 只由部署依赖探针校验，上传授权、完成核验和清理不重复查询；
- 上传控制器复用进程级 OSS 客户端，避免高并发下每请求创建／销毁 SDK 客户端。

容量档 P-RUN-02／03 仍保留首次实验数据，实际被测后端 JAR 为旧摘要 `125d57f4…`，驱动也是最终竞态和计时修复前的版本；因此 P-RUN-02／03 只作 Single Search 与横向扩容观察，IM 容量档为历史相对边界，不用于最终送达结论或完整客户端验收。

## 主机与依赖

| 项目 | 实际值 |
|---|---|
| 主机 | Apple M5 Pro，18 逻辑 CPU，64 GiB RAM，macOS 27.2.1 arm64 |
| PostgreSQL | 18.7，每轮使用 `mktemp` 隔离数据目录和随机 loopback 端口 |
| Redis | 8.10.3，随机 loopback 端口和随机命名空间，无持久化 |
| OSS | 阿里云真实私有 Bucket，使用随机 `project1/seed-test/.../load` 前缀；凭据只存在私有 env |
| nginx | 1.31.8，单 worker；API 和 WebSocket 使用两个独立 upstream |
| 网络 | 驱动、API、WS、数据库、Redis、nginx 均同机 loopback；OSS 为真实远端 |
| SMTP | 不在本次读写与 IM 操作配比中，未用于该案例 |

## 数据与隔离

- `maintenance.jar seed load` 生成 101 个账户（1 manager + 100 普通用户）、10,000 个商品、9,900 个浏览池商品、100 个交易对和 100 个私聊会话。
- 每个场景开始前从同一 PostgreSQL seed 快照恢复，并清空临时 Redis DB；避免上一容量档位的数据累积影响下一档。
- OSS 写入、seed 完成和删除均通过维护工具与私有前置检查核对；最终确认随机前缀为空后删除临时 PostgreSQL、Redis、manifest、nginx 和 JVM。
- `.env`、manifest、Cookie、CSRF、OSS 凭据和签名 URL 未进入证据目录。
- 部署依赖探针负责一次性核验私有桶和版本控制状态；业务请求路径不再重复查询 Bucket ACL／versioning。

## 服务拓扑

每一档按以下角色启动，实例数随场景变化：

| 角色 | Profile／路由 | 说明 |
|---|---|---|
| scheduler | `delivery-scheduler` | 固定 1 个，无 HTTP 监听 |
| delivery worker | `delivery-worker` | 1 或 2 个，无 HTTP 监听 |
| API 池 | 默认 infrastructure profile | nginx `least_conn`，仅承载普通 `/api/v1` |
| WS 池 | 默认 infrastructure profile | 独立 nginx upstream，仅承载 `/api/v1/realtime` |
| 数据库／Redis | 共享 | 所有实例连接同一隔离数据库和 Redis 命名空间 |

当前代码没有独立 `delivery-api`／`delivery-realtime` profile，HTTP 与 WS 进程来自同一 infrastructure 镜像；本实验通过两个 nginx upstream 将流量分池，未修改应用源码制造虚假角色。

## 最终清理

- 所有临时 JVM、scheduler、worker、nginx、Redis 和 PostgreSQL 已停止。
- OSS 随机前缀经预览、确认删除和二次空前缀检查。
- 临时目录已删除；`/private/tmp` 中无本次 `p1-seed-lab.*` 残留。
