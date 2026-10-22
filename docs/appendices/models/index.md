<!--
Version: 0.4.6
Version-Datetime: 2026-10-23T03:48:11+08:00
-->

# 图索引

共20张业务模型图，均有PlantUML可编辑源文件及PNG；ST-01—ST-03分别表达商品状态、交易生命周期及交易约定与确认进度。图稿可读性与逐项检查记录尚待补齐。

| 图编号 | 名称／类型 | 可编辑源文件 | 展示图 | 引用正文 | 关联 evidence | 关联需求／分析项 |
|---|---|---|---|---|---|---|
| UC-01 | 系统用例图（用例图；参与者两侧、用例两列，以 <<extend>> 表达条件性扩展） | [UC-01-系统用例图.puml](UC-01-系统用例图.puml) | [PNG](../rendered/UC-01-系统用例图.png) | [2. 用户需求 §2.5](../../requirements/02-用户需求.md)、[主报告第 2 部分](../../需求规格说明书.md) | 无，分析推导；范围依据 [E-07](../evidence/E-07-需求结构扩展.md) | R-01—R-04、FR-01—FR-14、UC-C01—C14、UC-C08-01 |
| UC-02 | 关键用例能力分组图；5个主用例、32个子用例，分组不表示必经顺序 | [UC-02-子用例图.puml](UC-02-子用例图.puml) | [PNG](../rendered/UC-02-子用例图.png) | [2. 用户需求 §2.5](../../requirements/02-用户需求.md) | 无，分析推导；子用例编号见[子用例分解](../use-cases/子用例分解.md) | UC-C02、C04、C05、C08、C14 及其子用例 |
| CL-01 | 核心领域类图 | [CL-01-核心领域类图.puml](CL-01-核心领域类图.puml) | [PNG](../rendered/CL-01-核心领域类图.png) | [第 3 章 3.3.3](../../requirements/03-领域与数据.md)；主报告领域分析部分 | 分析推导；交易双方与认领数量依据 C-09／C-13 类分析；两类 IM 依据 [E-08 D-42](../evidence/E-08-普通IM与购买请求联动.md) | C-01—C-04、C-07、C-09、C-10、C-13；BR-01、BR-02、BR-03、BR-18、BR-28、BR-29、BR-33、BR-34 |
| CL-02 | 账户与商品类图 | [PlantUML](CL-02-账户与商品类图.puml) | [PNG](../rendered/CL-02-账户与商品类图.png) | [第3章领域分析](../../requirements/03-领域与数据.md) | 现行规则及逐类分析 | C-01—C-06；UC-C01—C04、C13 |
| CL-03 | 交易与沟通类图 | [PlantUML](CL-03-交易与沟通类图.puml) | [PNG](../rendered/CL-03-交易与沟通类图.png) | [第3章领域分析](../../requirements/03-领域与数据.md) | 现行规则及逐类分析 | C-01、C-02、C-07—C-11；UC-C04—C07 |
| CL-04 | 治理与通知类图 | [PlantUML](CL-04-治理与通知类图.puml) | [PNG](../rendered/CL-04-治理与通知类图.png) | [第3章领域分析](../../requirements/03-领域与数据.md) | 现行规则及逐类分析 | C-01、C-04、C-09、C-12—C-16；UC-C02、C07、C08、C11、C14 |
| ST-01 | 商品状态图 | [ST-01-商品状态图.puml](ST-01-商品状态图.puml) | [PNG](../rendered/ST-01-商品状态图.png) | [第 5 章 5.2.1](../../requirements/05-行为与状态.md) | 无，分析推导（转换依据 TR-01—TR-10） | C-02、SC-02／SC-05／SC-06、BR-10—BR-12、BR-14、BR-33 |
| ST-02 | 交易状态图 | [ST-02-交易状态图.puml](ST-02-交易状态图.puml) | [PNG](../rendered/ST-02-交易状态图.png) | [第 5 章 5.2.1](../../requirements/05-行为与状态.md) | 无，分析推导（转换依据 TR-11—TR-19） | C-09、SC-05／SC-06、BR-01、BR-03—BR-09、BR-07 |
| ST-03 | 交易约定与确认进度 | [PlantUML](ST-03-交易约定与确认进度.puml) | [PNG](../rendered/ST-03-交易约定与确认进度.png) | [第5章5.2.1](../../requirements/05-行为与状态.md) | BR-04—BR-06、BR-07；4.15 | C-09、C-10；UC-C05、C06、C14 |
| ACT-01 | 发布与首次审核／活动图（泳道） | [ACT-01-发布与首次审核.puml](ACT-01-发布与首次审核.puml) | [PNG](../rendered/ACT-01-发布与首次审核.png) | [SC-02](../scenarios/SC-02-商品发布、审核与维护.md) | 分析推导；规则见 [4 章](../../requirements/04-规则与权限.md) | SC-02-01、SC-02-02；FR-02；BR-10、BR-12、BR-13、BR-34；TR-01—TR-03 |
| ACT-02 | 交易请求、锁单与双方确认／活动图（泳道） | [ACT-02-交易请求与双方确认.puml](ACT-02-交易请求与双方确认.puml) | [PNG](../rendered/ACT-02-交易请求与双方确认.png) | [SC-05](../scenarios/SC-05-请求、锁单、确认与终止.md) | 分析推导；交易边界见 [E-01 D-02](../evidence/E-01-范围讨论结果.md) | SC-05-01、SC-05-05、SC-05-08、SC-05-09；FR-05、FR-06；BR-01—BR-07、BR-28—BR-29；TR-11—TR-16 |
| ACT-03 | 交易争议与恢复／活动图（泳道） | [ACT-03-交易争议与恢复.puml](ACT-03-交易争议与恢复.puml) | [PNG](../rendered/ACT-03-交易争议与恢复.png) | [SC-06](../scenarios/SC-06-交易争议与恢复.md) | 争议时效与恢复见 [E-05](../evidence/E-05-状态转换复核.md)、[E-06](../evidence/E-06-处置流程与展示复核.md) | SC-06-01—SC-06-08；FR-05、FR-08；BR-05—BR-07、BR-06、BR-07、BR-08、BR-26、BR-29、BR-33、BR-34；TR-16、TR-18、TR-19 |
| ACT-04 | 商品信息修改、锁单与下架／活动图（泳道） | [ACT-04-修改锁单与下架.puml](ACT-04-修改锁单与下架.puml) | [PNG](../rendered/ACT-04-修改锁单与下架.png) | [SC-02](../scenarios/SC-02-商品发布、审核与维护.md) | 修改不二审见 [E-06 D-38](../evidence/E-06-处置流程与展示复核.md) | SC-02-03—SC-02-09；FR-02、FR-09；BR-02、BR-06、BR-09、BR-10、BR-11、BR-12、BR-14、BR-32、BR-33；TR-04、TR-07、TR-08 |
| ACT-05 | 账户与访问控制／活动图（泳道） | [ACT-05-账户与访问控制.puml](ACT-05-账户与访问控制.puml) | [PNG](../rendered/ACT-05-账户与访问控制.png) | [SC-01](../scenarios/SC-01-账户与访问控制.md) | 访问口径见 [E-03 D-18](../evidence/E-03-新增规则复核.md) | SC-01-01—SC-01-08；FR-01；BR-32、BR-20—BR-22；BR-32 |
| ACT-06 | 检索、详情可见性与收藏／活动图（泳道） | [ACT-06-检索详情与收藏.puml](ACT-06-检索详情与收藏.puml) | [PNG](../rendered/ACT-06-检索详情与收藏.png) | [SC-03](../scenarios/SC-03-检索、详情可见性与收藏.md) | 详情与搜索边界见 [E-06](../evidence/E-06-处置流程与展示复核.md) | SC-03-01—SC-03-08；FR-03、FR-04；BR-14、BR-15、BR-16、BR-22、BR-32 |
| ACT-07 | 商品评论与两类 IM／活动图（泳道） | [ACT-07-评论与买卖IM.puml](ACT-07-评论与买卖IM.puml) | [PNG](../rendered/ACT-07-评论与买卖IM.png) | [SC-04](../scenarios/SC-04-商品评论与两类IM.md) | 评论与 IM 必做见 [E-01 D-03、D-07](../evidence/E-01-范围讨论结果.md)；两类 IM 与交易联动见 [E-08 D-42](../evidence/E-08-普通IM与购买请求联动.md) | SC-04-01—SC-04-08；FR-04、FR-05、FR-11；BR-01、BR-17—BR-19、BR-02、BR-14、BR-17、BR-18、BR-22、BR-32、BR-33、BR-34 |
| ACT-08 | 完成交易评价／活动图（泳道） | [ACT-08-完成交易评价.puml](ACT-08-完成交易评价.puml) | [PNG](../rendered/ACT-08-完成交易评价.png) | [SC-07](../scenarios/SC-07-评价、举报、认领与封禁.md) | 评价仅本人查看的口径见 [E-07](../evidence/E-07-需求结构扩展.md) | SC-07-01—SC-07-03；FR-07；BR-24、BR-32 |
| ACT-09 | 举报、认领处置与封禁／活动图（泳道） | [ACT-09-举报认领与处置.puml](ACT-09-举报认领与处置.puml) | [PNG](../rendered/ACT-09-举报认领与处置.png) | [SC-07](../scenarios/SC-07-评价、举报、认领与封禁.md) | 认领与冻结见 [E-06 D-36—D-39](../evidence/E-06-处置流程与展示复核.md) | SC-07-04—SC-07-11；FR-07、FR-08；BR-18、BR-25、BR-26、BR-32、BR-33、BR-34；TR-09、TR-10 |
| ACT-10 | 管理员统计／活动图（泳道） | [ACT-10-管理员统计.puml](ACT-10-管理员统计.puml) | [PNG](../rendered/ACT-10-管理员统计.png) | [SC-08](../scenarios/SC-08-管理员统计.md) | 统计口径见 [E-02 D-15](../evidence/E-02-规则补充采纳记录.md) | SC-08-01—SC-08-06；FR-10；BR-31 |
| ACT-11 | 单方确认超时与异常交易处置／活动图（泳道） | [ACT-11-异常交易处置.puml](ACT-11-异常交易处置.puml) | [PNG](../rendered/ACT-11-异常交易处置.png) | [SC-09](../scenarios/SC-09-单方确认超时与异常交易处置.md) | 超时与冻结见 [E-06 D-38](../evidence/E-06-处置流程与展示复核.md) | SC-09-01—SC-09-08；FR-14；BR-05、BR-18、BR-33；TR-14、TR-19 |

## 图模型范围

UC-01／UC-02 表达角色、用例及子用例关系；CL-01表达核心类属性、行为及关联，CL-02—CL-04分领域展开完整属性及行为；ST-01／ST-02表达商品及交易生命周期，ST-03表达交易内部阶段及确认进度；ACT-01—ACT-11 表达业务流程。按用户故事组织的多页 HTML 原型见[原型说明](../prototype/README.md)。

停用与撤销规则见 [E-09](../evidence/E-09-规则合并与编号重排.md)；现行业务转换见第 4 章。全部图稿 PNG 见[渲染索引](../rendered/README.md)。
