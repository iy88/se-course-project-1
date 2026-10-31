<!--
Version: 0.1.35
Version-Datetime: 2026-10-31T11:10:47+08:00
-->

# 校园二手交易与物品流转平台

## llm-test-only 分支说明

本分支保留后端 `backend/`、桌面管理端 `frontend/admin/` 和移动PWA `frontend/mobile/` 的开发实现，运行期数据位于被忽略的 `var/`。开发决策与运行入口见[开发阶段技术决策](bits/开发阶段技术决策.md)。

2026-10-28同步需求主线 `c4ee232`，A／B报告均已确认。随后按合并后的需求开展三端实现对齐、隔离副本并行开发和多轮代码审查；需求对应实现、修复轮次及实际验证结果见[需求同步并行修改计划](bits/需求同步并行修改计划.md)。历史测试及人工核验仅代表各自记录的范围，本轮自动化回归不替代系统人工验收。下文需求阶段范围约束适用于需求材料维护。

本目录保存校园二手交易与物品流转平台的需求分析交付材料。全部14个主用例、14个用户故事及16个领域类均有独立详细文档。01—08按顺序构成需求规格说明书正文，详细材料以各目录索引为入口；正文详细展开关键US、UC、类及SC并展示关键图。需求正文及US／UC／SC／领域类分析已于2026-10-23获项目负责人确认，BR／TR已讨论接受；确认范围见[需求基线](docs/requirements/08-需求基线.md)。

## 开发设计与接入计划

测试与浏览器复核按同一份 UC/US/SC 清单、角色和预期执行；HTTP 自动化与浏览器是不同执行通道，结果分别记录。数据库、存储与 KV 后端由选定 dotenv 文件明确配置，同一测试和 seed 命令适用，不使用 `--profile`。自动化 seed、数据库、存储及 Redis 资源按本轮隔离；浏览器人工登录使用部署初始化保留的管理员及单独注册的测试用户，不依赖自动化临时身份。SMTP 服务商配置和真实收件箱投递、生产迁移、生产资源配置、多实例广播和备份恢复演练仍未验证。步骤与结果模板见[浏览器交互验收清单](docs/development/浏览器交互验收清单.md)。

ORM模型和业务查询采用SQLModel，数据库引擎与迁移保留必要SQLAlchemy基础设施。图片使用OSS Python SDK V2的短期上传租约：前端直传，后端核对SHA256、元信息、大小与真实图片后确认引用；本地存储使用相同租约API。依赖版本对比见[直接依赖版本审计](docs/development/依赖版本审计.md)。

人工演示使用 `(cd backend && .venv/bin/python -m app.manage demo-seed --env-file .env.dev)`，向所选环境持久添加演示账号、图片和业务记录，沿用配置的数据库 schema 与存储资源。先对同一环境执行 `migrate`；账号清单、场景入口与 US／UC／SC 演示步骤见 [Demo seed](docs/development/demo-seed.md)。

## 项目运行与配置

### 环境与目录

本节适用于 `llm-test-only` 分支的开发实现。准备 Python 3.12及以上、uv、Node.js 22及以上及npm；Python依赖由 [uv.lock](backend/uv.lock) 固定，两个前端分别使用各自的 `package-lock.json`。优先使用下方统一后台入口；手动启动备选方案需要三个独立终端。

| 服务／数据 | 位置 | 本地地址／用途 |
|---|---|---|
| FastAPI后端 | `backend/` | `http://127.0.0.1:8000`；业务API前缀 `/api/v1` |
| 移动用户端 | `frontend/mobile/` | `http://localhost:5173`；移动布局及PWA |
| 桌面管理端 | `frontend/admin/` | `http://localhost:5174`；审核、共享处理池及管理处置 |
| 数据库 | 所选环境文件配置 | SQLite 或 PostgreSQL，结构使用显式迁移 |
| 图片存储 | 所选环境文件配置 | local 或 OSS；local 经后端 HMAC 签名入口读取，OSS 使用私有桶短期签名 GET 直链 |

