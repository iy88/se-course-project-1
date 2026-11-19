<!--
Version: 0.2.6
Version-Datetime: 2026-11-19T22:44:22+08:00
-->

# Project1 脚本使用说明

脚本按自身位置定位项目，可从任意工作目录运行。

## 开发启动器

macOS 或 Linux 使用 `dev.py`，Windows 使用 PowerShell 5.1 或更高版本启动 `dev.ps1`。两者启动相同的 API、调度器、工作进程和双前端，默认读取 `backend/.env.dev`。Windows 需允许当前用户执行本地 `.ps1` 脚本：

```text
python3 scripts/dev.py start --env-file=backend/.env.dev
.\scripts\dev.ps1 start -EnvFile backend/.env.dev
```

分别使用 `status`、`restart` 和 `stop` 查看状态、重启和停止。Windows 的监督日志为 `var/dev/dev.log`，各服务输出位于 `var/dev/logs/`。

## 文档构建

文档构建额外依赖 Python 3.10+、PlantUML 及其 Java／Graphviz 环境。

在 project1 根目录执行：

```text
python3 scripts/cli.py build
```

默认先将34张业务模型图按200 DPI输出到 `docs/appendices/rendered/`，再同步关键材料到01—08章节并生成 `docs/需求规格说明书.md`。渲染索引自动登记实际像素尺寸和DPI；PNG伴随文件仅记录源文件及图片两个SHA-256摘要，不记录版本号、时间或DPI。

## 目录结构与统一入口

```text
scripts/
  cli.py                 # 文档构建入口
  dev.py                 # macOS/Linux 开发启动器
  dev.ps1                # Windows PowerShell 5.1+ 开发启动器
  doc_tools/
    common.py            # 原子写入、版本元数据与公共常量
    markdown.py          # Markdown展开、链接重定位与锚点
    report.py            # 需求章节同步与整合说明书
    design.py            # 按清单拼合设计文档
    diagrams.py          # PlantUML渲染、PNG和DPI
    checks.py            # 本地文档引用检查
    pdf/
      types.py           # 导出计划、记录类型与路径配置
      navigation.py      # PDF目标编码及注解读取
      transform.py       # Pandoc语法树、锚点及链接改写
      fonts.py           # 工具和字体解析
      exporter.py        # 文件发现、计划及转换协调
      cache.py           # SHA-256摘要、缓存及增量调度
      checks.py          # PDF产物、跳转和缺字检查
      commands.py        # PDF参数与命令执行
      header.tex         # 排版与链接宏
  tests/                 # 构建工具回归用例
```

统一使用 `cli.py` 的 `build`、`report`、`render`、`check` 和 `pdf` 子命令；各功能模块仅提供内部接口，不单独作为CLI运行。旧入口 `build.py` 和 `export_pdf.py` 已移除；原构建命令对应 `build` 子命令，原导出参数直接接在 `pdf` 后。通过 `python3 scripts/cli.py --help` 或 `python3 scripts/cli.py pdf --help` 查看帮助。

## 分步命令

```text
python3 scripts/cli.py report
python3 scripts/cli.py render --dpi 300
python3 scripts/cli.py check
```

`report` 更新章节中的关键材料及整合说明书，并检查本地链接和锚点。`check` 只读核对生成内容、模型源文件、PNG摘要；DPI由生成脚本写入，不作为增量渲染或检查判据。改变输出DPI时，使用 `render --force --dpi 数值` 强制重新生成。

`--plantuml` 可指定PlantUML可执行文件路径，`--force` 可重新渲染全部选定图。渲染先验证全部选定图片成功，再发布到输出目录。分辨率通过PlantUML实际渲染和PNG物理分辨率共同设置。图源 `skinparam defaultFontName` 统一为 `PingFang SC`（苹方），PNG 中中文与西文均按该字体渲染。

## 唯一内容来源

| 内容 | 唯一维护位置 | 章节中的关键材料 |
|---|---|---|
| 用户故事 | `docs/appendices/user-stories/`，由 index 进入 | US-02、04、05、08 |
| 用例 | `docs/appendices/use-cases/`，由 index 进入 | UC-C02、04、05、08、14 |
| 领域类 | `docs/appendices/class-analysis/`，由 index 进入 | C-02、09、13、16 |
| 详细场景 | `docs/appendices/scenarios/`，由 index 进入 | SC-05、07、09 |
| 业务验收预期 | 对应SC文件的分支表 | 第07章引用SC分支及第05章关键场景 |
| 图模型 | `docs/appendices/models/*.puml` | 章节选择关键图，完整材料经图索引进入 |
| 线性正文 | `docs/requirements/01-*.md` 至 `08-*.md` | 按章节顺序构成整合说明书 |

各 index 仅作为链接入口，普通 Markdown 引用不会触发展开，主报告不注入索引正文或整套目录。仅显式标记的关键材料进入正文，同一场景的分支由验收章节引用。

编辑独立材料后运行 `report`，关键材料会自动刷新到章节与整合说明书。章节中的 `spec-include` 注释标定源文件及标题层级；块内为生成内容。选定材料保持完整业务分析，重复导航由章节统一组织。整合说明书由01—08生成。

第07章的可靠性、性能和安全验收目标在该章维护。完整业务场景及分支以SC索引和独立文件为入口，验收结论由验证报告承载。

工具源码、测试及排版模板不维护文件内版本号；本说明文件保留版本信息。

