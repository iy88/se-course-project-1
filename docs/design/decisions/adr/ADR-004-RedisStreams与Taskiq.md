<!--
Version: 0.1.5
Version-Datetime: 2026-11-18T20:49:08+08:00
-->

# ADR-004 Redis Streams 与 Taskiq

| 字段 | 内容 |
|---|---|
| 编号/标题 | ADR-004 Redis Streams 与 Taskiq |
| 协作入口 | [任务 Issue](https://github.com/iy88/se-course-project-1/issues/38) |
| 背景 | FR-04、FR-05、FR-11、FR-14；实时及任务恢复。 关联 Q：按实际问题登记。 |
| 比较 | 见下表可行方案及影响 |
| 决定 | 采用 Redis Streams及任务执行适配器；IM 各实例独立游标读取并分发本机连接，worker 同组分担，数据库事件及调度记录支持认领和接管。 |
| 理由 | 复用 Redis 共享控制体系，控制当前组件数量，持久恢复依据留在数据库。 |
| 代价 | IM 全流读取开销随实例数增长；需要定义保留、缺口补取、ACK 与重复处理。 |
| 验证 | 两个 IM／worker 实例验证覆盖投递、竞争领取、崩溃接管和重连。 预期由对应任务的实际审查人核验，执行版本、环境、命令和结果在任务证据中登记。 结果位置随任务证据登记。 |
| 确认 | 本会话已明确采纳；确认姓名：袁尚峰；实际确认日期按会话记录登记，整理日期2026-11-13；交叉复核姓名及日期待登记。 |
| 重新评估条件 | 实测路由、积压隔离或恢复成本显著变化。 |
| 替代关系 | 首次登记；后续替代关联新旧 ADR |

## 可行方案比较

| 方案 | 收益与代价 |
|---|---|
| 方案 A | Redis Streams 复用既有 Redis，需明确独立读取／消费组与恢复 |
| 方案 B | RabbitMQ 提供路由与投递机制，增加一套部署及运维组件 |

任务执行层通过适配器接入 Redis Streams。Taskiq 是早期 Python 候选方案中的适配器。Java 工程按下面的映射和专题协议验证。

## 第4批协议细化

[实时与任务](../../detailed-design/key-designs/实时与任务.md)定义数据库账户序号及恢复边界、Redis发布与每IM独立XREAD、连接ACK／背压、worker 同组任务分担、持久认领及token约束。Redis确认、客户端传输确认与主体已读分别维护。邮箱及文件等来源工作复用其自身持久记录；通用业务调度采用TaskSchedule。验证采用TC-COM-023—028，实际依赖版本随实现锁定。

## Java 适配与 S1 验证

TASK-001 维护 `messaging` 模块，首批采用 [Spring Data Redis 的 Streams 接口](https://docs.spring.io/spring-data/redis/reference/redis/redis-streams.html)验证发布、独立读取、消费组和显式确认。应用装配 worker 与 scheduler，各来源模块持有任务事实并提供处理器。

通知派发读取已提交事件，实时实例以独立游标分发本机连接；worker 以消费组分担，并按来源记录锁及租约规则领取。Redis 确认在数据库已持久化本次结果或确认无需继续处理后执行；数据库事件与来源记录用于漏投扫描、重试和租约接管。

S1 在目标 Linux／OpenJDK 27 下用真实 PostgreSQL 和 Redis 验证通知重投与恢复、邮件 worker 中断与接管，采用 TC-COM-008／023—025／027 的适用子场景。锁定随 Spring Boot 管理的依赖及实测版本。S2 接入普通私聊与交易分支，S4 接入交易超时调度和事项能力。