`var/`、`.env.dev`、`.env.prod`、虚拟环境、`node_modules/`及构建目录均由 Git 忽略。保留已有数据库和图片目录即可保留业务数据，不需要为升级删除数据库；生产配置不得提交。

### 人工测试环境重置

在 `backend/` 目录运行 `.venv/bin/python -m app.devtools.reset` 预览目标；实际执行使用 `.venv/bin/python -m app.devtools.reset --execute --confirm <数据库名>`。执行前先停止后端和所有测试进程，并确认不需要保留本轮人工测试数据。

此命令仅接受 `.env.dev` 的 dev/test PostgreSQL、Redis 和 OSS 配置。删除应用 schema 内的全部表（含管理员、业务数据与审计），保留 schema 及其默认授权，再执行正式迁移；Redis 只删除 `REDIS_KEY_PREFIX` 下的键；OSS 删除媒体桶和证据桶中 `STORAGE_KEY_PREFIX` 下的当前对象，不删除桶，也不清除版本历史或未完成的分片上传。两个前缀必须非空，资源须与生产隔离。先前存放在其他前缀的对象不会被清理。

重置后运行 `.venv/bin/python -m app.manage seed` 重新初始化管理员及指定分类，并清除浏览器原有登录状态后重新登录。跨服务操作没有整体事务；失败时查看完整异常，修复原因后重跑。命令不会自动恢复备份。

### 后端配置

配置定义见 [config.py](backend/app/core/config.py)。应用设置只从选定的 dotenv 文件读取；操作系统环境中仅 `APP_ENV_FILE` 用于选择文件，其他继承的配置变量不覆盖文件内容。默认读取 `backend/.env.dev`，不受启动 cwd 影响。修改后重启后端。

从对应配置示例创建本地文件，在 `backend/` 目录执行：

```bash
cp -n .env.dev.example .env.dev
cp -n .env.prod.example .env.prod
chmod 600 .env.dev .env.prod
```

模板只使用 `REPLACE_*` 占位符，不写真实库名、角色名、bucket、AK 或密码。负责人自行填入 test/prod 值；不要把 test 文件原样当生产配置。示例中的关键项：

```dotenv
ENVIRONMENT=dev
DATABASE_SCHEMA=app
DATABASE_URL=postgresql+asyncpg://REPLACE_APP_DB_USER:REPLACE_URL_ENCODED_PASSWORD@127.0.0.1:5432/REPLACE_DATABASE_NAME
MIGRATION_DATABASE_URL=postgresql+asyncpg://REPLACE_MIGRATION_DB_USER:REPLACE_URL_ENCODED_PASSWORD@127.0.0.1:5432/REPLACE_DATABASE_NAME
MIGRATION_OWNER_ROLE=REPLACE_DB_OWNER_ROLE
DB_AUTO_CREATE=false
OSS_REGION=REPLACE_OSS_REGION
OSS_ENDPOINT=https://REPLACE_OSS_ENDPOINT
OSS_MEDIA_BUCKET=REPLACE_MEDIA_BUCKET
OSS_EVIDENCE_BUCKET=REPLACE_EVIDENCE_BUCKET
AUDIT_TRUSTED_PROXIES=none
```

