<!--
Version: 0.1.1
Version-Datetime: 2026-10-30T14:32:28+08:00
-->

# PostgreSQL 资源准备

由实例管理员执行，示例 host 为本机。将 `postgres` 换成实际管理员角色；先确认实例端口及版本。命令只建空数据库，不导入 SQLite 数据，也不执行应用迁移。不要对现有同名库先 DROP；遇到已存在先停止并核对归属。

本机 test 资源已按本节规则实测：PostgreSQL 18.6，`campus_market_test`、`campus_test_app`、`campus_test_migrator`、`campus_test_owner` 可用，migrator 连接后可 `SET ROLE campus_test_owner`，schema 为 `app`；Alembic 四项迁移（当前 head：`b7c1d2e3f4a5`） 已在 test 库应用，重复迁移无变更。生产库未由本轮连接、迁移或读取，禁止把下列示例直接套用于生产。

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -W
```

进入 psql 后执行（保留 `ON_ERROR_STOP`；CREATE DATABASE 不能放进 BEGIN）：

```sql
\set ON_ERROR_STOP on
SELECT version();
SHOW password_encryption;
SET password_encryption = 'scram-sha-256';

CREATE ROLE campus_prod_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE campus_prod_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE campus_prod_app LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT campus_prod_owner TO campus_prod_migrator;
\password campus_prod_migrator
\password campus_prod_app

CREATE ROLE campus_test_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE campus_test_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE campus_test_app LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT campus_test_owner TO campus_test_migrator;
\password campus_test_migrator
\password campus_test_app

CREATE DATABASE campus_market_prod OWNER campus_prod_owner TEMPLATE template0 ENCODING 'UTF8';
CREATE DATABASE campus_market_test OWNER campus_test_owner TEMPLATE template0 ENCODING 'UTF8';
REVOKE ALL ON DATABASE campus_market_prod FROM PUBLIC;
REVOKE ALL ON DATABASE campus_market_test FROM PUBLIC;
GRANT CONNECT ON DATABASE campus_market_prod TO campus_prod_migrator, campus_prod_app;
GRANT CONNECT ON DATABASE campus_market_test TO campus_test_migrator, campus_test_app;

```

将下面的连接命令单独输入并回车，看到 `campus_market_prod=#` 后再执行后续 SQL；不要将 `\connect` 与 SQL 一起粘贴：

```psql
\connect campus_market_prod
```

```sql
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA app AUTHORIZATION campus_prod_owner;
ALTER ROLE campus_prod_app IN DATABASE campus_market_prod SET search_path = app;
ALTER ROLE campus_prod_migrator IN DATABASE campus_market_prod SET search_path = app;
ALTER ROLE campus_prod_app IN DATABASE campus_market_prod SET timezone = 'UTC';
GRANT USAGE ON SCHEMA app TO campus_prod_app;
ALTER DEFAULT PRIVILEGES FOR ROLE campus_prod_owner IN SCHEMA app
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO campus_prod_app;
ALTER DEFAULT PRIVILEGES FOR ROLE campus_prod_owner IN SCHEMA app
  GRANT USAGE, SELECT ON SEQUENCES TO campus_prod_app;

```

同样单独执行测试库连接命令，确认提示符切换后再粘贴 SQL：

```psql
\connect campus_market_test
```

```sql
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA app AUTHORIZATION campus_test_owner;
ALTER ROLE campus_test_app IN DATABASE campus_market_test SET search_path = app;
ALTER ROLE campus_test_migrator IN DATABASE campus_market_test SET search_path = app;
ALTER ROLE campus_test_app IN DATABASE campus_market_test SET timezone = 'UTC';
GRANT USAGE ON SCHEMA app TO campus_test_app;
ALTER DEFAULT PRIVILEGES FOR ROLE campus_test_owner IN SCHEMA app
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO campus_test_app;
ALTER DEFAULT PRIVILEGES FOR ROLE campus_test_owner IN SCHEMA app
  GRANT USAGE, SELECT ON SEQUENCES TO campus_test_app;
```

每条 `\password` 会安全提示输入两遍，密码不写入文档、SQL 命令或 shell 历史。不同环境与不同登录角色使用不同密码。默认权限只作用于之后由 owner 建立的对象，迁移必须显式 SET ROLE owner；不能让 migrator 直接成为表所有者。迁移后再次撤销审计表的修改/删除权限，并检查已有表的授权，不能仅依赖默认权限。

迁移连接使用 migrator，连接后执行（按环境二选一；由迁移实现自动设置）：

```sql
SET ROLE campus_test_owner;
SET search_path = app;
SELECT session_user, current_user, current_database(), current_schema();
-- 版本化 DDL 由 `python -m app.manage migrate` 执行；不要手工 create_all 生产库。
RESET ROLE;
```

应用连接验证（只读）：

```bash
psql -h 127.0.0.1 -p 5432 -U campus_test_app -d campus_market_test -W -c 'SELECT current_user, current_database(), current_schema();'
psql -h 127.0.0.1 -p 5432 -U campus_prod_app -d campus_market_prod -W -c 'SELECT current_user, current_database(), current_schema();'
```

预期 schema 为 app。再用 test 用户尝试连接 prod，应被拒绝；prod 用户尝试 test 同样拒绝。管理员核对 `pg_hba.conf` 对 TCP 连接采用密码认证（如 scram-sha-256），避免 trust 掩盖密码错误；只开放实际需要的监听地址。远程生产连接使用受信 CA 验证的 TLS，连接串及驱动 SSL 参数由实现核对，不直接套用不兼容的驱动参数。

审计迁移应包含以下等效授权（表名以实现确定的 audit_events 为目标）：

```sql
-- 在对应数据库、迁移 owner 会话中执行；迁移实现需对 prod 使用对应角色。
REVOKE UPDATE, DELETE, TRUNCATE ON app.audit_events FROM campus_test_app;
GRANT SELECT, INSERT ON app.audit_events TO campus_test_app;
```

对象登记表由同一迁移链创建，app 仅需 SELECT/INSERT/UPDATE，不应有 DELETE/TRUNCATE：

```sql
REVOKE DELETE, TRUNCATE ON app.stored_objects FROM campus_test_app;
GRANT SELECT, INSERT, UPDATE ON app.stored_objects TO campus_test_app;
```

资源交接只提供非敏感信息：版本、host/port、两个库名、角色名、连通结果。密码由负责人直接填写本地环境配置。备份由数据库管理员角色执行和恢复演练，应用账号不承担备份权限。