## 检查生成逻辑

```text
PYTHONPATH=scripts python3 -m unittest discover -s scripts/tests -p "test_*.py"
```

检查源文件修改传播、章节与报告一致性、链接重定位、路径范围、SC验收表投影、渲染失败时的输出保护及DPI记录。

## PDF 导出

`python3 scripts/cli.py pdf` 使用 Pandoc 与 XeLaTeX 将 `docs/` 下全部 Markdown 导出到 `docs-pdf/`，保持原有目录层级并把扩展名改为 `.pdf`。主说明书 `docs/需求规格说明书.md` 对应 `docs-pdf/需求规格说明书.pdf`。依赖 Pandoc、XeLaTeX 及 macOS 中文字体；默认中文使用 `PingFang SC`（苹方）、西文使用 `Times New Roman`、代码使用 `Fira Code`，脚本通过 `fc-match` 精确匹配字体家族并解析实际字体文件、TTC集合索引及粗体／斜体变体，使用fontspec的 `Path` 和 `FontIndex` 显式加载；不依赖XeLaTeX按字体名查找，也不接受其他家族的静默替代。字体路径在每次导出时解析，无需修改系统字体配置。

```text
python3 scripts/cli.py pdf --only docs/requirements/01-项目概述.md
python3 scripts/cli.py pdf
python3 scripts/cli.py pdf --check --pdf-link-check on
python3 scripts/cli.py pdf --force --only docs/requirements/01-项目概述.md
```

默认按SHA-256增量导出：`docs-pdf/.export-cache.json` 保存每份Markdown的源文件摘要、渲染输入摘要及产出PDF摘要。源文件、转换内容、内嵌图片、排版模板、字体文件、工具模块、渲染器版本或导出参数变化时重导受影响文件；已有PDF缺失或摘要不符时同样重导。未变化PDF直接复用，附件也只复制内容变化项。首次没有可信缓存的文件正常导出；每份成功后原子写入缓存，中断后可复用已完成文件。`--force` 强制重导选定范围；`--check` 在已有缓存时同时检查其是否过期。

`--only` 可重复并接受文件或目录，用于先导出少量样本；默认并行 4 个 XeLaTeX 进程，可用 `--jobs 1` 顺序执行。`--check` 只读核对全部选定 PDF、复制附件及改写后的本地链接，并在 qpdf 可用时检查实际 PDF 链接注解、页内目标及跨PDF命名目标，验证目标指向有效页面；`--pdf-link-check off` 可关闭注解检查。`--check` 默认还通过 `pdftotext` 扫描各 PDF 文本中的替换字符，发现字体缺字（如箭头、带圈数字渲染为空框）即报错；`--glyph-check off` 可关闭该扫描。

导出不修改源 Markdown。本地 `.md` 链接改写为相对 `.pdf` 路径并保留片段；标题同时登记 Pandoc ID 与 GitHub 风格片段别名，正文中的 `<a id="…">` 转为 LaTeX 目标，使目录链接可用。ASCII 片段保持原样；非 ASCII 片段在 PDF 目标中映射为稳定的 ASCII 目标名，避免 XeLaTeX 目标名编码不一致。外部 URL 原样保留；PNG、PUML 等非 Markdown 附件复制到对应目录。`docs/` 之外的仓库文档不导出；对应链接在PDF中保留标题与仓库相对路径文字，不生成点击动作或 `_repository/`。PDF间文件跳转使用显式UTF-16BE文件描述（`/Filespec`、`/UF`），保留真实中文文件名和空格，避免短中文名被误解为PDFDocEncoding，不把文件名编码为URI；网页和普通附件仍按URI处理。不展开索引目录，只处理实际链接。

输出为 A4，正文使用中文字体，长代码与 URL 自动换行，图片缩放至版心并按正文位置放置，避免漂移到长表之后；列数达到 6 的宽表自动使用横向页（`--no-landscape-tables` 可关闭）。字体、页边距、字号及宽表阈值可通过 `--cjk-main-font`、`--margin`、`--fontsize`、`--wide-table-columns` 等参数调整。`scripts/doc_tools/pdf/header.tex` 将正文使用的箭头（`→`、`↔` 等）映射到数学字形，并把带圈数字 `①`—`⑳` 声明为 CJK 字符，避免中文字体缺字形成空框。

## 设计文档拼合

设计源文件位于 `docs/design/`，`docs/design/基线索引.md` 为统一入口。`docs/design/拼合清单.json` 逐份列明文档标识、标题、输出文件和有序源文件。新增 Q、ADR、模块接口及关键设计专题后，在对应文档的 `sources` 中登记相对于 `docs/design/` 的源文件路径。

```text
python3 scripts/cli.py report --documents design
python3 scripts/cli.py check --documents design
python3 scripts/cli.py report --documents requirements
```

`--documents` 支持 `requirements`、`design` 和 `all`，默认 `all`。需求组继续使用 `docs/requirements/01—08` 及原摘录同步规则。设计组生成架构讨论稿、架构确认与决策记录、接口与关键设计说明书、分阶段实现与测试计划，保留章节来源链接并检查相对链接、目录和标题层级。架构基线版作为独立占位文件维护。模板用于建立后续条目，条目形成后按清单纳入整合文档。

设计组检查以只读方式核对生成结果；`check --documents design` 执行设计文档与仓库 Markdown 引用检查。相同内容重复生成保持结果稳定。