| 配置 | 说明 |
|---|---|
| `APP_ENV_FILE` | 唯一文件选择器；默认 `backend/.env.dev`，显式指向 `.env.prod` 才运行生产 |
| `REDIS_URL` / `REDIS_KEY_PREFIX` | 配置URL时使用Redis且必须有非空前缀；两项均省略时使用内存KV |
| `ENVIRONMENT` | 必填：`dev`/`test`/`prod`；生产拒绝占位密钥及自动建表 |
| `DATABASE_SCHEMA` | 必填：常驻应用配置使用 `app`；自动化 runner 为每轮生成隔离 schema 并使用私有临时 dotenv 文件 |
| `DATABASE_URL` | 必填普通应用连接；PostgreSQL 使用 `postgresql+asyncpg`；SQLite 使用 `sqlite+aiosqlite` |
| `MIGRATION_DATABASE_URL` / `MIGRATION_OWNER_ROLE` | 只由独立迁移命令读取，不进入常驻服务配置 |
| `DB_AUTO_CREATE` | PostgreSQL 生产/集成必须为 false，结构由 `manage migrate` 建立；仅临时 SQLite 调试可 true |
| `OSS_*` / `STORAGE_LOCAL_ROOT` | 任一OSS资源字段存在时必须配齐并使用OSS；未配置OSS资源时须提供本地目录。失败不回退 |
| `OSS_*` | region、HTTPS endpoint、media/evidence 两个桶、单 RAM AK、超时与重试；缺字段只报告字段名 |
| `AUDIT_TRUSTED_PROXIES` | 必填：`none` 或逗号分隔的代理 IP/CIDR；只信任列出的直连代理转发头 |
| `SMTP_*` | 常规服务强制 SMTP；必填主机、端口、安全模式、账户、密码和寄件人，连接超时默认10秒 |
| `JWT_SECRET` / `FILE_URL_SECRET` | 分别生成至少 32 字节随机值；各环境均不得使用开发默认密钥或占位符 |

密码含 `@`、`:`、`/`、`#`、`%` 时只对 URL 用户名/密码部分做 percent-encoding，不在报告或日志打印连接串。可运行 `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` 分别生成两个密钥。

必填配置缺失、空白或格式不合法时，服务在启动阶段报出字段名并退出。主机、端口、API基址与超时等运行参数可使用代码中的普通默认值；数据库、存储、KV、密钥及审计代理策略必须由所选环境文件明确配置。业务自动化只保留一套全量验收入口。

注册、找回密码和换邮箱验证码通过配置的 SMTP 服务发送；正常接口响应不包含验证码，页面提示用户查收对应邮箱。启动前须在所选环境文件中填写真实邮件服务参数，未填写或使用占位值时服务启动失败。自动化验收将验证码写入私有临时 outbox 供测试读取，不连接真实 SMTP；真实收件箱投递仍须由人工按浏览器清单验证。

### 安装、初始化与启动

日常测试优先从仓库根目录使用统一入口：

```bash
./scripts/dev.sh start
# 修改后端代码后重启三端
./scripts/dev.sh restart
./scripts/dev.sh status
# 测试结束
./scripts/dev.sh stop
```

`start` 在后台运行后端8000、管理端5174、移动端5173；默认读取已有 `backend/.env.dev`，也可用 `APP_ENV_FILE` 选择其他 dotenv 文件。托管进程不会继承 shell 中的应用、前端或工具配置覆盖。脚本检查端口、执行 `uv sync --frozen`，前端缺少 Vite 时执行 `npm ci`；不会复制配置、启动 PostgreSQL/Redis、执行迁移或 seed。首次初始化和升级结构须先按下方命令显式迁移。锁文件变化后，先停止服务、在两个前端分别运行 `npm ci` 再启动，不能依赖脚本对已有 node_modules 自动重装。

`status` 只检查托管进程；未运行时返回1是正常的停止状态。日志见 `var/log/dev-services.log`，状态文件见 `var/run/dev-services.json`。启动准备可能超过5秒，先查看 status/日志，勿重复运行 start。一个服务退出时托管器停止其它服务；手动启动的进程不会由此入口接管或停止。不要同时使用后台与下方手动方案。

测试与 seed 使用选定 dotenv 文件中的数据库、存储与 KV 配置；自动化 runner 为每轮建立私有临时 dotenv 文件、随机 schema 和隔离身份，结束后清理本轮资源，不要求手工切换配置文件。浏览器人工流程使用持久化初始化的管理员和单独注册的用户；管理员及必要参考数据由独立 `app.manage seed` 初始化，不使用自动化 seed。自动化验证码通过私有临时 outbox 读取，不经过真实邮件服务；人工注册、找回密码和换邮箱须查收实际邮件。清理实现与复验状态见开发验收文档。

以下是初始化及手动启动备选方案。只需日常启动且数据库结构已更新时，直接使用上面的 `start`。

终端一：安装后端依赖并启动 API。首次或升级数据库结构时显式迁移。部署管理员和必要参考数据由持久化初始化命令准备；自动化 runner 自行准备并清理其临时身份与数据。

