<!--
Version: 0.1.1
Version-Datetime: 2026-11-07T01:34:48+08:00
-->

# 部署资产（需管理员安装，不由 Jenkins 自动安装）

本目录提供 issue #36 最终队列选型的仓库部署资产。系统服务、Nginx、sudoers 与备份脚本仍由服务器管理员安装；流水线只上传 release、执行迁移、preflight、真实队列门禁与激活脚本。生产主机地址、域名、账号和凭据不写入仓库。

## 资产

| 路径 | 用途 |
|---|---|
| `systemd/se-course-project1-backend.service` | 旧 combined 单进程服务，兼容回退 |
| `systemd/se-course-project1-api.service` | API 角色，监听 8001 |
| `systemd/se-course-project1-ws.service` | WS 角色，监听 8002 |
| `systemd/se-course-project1-worker.service` | Taskiq worker（outbox/超时/retention/幂等清理） |
| `systemd/se-course-project1-scheduler.service` | 单实例 Taskiq scheduler（静态 schedule + Redis 延迟重试源） |
| `systemd/se-course-project1-jobs.service` | 旧 3 角色 release 的过渡/回退 jobs 入口 |
| `nginx/se-course-project1-http.conf` | http 层的 map/upstream |
| `nginx/se-course-project1-routes.conf` | 合入既有 server 的 API/WS location |
| `sudoers/se-course-project1-activate.sudoers` | 固定 unit start/stop 与备份的受限 sudo |
| `preflight.py` | 按 combined/split 目标校验配置、预算、连接 |
| `activate.py` | 成套激活、真实/受控 readiness、失败回退与 ACTIVATED 记录 |
| `tests/` | fake systemctl/health 的激活、身份、preflight、sudoers 测试 |

所有模板中的路径、端口和 service 名称需按现场实际值核对。不要把生产配置复制进仓库；`activate.py`/`preflight.py` 从 release 内 `.env.prod` 读取配置。worker/scheduler 的框架参数全部来自 dotenv，systemd 不展开 secrets，也不重复 `--workers/--max-async-tasks/...`。

## 一次性管理员安装

先预览并备份现有 systemd unit、sudoers 与 Nginx 配置，再执行：

```bash
install -m 0644 deploy/systemd/se-course-project1-backend.service /etc/systemd/system/
install -m 0644 deploy/systemd/se-course-project1-api.service /etc/systemd/system/
install -m 0644 deploy/systemd/se-course-project1-ws.service /etc/systemd/system/
install -m 0644 deploy/systemd/se-course-project1-worker.service /etc/systemd/system/
install -m 0644 deploy/systemd/se-course-project1-scheduler.service /etc/systemd/system/
# Only needed for rollback to the transitional 3-role release:
install -m 0644 deploy/systemd/se-course-project1-jobs.service /etc/systemd/system/
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/se-course-project1-*.service

install -m 0755 deploy/activate.py /usr/local/sbin/se-course-project1-activate
install -m 0755 deploy/preflight.py /usr/local/sbin/se-course-project1-preflight
install -m 0440 deploy/sudoers/se-course-project1-activate.sudoers /etc/sudoers.d/
visudo -cf /etc/sudoers.d/se-course-project1-activate.sudoers

# The activation script runs as deploy (not root). It may only elevate the
# exact systemctl start/stop commands listed in the sudoers template; it never
# executes release-owned Python or test hooks as root.

# http 层配置可放 conf.d；routes 只能 include 到既有 server 内。
install -m 0644 deploy/nginx/se-course-project1-http.conf /etc/nginx/conf.d/se-course-project1-http.conf
install -m 0644 deploy/nginx/se-course-project1-routes.conf /etc/nginx/snippets/se-course-project1-routes.conf
# 在既有两个 frontend server 中替换旧 API/WS location 为：
# include /etc/nginx/snippets/se-course-project1-routes.conf;
# 保留静态目录、SPA/PWA、TLS；维护窗口确认服务就绪后再启用。
nginx -t && systemctl reload nginx
```

系统 unit 设置 `APP_RUNTIME_ROLE`，与共享 `.env.prod` 中的业务配置分离；四个 split 角色读取同一 release 与同一 dotenv。`/usr/local/sbin` 中脚本以 root 所有，`deploy` 直接运行激活脚本；脚本只能对 sudoers 中逐条列出的固定 unit/action 调用 `sudo -n`，不获得任意 `systemctl`、shell 或 release Python 的 root 执行权。`--systemctl`/`--health-command` 仅为测试钩子，生产调用不使用。

## 新环境与日常发布

从零准备生产基础设施、Jenkins 依赖及凭据、配置四角色、手动发布和开放 Webhook 的完整顺序见[部署说明](../../docs/development/部署说明.md#从零部署)。新环境直接采用 API/WS/worker/scheduler，不要求先运行 combined；安装但不启动兼容 backend unit，供激活器在没有旧记录时执行停止检查。

发布流程保留 PostgreSQL/Redis 备份、迁移版本核对、PREPARED/MIGRATED 标记和真实 readiness。管理员单独维护 Nginx，服务就绪后加载 `/api/ → 8001`、`/ws → 8002` 路由并验证公网双向通信。日常升级成套停止旧服务、切换 current、启动四角色，不宣称零停机；scheduler 必须单实例。

激活失败时尝试恢复上一 release 及服务集合；没有旧版本的新环境无旧 release 可恢复。数据库、Redis 和 Nginx 不自动回滚。保留失败日志与标记，按备份及配置单独恢复，不伪造发布标记或覆盖已有 release 目录。

## 验证

```bash
backend/.venv/bin/python -m pytest -q scripts/deploy/tests
(cd backend && CI_REALTIME_APPROVED=1 CI_REALTIME_PG_ADMIN_URL=... CI_REALTIME_REDIS_MANAGED=1 \
  .venv/bin/python -m tests.integration_real.runner)  # 专用临时 PG/Redis
python3 scripts/deploy/preflight.py --mode split --connect  # 在生产 release 中执行
```

`activate.py --dry-run` 只打印命令，不切换 symlink、不启停服务；现场演练先在隔离测试机验证，不能以测试替身结果宣称生产已通过。

启用 webhook 前先准备服务、sudoers、Redis8.2+测试二进制及CI专用PG，并完成手动完整发布；Jenkins默认split，combined仅显式维护/回退选择。Jenkins agent需nginx语法校验器和Rust1.95+/Clippy。部署成功后由管理员enable四角色、disable旧backend的开机自启；回退combined时同步恢复Nginx与开机自启。

流水线保留SQLite业务验收门禁，迁移到真实PG/Redis四角色业务验收尚未完成；可靠性专项不等价完整业务验收，不能删除旧门禁后宣称迁移完成。配置迁移工具随deploy包携带，发布后以backend/.venv/bin/python deploy/migrate_runtime_env.py显式指定shared dotenv及shared私有备份目录运行，不自动迁移配置或重启生产。
