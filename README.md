<!--
Version: 0.1.23
Version-Datetime: 2026-10-26T21:22:39+08:00
-->

# 校园二手交易与物品流转平台

本目录保存校园二手交易与物品流转平台的需求分析交付材料。全部14个主用例、14个用户故事及16个领域类均有独立详细文档。01—08按顺序构成需求规格说明书正文，详细材料以各目录索引为入口；正文详细展开关键US、UC、类及SC并展示关键图。需求正文及US／UC／SC／领域类分析已于2026-10-23获项目负责人确认，BR／TR已讨论接受；确认范围见[需求基线](docs/requirements/08-需求基线.md)。

## 成员分工

需求成果确认已登记；当时34张图稿（含UC-03—UC-16独立用例图）已于2026-10-26由用户确认审阅通过；13张变化图稿及相关一致性修订已于2026-10-26获用户确认；成员按实际完成的内容记录贡献，见 [成员职责表](bits/成员职责表.md)。

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
| `docs/draft-AI智能体使用验证报告.md` | B 报告，汇总实质 AI 贡献、人工取舍、核验与证据索引 |
| `docs/appendices/models/` | 报告图（用例、活动、类、状态、上下文图等）的可编辑源文件目录，例如 `.puml`、`.mmd`；PNG 集中在 docs/appendices/rendered，不保存 SVG |
| `docs/appendices/rendered/` | `.puml`／`.mmd` 统一渲染的 PNG，入口 [渲染索引](docs/appendices/rendered/README.md) |
| `docs/appendices/evidence/` | 业务决定及讨论依据、实际形成的验证证据；入口 [证据索引](docs/appendices/evidence/index.md)，E 编号与 D 决定连续编号；编号重排时以 evidence 中映射表为准 |
| `docs/appendices/ai-usage/` | AI关键分析贡献、必要上下文及交互原文、人工取舍和核验、填写模板，索引见 [index.md](docs/appendices/ai-usage/index.md)，填写规则见 [AGENTS.md](AGENTS.md) |
| `docs/appendices/prototype/` | 按用户故事组织的多页 HTML 原型及 [说明](docs/appendices/prototype/README.md)，一个 HTML 文件一个页面，示例数据不代表后台功能实现 |
| `docs-pdf/` | 由Pandoc生成的PDF交付副本，保持docs的目录结构，文档链接使用PDF目标；该目录由Git忽略 |
| `scripts/` | [Python构建说明](scripts/README.md)：同步关键材料、生成说明书、渲染PNG，以及按SHA-256增量导出和检查PDF |
| `bits/` | 项目 notes：实际成员贡献、开放问题及分析检查；文件不加 draft-，未决／待验证在正文注明，实际贡献按事实记录 |

文件按“编号-名称”组织；编号重排时同步更新文件名、索引及引用，需要的版本、日期按版本规范记录，需求确认事实集中登记在需求基线和证据中。正文通过相对链接及编号引用附件；尚未开展的工作不预填结果。

`docs/`中的交付材料只引用`docs/`内的本地文件，不引用仓库根AGENTS.md／README.md、bits、scripts或其他目录。必要决定、背景及依据保留在docs内，使交付材料能够独立阅读；历史引文中的文件名不作为现行依赖。脚本用法和仓库操作规范保留在docs外的指导文件中，工作笔记及仓库指导文件可以引用docs。

## 范围与验证约束

- 原型作为本项目需求分析交付材料，包含按用户故事组织的15个HTML页面。
- 场景分析与原型材料已成文；场景及原型走查由张新悦、孙含佳、金婉怡分别于 2026-10-23、2026-10-23、2026-10-25 完成（A.5.4—A.5.6、A.6.4—A.6.6、E-11—E-13）。图稿可读性记录按实际范围保留，系统运行验收在实现阶段开展。
- 多页 HTML 原型按用户故事组织界面示例，作为最终 review 的补充材料，不以静态页面证明后台功能已实现。
- 需求清单覆盖题目全部十项核心功能；14个主用例均有详细文档，主报告选取五个关键业务闭环展开。
- 业务规则、术语及未决问题统一维护；性能目标按第 6 章登记的来源与状态表达，实测结论待系统实现后形成。教学模拟如实标注，AI 自检不能替代人工确认。
- 各成员仅记录 AI 对项目分析有实质影响的关键建议、人工取舍及证据，须有必要上下文并注明姓名；人工直接决定由 evidence 承载。实质分析开始时起草ai-usage，讨论中途保存关键prompt／output及实际反馈原文、来源定位与人工取舍；不要求完整聊天或环境、Git、一般文档维护流水，也不要求每次提交补档。构建与导出工具按用户明确要求专项记录于[AI-14](docs/appendices/ai-usage/AI-14-2026-10-23-文档构建与PDF增量导出.md)，不扩大日常维护的默认建档范围。详细边界见 AGENTS.md；B 报告由组长汇总。袁尚峰统筹最终review与汇总；三位成员已在各自设备和Git账号下完成走查及个人AI证据补充，实际贡献见A报告A.8。