```bash
cd backend
uv sync --locked
uv run python -m app.manage migrate          # 显式执行数据库迁移
uv run python -m app.manage seed             # 持久化部署管理员及必要参考数据；密码交互输入
uv run python -m app.manage serve --host 127.0.0.1 --port 8000
```

迁移、seed、runner 和 pytest 命令使用所选 dotenv 文件指定的后端。验收报告记录实际配置目标，不把一种存储后端的结果表述成另一种后端的验证。

自动化与人工测试共享业务范围、角色和预期，但使用不同身份来源：自动化通过真实 HTTP 执行并清理本轮 seed；人工浏览器使用持久化初始化的管理员与注册用户。不要把自动化临时身份当作人工登录账号。

终端二：从仓库根目录启动桌面管理端。

```bash
cd frontend/admin
npm ci
npm run dev -- --strictPort
```

终端三：从仓库根目录启动移动用户端。

```bash
cd frontend/mobile
npm ci
npm run dev -- --strictPort
```

依赖已安装且锁文件未变化时，可直接运行各端启动命令。`--strictPort` 在指定端口被占用时直接报错，避免Vite自动改端口后访问错服务。前端当前不读取 `VITE_API_URL` 等环境变量，API统一使用同源 `/api/v1`，WebSocket使用同源 `/ws`；两端 [Vite配置](frontend/mobile/vite.config.js)及[管理端配置](frontend/admin/vite.config.js)将 `/api` 和 `/ws` 代理到本机8000端口。更换后端地址／端口时，同时修改两端代理目标并重启Vite。

后端启动后可检查：

```bash
curl http://127.0.0.1:8000/api/health
```

交互式API文档为 `http://127.0.0.1:8000/docs`，OpenAPI描述为 `/openapi.json`。管理端从共享池认领事项后处理；私人交易读取与处置须使用本人认领且真正关联的事项，不能把管理员登录或先前商品审核当作任意交易权限。

### 前端开发缓存与排错

两端 Vite 的依赖预构建缓存分别位于各自项目根目录：`frontend/admin/.vite/`、`frontend/mobile/.vite/`。该目录已被 `.gitignore` 忽略，不写入共享或重装的 `node_modules`。安装或更新依赖前先停止对应端的 Vite 开发服务，完成后重新启动；不要依赖旧开发服务继续使用重新安装前的预构建结果。若出现 `504 Outdated Optimize Dep`，停止并重新启动对应端 Vite。浏览器仍持有旧页面资源时，刷新当前页面即可更新该页缓存。

### 回归、构建与预览

业务测试只保留 `backend/tests/acceptance_real/` 一套完整验收。CLI与pytest调用同一个runner；后端由所选 dotenv 文件明确配置，不设另一套测试命令或 `--profile`。自动化与浏览器人工使用同一UC/US/SC业务范围、角色和预期；通道差异是自动化通过真实 HTTP、人工通过浏览器操作，人工结果不自动继承API结果。

```bash
# 后端目录，唯一全量业务测试；runner使用本轮私有临时dotenv配置
cd backend
RUN_REAL_ACCEPTANCE=1 .venv/bin/python -m pytest -q
# 同一runner的CLI入口，可指定专用服务端口/运行标识
.venv/bin/python -m tests.acceptance_real.runner --port 8107
```

runner自行准备本轮seed和隔离资源，启动专用测试服务，并在成功或失败时清理本轮数据库、存储和 Redis 数据；共享数据不得删除。最终全量与故障注入的资源清理已复验，结果见开发验收文档。退出码非0或存在FAIL/SKIP/PARTIAL/UNCOVERED均须查看报告。当前清单计数和执行状态见[整体验收](docs/development/整体验收.md)；浏览器清单维持独立 NOT-RUN，不继承 API 状态。

同一全量入口默认采集整个 `backend/app` 的代码行与分支覆盖率，并合并验收驱动和真实 API 子进程的数据。HTML、JSON、XML、文本报告保存在 `var/acceptance-real/code-coverage/`，具体路径和百分比写入本轮验收报告；代码覆盖率与路由、UC/US/SC 覆盖率分别记录。

