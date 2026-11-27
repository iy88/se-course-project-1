# 性能与容量测试环境准备

记录时间：2026-11-27T14:00—15:05 +08:00。

## 代码与产物

| 项目 | 实际值 |
|---|---|
| 压测运行时工作树 | 从 `main` `41bc161f` 派生，包含本分支尚未提交的 seed、loadtest 和前后端改动 |
| 收尾基线 | 压测完成后本地分支快进到 `main` `429bb3d1`；`41bc161f..429bb3d1` 只新增 Batch D 文档与截图，不涉及后端或 loadtest 代码 |
| 后端 JAR | `backend-app-0.0.1-SNAPSHOT.jar`；SHA-256 `125d57f4d7cf6fbcc03a32900c112818e3b4898d18ff0f47fa4dfe02afe1ee26` |
| 维护 JAR | `maintenance-0.0.1-SNAPSHOT.jar`；SHA-256 `bf36dc15968ae6fe9dcbbcf822463f7e6c6782f88d9919b6ca87cd9932cd4b7b` |
| 压测驱动 | `loadtest/target/release/campus-loadtest` 0.1.0；SHA-256 `8f32db78418de9d033db0086416418bc9d5e6889e49eec17d885a5633745906f` |
| Java | OpenJDK 27.0.1.1 |
| 驱动单测 | `cargo test --locked --manifest-path loadtest/Cargo.toml`：29/29 通过 |

后端 JAR 使用可复现构建时间，文件系统时间固定为 1980-02-01，不能据此判断构建时刻；以摘要和报告参数为准。

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
