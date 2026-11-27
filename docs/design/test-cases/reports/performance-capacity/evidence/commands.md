# 性能测试过程与命令

以下命令使用占位变量；真实端口、数据库名和 OSS 前缀由隔离实验室随机生成，凭据只从私有 env 读取。

## 1. 隔离依赖与种子

1. `initdb` 创建临时 PostgreSQL 18.7；`redis-server` 启动无持久化临时实例。
2. 使用维护工具预览并确认 `db reset`，将 schema 迁移到 29 条 Flyway migration。
3. 检查随机 OSS 前缀为空后执行：

```bash
java -jar backend/maintenance/target/maintenance-0.0.1-SNAPSHOT.jar \
  seed load --env-file="$LOAD_ENV" --manifest="$MANIFEST" --prepare-reset
```

4. 验证 100 用户、10,000 商品和 OSS 对象存在，再创建 `seed_load_snapshot` 数据库模板。后续每档均从该模板恢复，避免容量档位之间写数据累积。

## 2. 服务与分流

```bash
java -jar backend/backend-app/target/backend-app-0.0.1-SNAPSHOT.jar \
  --env-file="$LOAD_ENV" --spring.profiles.active=delivery-scheduler

java -jar backend/backend-app/target/backend-app-0.0.1-SNAPSHOT.jar \
  --env-file="$LOAD_ENV" --spring.profiles.active=delivery-worker

java -jar backend/backend-app/target/backend-app-0.0.1-SNAPSHOT.jar \
  --env-file="$LOAD_ENV" --server.port="$API_PORT_1" \
  --project1.http.allowed-origins="$HTTP_ORIGIN"
```

API 和 WS 实例使用相同 infrastructure profile；分别启动 N 个后，nginx 配置两个 `least_conn` upstream：

```nginx
upstream api_pool {
  least_conn;
  server 127.0.0.1:<api-1>;
  # ...
  keepalive 64;
}

upstream ws_pool {
  least_conn;
  server 127.0.0.1:<ws-1>;
  # ...
  keepalive 64;
}
```

普通 HTTP server 只 `proxy_pass http://api_pool`；WS server 保留 `Upgrade`／`Connection` 并 `proxy_pass http://ws_pool`。

## 3. 驱动命令

正式默认容量：

```bash
./loadtest/target/release/campus-loadtest \
  --mode capacity \
  --base-url "$API_ORIGIN" \
  --ws-base-url "$WS_ORIGIN" \
  --manifest "$MANIFEST" \
  --users 100 \
  --output "$RESULT"
```

默认参数为 Single Search：起点 200、上限 400 HTTP RPS、5 秒预热、30 秒阶段、300 秒验证、12 次 refine、1 RPS 精度、2,048 in-flight、100 ms 最大调度滞后、零错误预算。

正式上限探查示例：

```bash
./loadtest/target/release/campus-loadtest \
  --mode capacity --capacity-case single --single-operation search \
  --base-url "$API_ORIGIN" --ws-base-url "$WS_ORIGIN" \
  --manifest "$MANIFEST" --users 100 \
  --capacity-start-rate 600 --capacity-max-rate 600 \
  --capacity-stage-seconds 20 --capacity-warmup-seconds 5 \
  --capacity-validation-seconds 20 --capacity-refinements 0 \
  --capacity-max-in-flight 8192 --capacity-max-lag-ms 500 \
  --output "$RESULT"
```

IM 使用 `--single-operation im`，mixed 使用 `--capacity-case mixed`。正式容量报告使用 300 秒验证；上限档只做 20 秒短窗，以首次明显积压、超时、错误或延迟陡增确定边界，不宣称长期 SLA。

## 4. 观测与清理

- 通过 `ps -p <pids> -o pid=,pcpu=,rss=` 采样进程 CPU／RSS。
- 通过 PostgreSQL `pg_stat_activity`、`pg_locks`、`user_event` 统计活动连接、锁和未发布事件。
- 通过 Redis `XLEN`、`XPENDING` 统计 event stream、work stream 与 worker pending。
- 通过 nginx access log 核对各 upstream 请求数和 WebSocket 101 绑定分布。
- 场景结束后停止 JVM／nginx，从数据库模板恢复并清空 Redis。
- 全套结束后停止临时依赖，预览并确认删除 OSS 前缀，二次检查为空后删除私有 manifest 和临时目录。