lint、类型检查、文档构建检查和前端构建仍保留为工程检查，不另维护单元/专项测试套件：

```bash
(cd backend && uvx ruff check app tests alembic ../scripts)
python3 scripts/cli.py check
(cd frontend/mobile && npm run build)
(cd frontend/admin && npm run build)
```

构建产物分别位于 `frontend/mobile/dist/`、`frontend/admin/dist/`。本轮需求对齐后的自动化验证结果见[并行修改与审查计划](bits/需求同步并行修改计划.md)；最近一次真实开发环境 API 测试、补充数据与缺陷记录见[开发环境真实API测试与生命周期数据](bits/开发环境真实API测试与生命周期数据.md)。命令构建、真实 HTTP 测试通过与人工功能验收分别记录。

先启动后端，再在两个独立终端预览构建产物：

```bash
(cd frontend/mobile && npm run preview -- --port 4173 --strictPort)
```

```bash
(cd frontend/admin && npm run preview -- --port 4174 --strictPort)
```

当前锁定的 Vite 6 预览默认继承 `server.proxy`，两端预览的 `/api`、`/ws` 仍指向本机8000，可在本机联调；后端须另行启动，预览不创建测试数据，也不由 `dev.sh` 管理。正式托管静态产物时需自行配置 `/api` 的HTTP反向代理、`/ws` 的WebSocket升级，以及前端路由回退到 `index.html`。两端均使用根路径，宜用不同域名或端口提供各自根目录，不直接拼接到同一站点的任意子路径。移动端PWA的Service Worker由生产构建生成，安装与缓存需在HTTPS或localhost安全上下文验证；业务操作仍依赖在线API。

局域网手机访问时，可使用 `npm run dev -- --host 0.0.0.0 --strictPort`，手机访问开发机IP的5173端口；代理仍由开发机连接本机后端。普通局域网HTTP可用于页面联调，但不等于已满足PWA安装条件。

当前运行方案面向单进程开发：WebSocket连接管理在进程内；KV按所选配置使用进程内 memory 或 Redis。PostgreSQL、私有 OSS 双桶、环境隔离与审计曾在 test 目标接入；历史目标经验不代表现行 runner 清理策略已验证。生产迁移、生产资源配置、真实邮件、多实例广播及备份恢复演练仍未验证，不因静态构建或历史 test 结果就视为生产部署完成。

## 成员分工

