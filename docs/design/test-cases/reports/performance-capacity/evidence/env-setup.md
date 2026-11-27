# 性能与容量测试环境

被测源码 `2685182d3919e272e0f35fb387f174101c1e8bb8`。实验从独立干净 worktree 构建，所有运行共用以下产物。

| 产物 | SHA-256 |
|---|---|
| `backend-app-0.0.1-SNAPSHOT.jar` | `12b22171026b22ccc387927a17bacac90611f952b80edbbd2e4c13d1fedb13fd` |
| `maintenance-0.0.1-SNAPSHOT.jar` | `2e81331c41232cf33c0e1af40470906ae5f7c59dc4a4560640139873df82aae5` |
| `campus-loadtest` | `d177daa88bd61752c654e33a0a68cb38fabc04f98e6ac70f6ce2c84b2951971e` |

Apple M5 Pro，18 逻辑 CPU，64 GiB。OpenJDK 27、PostgreSQL 18.7、Redis 8.10.3、本机 nginx API／WS 独立 upstream；真实远端私有 OSS 使用本次实验的随机隔离前缀。容量矩阵每档恢复同一快照并清空临时 Redis。稳态复核独立初始化，使用同样的种子规模和角色拓扑。种子包括 100 普通用户、1 管理员、10,000 商品、100 个交易对和 100 个私聊会话。
