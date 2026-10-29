"""报告生成：phase 汇总、US/AC 与 SC 分支覆盖、失败清单、缺陷候选、数据清单、证据边界。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from e2e_support import Ctx

US_TITLES = {
    "US-01": "账户生命周期",
    "US-02": "发布与维护商品",
    "US-03": "检索商品",
    "US-04": "收藏与咨询",
    "US-05": "请求与确认交易",
    "US-06": "记录线下交付",
    "US-07": "评价与举报",
    "US-08": "审核与处置沟通",
    "US-09": "了解商品状态",
    "US-10": "查看管理统计",
    "US-11": "接收通知与待办",
    "US-12": "管理本人业务",
    "US-13": "维护商品分类",
    "US-14": "处理异常交易",
}

SC_TITLES = {
    "SC-01": "账户与访问控制",
    "SC-02": "商品发布、审核与维护",
    "SC-03": "检索、详情可见性与收藏",
    "SC-04": "商品评论与两类 IM",
    "SC-05": "请求、锁单、确认与终止",
    "SC-06": "交易争议与恢复",
    "SC-07": "评价、举报、认领与封禁",
    "SC-08": "管理员统计",
    "SC-09": "单方确认超时与异常交易处置",
    "SC-10": "分类标签申请与维护",
    "SC-11": "站内通知与消息已读",
    "SC-12": "本人业务入口",
}


def _table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if cell is None else str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def _status_counts(results: list[dict]) -> dict[str, int]:
    counts = Counter(r["status"] for r in results)
    return {k: counts.get(k, 0) for k in ("PASS", "FAIL", "SKIP")}


def _coverage(results: list[dict], field: str, known: dict[str, str]) -> list[list]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        key = (row.get(field) or "").strip()
        if not key:
            continue
        # SC-02-05 等取前 5 位；US 取前 5 位
        key = key.split("-")[0] + "-" + key.split("-")[1] if len(key.split("-")) >= 2 else key
        groups[key].append(row)
    rows = []
    for key, title in known.items():
        items = groups.get(key, [])
        counts = _status_counts(items)
        checks = sorted({i["check_id"] for i in items})
        rows.append([key, title, counts["PASS"], counts["FAIL"], counts["SKIP"], "、".join(checks[:8]) + ("……" if len(checks) > 8 else "")])
    return rows


def build_report(
    *,
    run_id: str,
    base_url: str,
    health: dict,
    started_at: datetime,
    finished_at: datetime,
    phases: list[tuple],
    phase_summaries: list[dict],
    results: list[dict],
    defects: list[dict],
    call_counts: list[dict],
    ctx: Ctx,
    refresh_notes: list[str],
) -> str:
    counts = _status_counts(results)
    duration = (finished_at - started_at).total_seconds()
    lines: list[str] = []
    lines.append(f"# 开发环境真实 API 生命周期测试报告（{run_id}）")
    lines.append("")
    lines.append("> 本报告由真实运行中的后端 HTTP 接口测试自动生成；检查项只记录实际执行结果，")
    lines.append("> 不把未执行、被跳过或人工未核验的内容写成通过。")
    lines.append("")
    lines.append("## 1. 运行环境")
    lines.append("")
    lines.append(_table(
        ["项目", "值"],
        [
            ["运行标识", run_id],
            ["后端地址", base_url],
            ["健康检查", str(health)],
            ["开始时间", started_at.isoformat()],
            ["结束时间", finished_at.isoformat()],
            ["总用时", f"{duration:.1f}s"],
            ["执行阶段", "、".join(p[0] for p in phases)],
            ["数据清单条目", len(ctx.inventory)],
        ],
    ))
    lines.append("")
    lines.append("## 2. 结果总览")
    lines.append("")
    lines.append(_table(
        ["阶段", "内容", "需求范围", "PASS", "FAIL", "SKIP", "用时(s)", "异常中止"],
        [
            [
                row["id"],
                row["title"],
                row["requirements"],
                row["counts"].get("PASS", 0),
                row["counts"].get("FAIL", 0),
                row["counts"].get("SKIP", 0),
                row["elapsed_seconds"],
                "是" if row["aborted"] else "",
            ]
            for row in phase_summaries
        ],
    ))
    lines.append("")
    lines.append(_table(
        ["检查项总计", "PASS", "FAIL", "SKIP"],
        [["所有阶段", counts["PASS"], counts["FAIL"], counts["SKIP"]]],
    ))
    lines.append("")
    api_total = sum(row["calls"] for row in call_counts)
    lines.append(f"真实 HTTP 调用共 **{api_total}** 次；其中服务器 5xx **{sum(row['server_5xx'] for row in call_counts)}** 次。")
    lines.append("")

    lines.append("## 3. 用户故事验收条件覆盖（按检查项登记）")
    lines.append("")
    lines.append(_table(
        ["US", "名称", "PASS", "FAIL", "SKIP", "已执行检查项"],
        _coverage(results, "us", US_TITLES),
    ))
    lines.append("")
    lines.append("## 4. 场景分支覆盖（按检查项登记）")
    lines.append("")
    lines.append(_table(
        ["SC", "名称", "PASS", "FAIL", "SKIP", "已执行检查项"],
        _coverage(results, "sc", SC_TITLES),
    ))
    lines.append("")

    failed = [r for r in results if r["status"] == "FAIL"]
    skipped = [r for r in results if r["status"] == "SKIP"]
    lines.append("## 5. 失败与跳过清单")
    lines.append("")
    if failed:
        lines.append("### 5.1 失败检查项")
        lines.append("")
        lines.append(_table(
            ["检查项", "US", "SC", "说明", "实际/差异"],
            [
                [
                    r["check_id"],
                    r["us"],
                    r["sc"],
                    r["desc"],
                    (r.get("detail") or "")[:600],
                ]
                for r in failed
            ],
        ))
        lines.append("")
    else:
        lines.append("本运行未记录失败检查项。")
        lines.append("")
    if skipped:
        lines.append("### 5.2 跳过检查项")
        lines.append("")
        lines.append(_table(
            ["检查项", "US", "SC", "说明", "跳过原因"],
            [[r["check_id"], r["us"], r["sc"], r["desc"], (r.get("detail") or "")[:300]] for r in skipped],
        ))
        lines.append("")

    lines.append("## 6. 缺陷与异常候选")
    lines.append("")
    if defects:
        rows = []
        for d in defects:
            if d.get("kind") == "server_5xx":
                rows.append(["服务器 5xx", d.get("phase"), f"{d.get('method')} {d.get('path')} → {d.get('status')}", (d.get("body") or "")[:300]])
            elif d.get("kind") == "phase_aborted":
                rows.append(["阶段异常中止", d.get("phase"), d.get("detail", ""), (d.get("traceback") or "")[:300]])
            else:
                rows.append([d.get("kind", "其他"), d.get("phase"), str({k: v for k, v in d.items() if k not in ("kind", "phase")})[:400], ""])
        lines.append(_table(["类别", "阶段", "说明", "证据"], rows))
    else:
        lines.append("未记录 5xx 或阶段异常中止；失败检查项见第 5 节。")
    lines.append("")

    lines.append("## 7. 数据清单（开发库中保留并可查询）")
    lines.append("")
    accounts = [row for row in ctx.inventory if row["kind"] == "account"]
    lines.append("### 7.1 账户")
    lines.append("")
    lines.append(_table(
        ["key", "显示名称", "邮箱", "角色", "状态"],
        [
            [
                row["key"],
                row["label"],
                (row.get("extra") or {}).get("email", ""),
                (row.get("extra") or {}).get("role", ""),
                row["state"],
            ]
            for row in accounts
        ],
    ))
    lines.append("")
    for kind, title in [("category", "分类标签"), ("prohibited", "禁发范围"), ("product", "商品")]:
        rows = [row for row in ctx.inventory if row["kind"] == kind]
        if not rows:
            continue
        lines.append(f"### 7.{2 + ['category', 'prohibited', 'product'].index(kind)} {title}")
        lines.append("")
        lines.append(_table(
            ["key", "id", "名称/标题", "当前状态", "归属/备注"],
            [
                [
                    row["key"],
                    row["id"],
                    row["label"],
                    row["state"],
                    ", ".join(f"{k}={v}" for k, v in (row.get("extra") or {}).items() if v is not None)[:200],
                ]
                for row in rows
            ],
        ))
        lines.append("")
    trade_rows = [row for row in ctx.inventory if row["kind"] == "trade"]
    if trade_rows:
        lines.append("### 7.5 交易")
        lines.append("")
        lines.append(_table(
            ["key", "id", "当前状态", "买方/卖方"],
            [
                [
                    row["key"],
                    row["id"],
                    row["state"],
                    f"{(row.get('extra') or {}).get('buyer', '')} / {(row.get('extra') or {}).get('seller', '')}",
                ]
                for row in trade_rows
            ],
        ))
        lines.append("")
    for kind, title in [("case", "管理事项"), ("report", "举报"), ("notification", "通知"), ("conversation", "IM 会话"), ("review", "评价"), ("favorite", "收藏"), ("comment", "评论")]:
        rows = [row for row in ctx.inventory if row["kind"] == kind]
        if not rows:
            continue
        lines.append(f"### 7.6 {title}（{kind}）")
        lines.append("")
        lines.append(_table(
            ["key", "id", "名称/说明", "状态", "备注"],
            [
                [
                    row["key"],
                    row["id"],
                    row["label"],
                    row["state"],
                    ", ".join(f"{k}={v}" for k, v in (row.get("extra") or {}).items())[:200],
                ]
                for row in rows
            ],
        ))
        lines.append("")

    states = Counter()
    for row in ctx.inventory:
        if row["kind"] == "product":
            states[("product", row["state"])] += 1
        if row["kind"] == "trade":
            states[("trade", row["state"])] += 1
        if row["kind"] == "case":
            states[("case", row["state"])] += 1
    if states:
        lines.append("### 7.7 状态分布")
        lines.append("")
        lines.append(_table(["对象", "状态", "数量"], [[k[0], k[1], v] for k, v in sorted(states.items())]))
        lines.append("")

    lines.append("## 8. 证据边界与说明")
    lines.append("")
    lines.append("- 所有业务对象、图片、消息、通知、事项与状态转换均通过真实运行后端的 HTTP 接口产生；数据保留在开发库 `var/db/app.db` 与 `var/storage/`。")
    lines.append("- 图片使用真实 multipart 上传到开发存储，商品图与举报证据图均通过签名 URL 读取校验；图片为本地生成的示意素材，不代表真实物品照片。")
    lines.append("- 单方确认满 7 天超时：因无法等待真实 7 天，p08 仅把持久化计时起点前移以模拟时间流逝；超时识别、状态转异常、冻结、事项生成、通知及后续处置由真实后台扫描与业务接口完成。")
    lines.append("- 冻结暂停计时验证同样基于计时起点前移，并核对冻结期间扫描不转异常、解冻后按剩余时间续算。")
    lines.append("- 并发/重复提交验证由测试线程并发调用真实接口，不保证覆盖全部竞态窗口。")
    lines.append("- 本报告不覆盖前端页面人工验收、真实邮件、生产数据库/对象存储、真实手机与网络弱网；不将自动化通过写成人工验收。")
    if ctx.notes or refresh_notes:
        lines.append("")
        lines.append("### 8.1 运行备注")
        lines.append("")
        for note in ctx.notes:
            lines.append(f"- {note}")
        for note in refresh_notes:
            lines.append(f"- {note}")
    lines.append("")
    lines.append("## 9. 结束状态复核")
    lines.append("")
    lines.append("运行结束后通过只读接口重新读取清单对象状态；复核不改变业务数据，失败仅记录备注。")
    lines.append("")
    if refresh_notes:
        lines.append(_table(["复核备注"], [[n] for n in refresh_notes]))
    else:
        lines.append("清单对象状态复核完成，未记录异常。")
    lines.append("")
    return "\n".join(lines)