需求成果确认已登记；当时34张图稿（含UC-03—UC-16独立用例图）已于2026-10-26由用户确认审阅通过；13张变化图稿及相关修订已于2026-10-26获用户确认；成员按实际完成的内容记录贡献，见 [A报告A.8](docs/需求分析质量验证报告.md#a8-成员贡献与人工责任)。

## 文件位置与命名

| 位置 | 存放内容与命名 |
|---|---|
| `docs/需求规格说明书.md` | 由01—08生成的整合需求规格说明书 |
| `docs/requirements/` | 01—08线性章节；关键材料从独立源文件展开 |
| `docs/appendices/user-stories/` | 14份详细用户故事、验收条件及类协作，入口 [用户故事索引](docs/appendices/user-stories/index.md)，与用例分开维护 |
| `docs/appendices/use-cases/` | 14份详细主用例、66项子用例及类协作，入口 [用例索引](docs/appendices/use-cases/index.md)；图仍放 models |
| `docs/appendices/scenarios/` | 12份独立详细场景，入口 [场景索引](docs/appendices/scenarios/index.md)；第05章保留总览及动态模型，第07章保留验收条件 |
| `docs/appendices/class-analysis/` | 详细类分析材料，入口 [类分析索引](docs/appendices/class-analysis/index.md)；图仍放 models |
| `docs/appendices/` | 附录及附件组织入口 [附录索引](docs/appendices/index.md)，引用现有材料，不复制另一套正文／证据 |
| `docs/需求分析质量验证报告.md` | A 报告，汇总确认、模型检查、最终验收 review 及问题复核记录 |
| `docs/AI智能体使用验证报告.md` | B 报告，汇总实质 AI 贡献、人工取舍、核验与证据索引 |
| `docs/appendices/models/` | 报告图（用例、活动、类、状态、上下文图等）的可编辑源文件目录，例如 `.puml`、`.mmd`；PNG 集中在 docs/appendices/rendered，不保存 SVG |
| `docs/appendices/rendered/` | `.puml`／`.mmd` 统一渲染的 PNG，入口 [渲染索引](docs/appendices/rendered/README.md) |
| `docs/appendices/evidence/` | 业务决定及讨论依据、实际形成的验证证据；入口 [证据索引](docs/appendices/evidence/index.md)，E 编号与 D 决定连续编号；编号重排时以 evidence 中映射表为准 |
| `docs/appendices/ai-usage/` | AI关键分析贡献、必要上下文及交互原文、人工取舍和核验、填写模板，索引见 [index.md](docs/appendices/ai-usage/index.md)，填写规则见 [AGENTS.md](AGENTS.md) |
| `docs/appendices/prototype/` | 按用户故事组织的多页 HTML 原型及 [说明](docs/appendices/prototype/README.md)，一个 HTML 文件一个页面，示例数据不代表后台功能实现 |
| `docs-pdf/` | 由Pandoc生成的PDF交付副本，保持docs的目录结构，文档链接使用PDF目标；该目录由Git忽略 |
| `scripts/` | [Python构建说明](scripts/README.md)：同步关键材料、生成说明书、渲染PNG，以及按SHA-256增量导出和检查PDF |
| `bits/` | 项目协作复盘及本分支开发阶段技术决策与运行指南；成员贡献、问题处理及需求边界分别见 A 报告与需求基线 |

文件按“编号-名称”组织；编号重排时同步更新文件名、索引及引用，需要的版本、日期按版本规范记录，需求确认事实集中登记在需求基线和证据中。正文通过相对链接及编号引用附件；尚未开展的工作不预填结果。

`docs/`中的交付材料只引用`docs/`内的本地文件，不引用仓库根AGENTS.md／README.md、bits、scripts或其他目录。必要决定、背景及依据保留在docs内，使交付材料能够独立阅读；历史引文中的文件名不作为现行依赖。脚本用法和仓库操作规范保留在docs外的指导文件中，工作笔记及仓库指导文件可以引用docs。

## 范围与验证约束

- 原型作为本项目需求分析交付材料，包含按用户故事组织的15个HTML页面。
- 场景分析与原型材料已成文；场景及原型走查由张新悦、孙含佳、金婉怡分别于 2026-10-23、2026-10-23、2026-10-25 完成（A.5.2—A.5.4、A.6.2—A.6.4、E-11—E-13）。图稿可读性记录按实际范围保留，系统运行验收在实现阶段开展。
- 多页 HTML 原型按用户故事组织界面示例，作为最终 review 的补充材料，不以静态页面证明后台功能已实现。
- 需求清单覆盖题目全部十项核心功能；14个主用例均有详细文档，主报告以交易闭环展开用户故事、场景和关键类，并展示三个代表性用例。
- 业务规则、术语及未决问题统一维护；性能目标按第 6 章登记的来源与状态表达，实测结论待系统实现后形成。教学模拟如实标注，AI 自检不能替代人工确认。
- 各成员仅记录 AI 对需求分析有实质影响的关键建议、人工取舍及证据，须有必要上下文并注明姓名；人工直接决定由 evidence 承载。实质分析开始时起草ai-usage，讨论中途保存关键prompt／output及实际反馈原文、来源定位与人工取舍；不要求完整聊天或环境、Git、一般文档维护流水，也不要求每次提交补档。构建与导出工具按用户明确要求专项记录于[AI-14](docs/appendices/ai-usage/AI-14-2026-10-23-文档构建与PDF增量导出.md)，不扩大日常维护的默认建档范围。开发阶段无需AI使用档案，开发决策与验证结果按代码、测试及必要技术笔记保留。详细边界见 AGENTS.md；B 报告由组长汇总。袁尚峰统筹最终review与汇总；三位成员已在各自设备和Git账号下完成走查及个人AI证据补充，实际贡献见A报告A.8。

## 图文件与索引规范

- 报告图可编辑源文件统一放在 `docs/appendices/models/`，PNG 集中在 `docs/appendices/rendered/`，不散落到章节目录；证据截图、原始资料仍放 `docs/appendices/evidence/`，原型材料放 `docs/appendices/prototype/`。
- 图文件采用“编号-名称”，例如 `ACT-02-交易请求与双方确认.puml`；图模型保留可编辑源文件，同名 PNG 集中到 `docs/appendices/rendered/`，不保存 SVG 导出图；多页 HTML 原型直接维护 HTML 页面。
- Markdown 正文以相对路径链接引用源文件，并可用图片语法展示 `docs/appendices/rendered/` 中已有的 PNG；图源与图片同步，不插入不存在的图片链接。
- [图索引](docs/appendices/models/index.md) 登记图编号、名称、源文件、正文位置、关联证据 evidence，以及可选关联项目／分析项；链接必须定位实际文件或条目。
- 不交付数据字典，不开展传统数据建模；保留领域类分析、职责、关联、状态和必要业务概念。不得据此省略业务规则、权限或隐私约束。

## 草稿与版本规范

- `bits/` 为 notes，不使用 `draft-` 前缀，去前缀不代表内容已验证；其余未确认的业务文档以 `draft-` 开头；确认后去除前缀并修订引用。README 及配置属于仓库运行规范，不作为业务确认稿。
- 仅 `docs/` 下的文件及各目录的 `README.md`、`AGENTS.md` 需要记录 `Version: x.y.z` 和带时区的 `Version-Datetime: ISO8601`。文本在原生注释或正文中记录；`docs/` 中的二进制文件使用同目录 `<文件名>.version` 伴随文件记录；渲染PNG的伴随文件仅保存源文件与PNG的SHA-256，不要求版本号与时间，DPI由生成脚本保证。其他文件（包括工具源码、测试、配置及未来业务代码）不需要版本信息，由 Git 历史追踪。
- 每次 commit 前对需要版本信息的修改文件按最终内容统一递增版本号、更新版本时间，并与上一提交比较；时间不得在未来。同一提交前的多轮修改不逐轮登记版本或保留未提交即放弃的中间方案。删除文件无需更新版本。
- 文档拆分、改名后同步修订引用。图源按最终提交内容管理版本。

## 提交前操作

完整的智能体工作与提交前检查规则统一见 [AGENTS.md](AGENTS.md)，适用于每次 commit 和 amend；提交前须检查需求／规则边界、跨文档一致性、历史遗留及实际目录与 README／索引同步；由用户明确指出 AI 使用模型及工作负责人，逐文件确认 diff、归属和更改。成员提交时同样按该检查清单核对；此处仅保留入口，不配置可执行 Git hook。

## 当前阶段工作入口

- [项目协作复盘与后续工作方法](bits/项目协作复盘与后续工作方法.md)：根据本人及组员Git历史，归纳基线漂移、共享材料合并、覆盖与模型语义、证据记录、图稿和导出等问题，说明后续任务的组织方法。具体执行规则统一见[AGENTS.md](AGENTS.md#工作中的基线变更传播与交接强制)。

- [需求基线](docs/requirements/08-需求基线.md)：指定需求范围、纳入版本与确认记录。
- [需求分析质量验证报告](docs/需求分析质量验证报告.md)：A.7 登记问题处理与复核，A.8 记录成员实际贡献；最终交付版本及日期见 A.1。

01—08及整合说明书已去除草稿前缀；附录文件名已去除 `draft-`，档案与证据的确认状态以正文记录为准。A报告已于2026-10-26经袁尚峰确认去除 `draft-`；B报告已于2026-10-27经袁尚峰确认去除 `draft-`，确认依据见 [AI-20](docs/appendices/ai-usage/AI-20-2026-10-27-报告结构优化与语义审阅.md)。变更纳入文件时同步更新基线版本表及影响记录。

## 报告入口

- [需求规格说明书](docs/需求规格说明书.md)
- [附录与附件索引](docs/appendices/index.md)
- [需求分析质量验证报告](docs/需求分析质量验证报告.md)
- [AI 智能体使用验证报告](docs/AI智能体使用验证报告.md)
- [多页 HTML 原型](docs/appendices/prototype/README.md)
- [渲染图索引](docs/appendices/rendered/README.md)
- [证据索引 E-01—E-09、E-11—E-15](docs/appendices/evidence/index.md)

## 文档生成

详细US、UC、SC和类分析分别在对应目录维护；01—08的关键节选由构建脚本从这些源文件同步，按章节顺序生成整合说明书。

```text
python3 scripts/cli.py build
python3 scripts/cli.py check
```

### 图片重新导出

在项目根目录执行：

```bash
# 增量渲染：只重新导出源文件或产物摘要变化、PNG 缺失的图
python3 scripts/cli.py render

# 强制重新导出全部图
python3 scripts/cli.py render --force

# 渲染图片，同时同步章节和整合说明书
python3 scripts/cli.py build
```

脚本调用本机 PlantUML，将 `docs/appendices/models/*.puml` 导出为默认200 DPI的PNG，保存到 `docs/appendices/rendered/`；同时更新对应 `.png.version` 中的源文件及PNG两个SHA-256摘要（不记录版本号、时间或DPI），以及渲染索引。源文件摘要包含版本注释，因此仅修改图源版本头也会触发重新渲染。`render` 不同步需求正文，也不导出PDF；需要同步正文时使用 `build`。

仅同步正文用 `python3 scripts/cli.py report`，仅检查用 `python3 scripts/cli.py check`；原型直接维护HTML页面。分步构建及自定义DPI见[scripts说明](scripts/README.md)。

## PDF 增量导出与检查

先同步Markdown正文，再导出PDF；以下命令在项目根目录执行：

```text
python3 scripts/cli.py report
python3 scripts/cli.py pdf
python3 scripts/cli.py pdf --check --pdf-link-check on
```

导出范围为 `docs/` 下全部Markdown，输出到 `docs-pdf/` 并保持目录层级；主说明书对应 `docs-pdf/需求规格说明书.pdf`。图片、图源及HTML原型等引用附件一并复制。导出前应已消除docs外的本地文件引用，不以导出时转成文字路径代替源文档修正，不生成 `_repository/`。

默认使用SHA-256增量导出。缓存 `docs-pdf/.export-cache.json` 分别保存源文件、渲染输入和产出PDF摘要；未变化且产出完整的PDF直接复用。源文档、内嵌图片、字体、模板、脚本、渲染器版本或排版参数变化时重导受影响文件；PDF缺失或内容损坏时自动重导。附件仅在内容变化时复制；首次无缓存时正常生成，缓存与PDF均由Git忽略。

```text
python3 scripts/cli.py pdf --only docs/requirements/02-用户需求.md
python3 scripts/cli.py pdf --force --only docs/requirements/02-用户需求.md
```

`--only` 可重复指定文件或目录，`--force` 强制重导所选范围。首次交付应运行完整的增量导出命令，以保证跨PDF目标齐全；选定导出不会递归生成其他PDF。默认并行4个任务，可用 `--jobs 1` 顺序运行。

PDF依赖Pandoc、XeLaTeX、`fc-match`及本机字体：中文苹方 `PingFang SC`、西文 `Times New Roman`、代码 `Fira Code`；PNG内中西文统一苹方。脚本按实际字体文件及集合索引加载，避免字体名查找失败。检查依赖qpdf核对实际链接注解、页内锚点及跨PDF目标，pdftotext扫描缺字；使用 `--pdf-link-check on` 可要求执行链接检查。

跨PDF文件名以Unicode文件描述保存，支持中文和空格。阅读时保留整个 `docs-pdf/` 目录结构，并使用支持本地跨PDF跳转的阅读器；红色为跨文件链接配色，不表示链接错误。字体、宽表、缓存失效条件及更多参数见[scripts说明](scripts/README.md#pdf-导出)。