## 图文件与索引规范

- 报告图可编辑源文件统一放在 `docs/appendices/models/`，PNG 集中在 `docs/appendices/rendered/`，不散落到章节目录；证据截图、原始资料仍放 `docs/appendices/evidence/`，原型材料放 `docs/appendices/prototype/`。
- 图文件采用“编号-名称”，例如 `ACT-02-交易请求与双方确认.puml`；图模型保留可编辑源文件，同名 PNG 集中到 `docs/appendices/rendered/`，不保存 SVG 导出图；多页 HTML 原型直接维护 HTML 页面。
- Markdown 正文以相对路径链接引用源文件，并可用图片语法展示 `docs/appendices/rendered/` 中已有的 PNG；图源与图片同步，不插入不存在的图片链接。
- [图索引](docs/appendices/models/index.md) 登记图编号、名称、源文件、正文位置、关联证据 evidence，以及可选关联项目／分析项；链接必须定位实际文件或条目。
- 不交付数据字典，不开展传统数据建模；保留领域类分析、职责、关联、状态和必要业务概念。不得据此省略业务规则、权限或隐私约束。

## 草稿与版本规范

- `bits/` 为 notes，不使用 `draft-` 前缀，去前缀不代表内容已验证；其余未确认的业务文档以 `draft-` 开头；确认后去除前缀并修订引用。README 及配置属于仓库运行规范，不作为业务确认稿。
- 仅 `docs/` 下的文件及各目录的 `README.md`、`AGENTS.md` 需要记录 `Version: x.y.z` 和带时区的 `Version-Datetime: ISO8601`。文本在原生注释或正文中记录；`docs/` 中的二进制文件使用同目录 `<文件名>.version` 伴随文件记录。其他文件（包括工具源码、测试、配置及未来业务代码）不需要版本信息，由 Git 历史追踪。
- 每次 commit 前对需要版本信息的修改文件按最终内容统一递增版本号、更新版本时间，并与上一提交比较；时间不得在未来。同一提交前的多轮修改不逐轮登记版本或保留未提交即放弃的中间方案。删除文件无需更新版本。
- 文档拆分、改名后同步修订引用。图源按最终提交内容管理版本。

## 提交前操作

完整的智能体工作与提交前检查规则统一见 [AGENTS.md](AGENTS.md)，适用于每次 commit 和 amend；提交前须检查需求／规则边界、跨文档一致性、历史遗留及实际目录与 README／索引同步；由用户明确指出 AI 使用模型及工作负责人，逐文件确认 diff、归属和更改。成员提交时同样按该检查清单核对；此处仅保留入口，不配置可执行 Git hook。

## 当前阶段工作入口

- [项目协作复盘与后续工作方法](bits/项目协作复盘与后续工作方法.md)：根据本人及组员Git历史，归纳基线漂移、共享材料合并、覆盖与模型语义、证据记录、图稿和导出等问题，说明后续任务的组织方法。具体执行规则统一见[AGENTS.md](AGENTS.md#工作中的基线变更传播与交接强制)。

- [需求基线](docs/requirements/08-需求基线.md)：指定需求范围、纳入版本与确认记录。
- [未决问题与复核清单](bits/未决问题与复核清单.md)：统一维护开放问题、责任与处理状态。

01—08及整合说明书已去除草稿前缀；附录文件名已去除 `draft-`，档案与证据的确认状态以正文记录为准。A报告已于2026-10-26经袁尚峰确认去除 `draft-`；B报告保留草稿前缀，后续确认及提交信息见工作笔记。变更纳入文件时同步更新基线版本表及影响记录。

## 报告入口

- [需求规格说明书](docs/需求规格说明书.md)
- [附录与附件索引](docs/appendices/index.md)
- [需求分析质量验证报告](docs/需求分析质量验证报告.md)
- [AI 智能体使用验证报告](docs/draft-AI智能体使用验证报告.md)
- [多页 HTML 原型](docs/appendices/prototype/README.md)
- [渲染图索引](docs/appendices/rendered/README.md)
- [证据索引 E-01—E-09、E-11—E-15](docs/appendices/evidence/index.md)

## 文档生成

详细US、UC、SC和类分析分别在对应目录维护；01—08的关键节选由构建脚本从这些源文件同步，按章节顺序生成整合说明书。

```text
python3 scripts/cli.py build
python3 scripts/cli.py check
```

默认按源文件摘要复用未变化的业务图，需更新时按200 DPI渲染34张业务模型图。仅同步正文用 `python3 scripts/cli.py report`，仅检查用 `python3 scripts/cli.py check`；原型直接维护HTML页面。分步构建及自定义DPI见[scripts说明](scripts/README.md)。

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
