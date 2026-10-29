"""[p08] 单方确认超时与异常交易（US-14；SC-09）。

覆盖范围：
- 真实冻结暂停计时（D-51/SC-09-10）：进行中且已有单方完成确认的交易，由认领管理员凭
  “与本交易相关的商品举报事项”真实冻结 → 核对 confirm_wait_paused_at 与剩余秒数 →
  仅把 trades.confirm_wait_started_at 前移 8 天（不触碰暂停字段）→ 等真实后台扫描 ≥1
  个周期仍 in_progress/未转异常 → 解冻 → 核对剩余续算、paused 清空、started_at 重锚。
- 超时转异常（US-14-AC-01/SC-09-01）：单方确认等待起点前移后由真实后台扫描转为
  abnormal+frozen、清空计时、生成 ABNORMAL_TRADE 事项、双方 trade_abnormal 通知、
  锁单保持且不自动完成/取消。
- 异常处置（US-14-AC-03/05/06/07/SC-09-03/05/06/07/08）：认领异常事项、处置沟通、
  管理员有依据 adjust 恢复进行中（保留有效约定、清当前确认、恢复不启动计时、不解冻）→
  仅解除冻结 → adjust 终止（解冻/归档/商品默认下架/通知/transitions 留痕）→ 事项处置。
- D-48（US-14-AC-08/SC-09-09）：同商品旧交易已结束、新交易仍锁单时恢复旧交易 → 409，
  且双方交易、商品、锁单、分支及限制均无副作用；同状态调整 409、非法目标状态 422。
- D-50（SC-09-04）：冻结期间双方交易操作与双方间 IM 禁发、第三方会话不受影响；
  仅冻结用户不能发布/下架/上架但可编辑无关商品。
- US-14-AC-02：等待期进入争议视为回应，原计时结束；恢复进行中不启动计时。
- 事项样本：异常事项保留“待认领（未认领）”与“已认领并处置”两种。

证据边界（强制说明）：
1. 本阶段唯一不通过 HTTP 接口完成的操作是“时间流逝模拟”：只把 `trades.confirm_wait_started_at`
   前移 8 天。其余全部——超时阈值判断、后台扫描识别、状态转换（in_progress→abnormal）、
   冻结、事项生成、通知、认领、问询、管理员调整、解冻/归档/商品下架——都由真实运行后端与
   真实接口完成，本阶段不直接修改任何其它数据库字段。
2. 冻结暂停场景下前移起点时**不触碰** confirm_wait_paused_at / confirm_wait_remaining_seconds，
   以免伪造暂停状态；暂停保存、扫描跳过、解冻续算全部由真实服务完成。
3. 轮询上限 180s 以适配最终 8000 实例默认 60s 扫描间隔；自测实例用 3s 间隔加速。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from e2e_support import (
    admin_case_detail,
    admin_claim_case,
    admin_list_cases,
    backdate_confirm_wait,
    db_connect,
    db_query_one,
    ensure_account,
    upload_image,
    wait_trade_status,
)

PHASE_ID = "p08"

SEED_ACCOUNTS = [
    ("admin", "admin@campus.edu", "admin123456", "平台管理员"),
    ("zhang", "zhang@campus.edu", "secret123", "张同学"),
    ("li", "li@campus.edu", "secret123", "李同学"),
    ("wang", "wang@campus.edu", "secret123", "王同学"),
]
NEW_ACCOUNTS = [
    ("chen", "chen@campus.edu", "secret123", "陈同学"),
    ("liu", "liu@campus.edu", "secret123", "刘同学"),
    ("wu", "wu@campus.edu", "secret123", "吴同学"),
    ("sun", "sun@campus.edu", "secret123", "孙同学"),
]

AGREEMENT = {
    "delivery_time": "2026-11-02 18:00",
    "delivery_location": "图书馆西门",
    "delivery_method": "当面交付",
    "amount_cents": 6000,
    "payment_method": "支付宝",
    "payment_timing": "当面支付",
}
LOCKING = ("in_progress", "disputed", "abnormal")
ENDED = ("completed", "terminated")
TIMEOUT_SECONDS = 7 * 24 * 60 * 60
SCAN_WAIT_TIMEOUT = 180.0


# ---------------------------------------------------------------------------
# 基础辅助（真实 HTTP 造数）
# ---------------------------------------------------------------------------
def _ensure_accounts(api, ctx) -> None:
    for key, email, password, name in SEED_ACCOUNTS + NEW_ACCOUNTS:
        ensure_account(api, ctx, key, email, name, password=password)


def _active_category(api, ctx, preferred: str = "电子产品") -> int:
    cats = api.get("/categories", token=ctx.token("chen"), expected=200).json()
    for cat in cats:
        if cat.get("name") == preferred and cat.get("status") == "active":
            return cat["id"]
    for cat in cats:
        if cat.get("status") == "active":
            return cat["id"]
    raise AssertionError("当前没有任何可用分类，无法发布商品")


def _upload_asset(api, ctx, token: str, asset_name: str, namespace: str, key: str) -> dict:
    data = upload_image(api, token, asset_name, namespace=namespace)
    ctx.remember_item(
        "file", key, data["key"], f"{namespace}:{asset_name}", namespace, {"url": data["url"]}
    )
    return data


def _pending_product_case(api, ctx, product_id: int) -> dict:
    cases = admin_list_cases(api, ctx, status="pending", case_type="product_review")
    for case in cases:
        if case.get("product_id") == product_id:
            return case
    raise AssertionError(f"共享池中没有商品 #{product_id} 的待审核事项")


def _approve_product(api, ctx, product_id: int) -> None:
    case = _pending_product_case(api, ctx, product_id)
    admin_claim_case(api, ctx, case["id"])
    api.post(
        f"/admin/products/cases/{case['id']}/review",
        token=ctx.token("admin"),
        json_body={"result": "approved"},
        expected=200,
    )


def _publish_listed(api, ctx, seller: str, product_key: str, title: str, price: int,
                    asset_name: str, category_id: int,
                    description: str = "真实接口构造的超时/冻结阶段样本商品") -> dict:
    token = ctx.token(seller)
    image = _upload_asset(api, ctx, token, asset_name, "product", f"image_{product_key}")
    product = api.post(
        "/products",
        token=token,
        json_body={
            "title": title,
            "description": description,
            "price_cents": price,
            "image_keys": [image["key"]],
            "tags": [{"category_id": category_id}],
        },
        expected=200,
    ).json()
    _approve_product(api, ctx, product["id"])
    product = api.get(f"/products/{product['id']}", token=token, expected=200).json()
    ctx.remember_product(product_key, product, seller, state=product["status"])
    return product


def _ensure_listed_product(api, ctx, product_key: str, seller: str, title: str, price: int,
                           asset_name: str, category_id: int) -> dict:
    existing = ctx.products.get(product_key)
    if existing and existing.get("id"):
        token = ctx.token(seller)
        resp = api.get(f"/products/{existing['id']}", token=token)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "listed" and not data.get("display_restricted"):
                ctx.remember_product(product_key, data, seller, state="listed")
                return data
            if data.get("status") == "delisted":
                relist = api.post(f"/products/{data['id']}/relist", token=token)
                if relist.status_code == 200 and relist.json().get("status") == "listed":
                    data = relist.json()
                    ctx.remember_product(product_key, data, seller, state="listed")
                    return data
            if data.get("status") == "pending_review":
                _approve_product(api, ctx, data["id"])
                data = api.get(f"/products/{data['id']}", token=token, expected=200).json()
                if data.get("status") == "listed":
                    ctx.remember_product(product_key, data, seller, state="listed")
                    return data
    return _publish_listed(api, ctx, seller, product_key, title, price, asset_name, category_id)


def _trade_or_none(api, ctx, tid: int, viewer: str) -> dict | None:
    resp = api.get(f"/trades/{tid}", token=ctx.token(viewer))
    return resp.json() if resp.status_code == 200 else None


def _trade(api, ctx, tid: int, viewer: str) -> dict:
    return api.get(f"/trades/{tid}", token=ctx.token(viewer), expected=200).json()


def _create_request(api, ctx, buyer: str, seller: str, product_id: int, trade_key: str,
                    note: str | None = None) -> int:
    body = {"product_id": product_id}
    if note:
        body["note"] = note
    tid = api.post("/trades/requests", token=ctx.token(buyer), json_body=body, expected=200).json()["id"]
    ctx.remember_trade(trade_key, {"id": tid}, buyer, seller, state="pending_acceptance")
    return tid


def _accept(api, ctx, tid: int, seller: str) -> None:
    api.post(f"/trades/{tid}/accept", token=ctx.token(seller), expected=200)


def _agree(api, ctx, tid: int, proposer: str, confirmer: str) -> None:
    aid = api.post(
        f"/trades/{tid}/agreements", token=ctx.token(proposer), json_body=AGREEMENT, expected=200
    ).json()["id"]
    api.post(f"/trades/{tid}/agreements/{aid}/confirm", token=ctx.token(confirmer), expected=200)


def _confirm(api, ctx, tid: int, user: str) -> None:
    api.post(f"/trades/{tid}/confirmations", token=ctx.token(user), json_body={}, expected=200)


def _ensure_single_confirm_trade(api, ctx, trade_key: str, buyer: str, seller: str,
                                 product_factory) -> tuple[int, int]:
    """确保存在“进行中 + 已确认约定 + 仅一方完成确认（等待计时已开始）”的交易。

    返回 (trade_id, product_id)。优先复用 ctx 中同 key 且仍在进行中的交易（p05 可能已构造）。
    """
    existing = ctx.trades.get(trade_key)
    if existing and existing.get("id"):
        data = _trade_or_none(api, ctx, int(existing["id"]), buyer)
        if data is not None and data.get("status") == "in_progress":
            if (
                not (data.get("my_confirmed") or data.get("other_party_confirmed"))
                and not data.get("frozen")
            ):
                if data.get("agreement_stage") == "awaiting_agreement":
                    pending = data.get("pending_agreement")
                    if pending:
                        confirmer = seller if pending["proposer_id"] == ctx.accounts[buyer]["id"] else buyer
                        api.post(
                            f"/trades/{data['id']}/agreements/{pending['id']}/confirm",
                            token=ctx.token(confirmer), expected=200,
                        )
                    else:
                        _agree(api, ctx, data["id"], buyer, seller)
                _confirm(api, ctx, data["id"], buyer)
                data = _trade(api, ctx, data["id"], buyer)
            if data.get("confirm_wait_started_at") is not None:
                ctx.remember_trade(trade_key, {"id": data["id"]}, buyer, seller, state="in_progress")
                return int(data["id"]), int(data["product_id"])
    product = product_factory()
    tid = _create_request(api, ctx, buyer, seller, product["id"], trade_key)
    _accept(api, ctx, tid, seller)
    _agree(api, ctx, tid, buyer, seller)
    _confirm(api, ctx, tid, buyer)
    ctx.remember_trade(trade_key, {"id": tid}, buyer, seller, state="in_progress")
    return tid, int(product["id"])


def _ensure_completed_trade(api, ctx, trade_key: str, buyer: str, seller: str,
                            product_factory) -> tuple[int, dict]:
    existing = ctx.trades.get(trade_key)
    if existing and existing.get("id"):
        data = _trade_or_none(api, ctx, int(existing["id"]), buyer)
        if data is not None and data.get("status") == "completed":
            ctx.remember_trade(trade_key, {"id": data["id"]}, buyer, seller, state="completed")
            return int(data["id"]), data
    product = product_factory()
    tid = _create_request(api, ctx, buyer, seller, product["id"], trade_key)
    _accept(api, ctx, tid, seller)
    _agree(api, ctx, tid, buyer, seller)
    _confirm(api, ctx, tid, buyer)
    _confirm(api, ctx, tid, seller)
    data = _trade(api, ctx, tid, buyer)
    ctx.remember_trade(trade_key, {"id": tid}, buyer, seller, state=data["status"])
    return tid, data


def _notifications(api, token: str, *, pages: int = 3, page_size: int = 50) -> list[dict]:
    items: list[dict] = []
    for page in range(1, pages + 1):
        data = api.get(
            "/notifications", token=token, params={"page": page, "page_size": page_size}, expected=200
        ).json()
        items.extend(data.get("items") or [])
        if len(data.get("items") or []) < page_size:
            break
    return items


def _notif(items: list[dict], ntype: str, link_id: int | None = None) -> list[dict]:
    return [n for n in items if n.get("type") == ntype and (link_id is None or n.get("link_id") == link_id)]


def _report_case_id(api, ctx, report_id: int) -> int:
    rows = api.get("/admin/reports", token=ctx.token("admin"), params={"status": "all"},
                   expected=200).json()
    for row in rows:
        if row.get("id") == report_id and row.get("case_id"):
            return int(row["case_id"])
    for case in admin_list_cases(api, ctx, status="all", case_type="report"):
        if case.get("report_id") == report_id:
            return int(case["id"])
    raise AssertionError(f"未找到举报 #{report_id} 对应的事项")


def _create_report(api, token: str, target_type: str, target_id: int, reason: str) -> dict:
    return api.post("/reports", token=token, json_body={
        "target_type": target_type, "target_id": target_id, "reason": reason}, expected=201).json()


def _remember_report(ctx, key: str, data: dict, state: str) -> dict:
    """登记举报对象并记录当前状态（e2e_support.Ctx.remember_report 不支持 state 关键字）。"""
    payload = dict(data)
    payload["status"] = state
    return ctx.remember_report(key, payload)


def _abnormal_case_of_trade(api, ctx, trade_id: int, *, status: str = "pending") -> dict | None:
    for case in admin_list_cases(api, ctx, status=status, case_type="abnormal_trade"):
        if case.get("trade_id") == trade_id:
            return case
    return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _shift_started_only(db_path: str, trade_id: int, seconds: int) -> tuple[str, str]:
    """【证据边界】仅前移 trades.confirm_wait_started_at（模拟时间流逝）。

    冻结暂停场景必须保留 confirm_wait_paused_at / confirm_wait_remaining_seconds，
    因此这里不用 e2e_support.backdate_confirm_wait（它会清空暂停字段）；除本字段外
    不修改任何其它列。返回 (前移前起点, 前移后起点)。
    """
    conn = db_connect(db_path)
    try:
        row = conn.execute(
            "SELECT confirm_wait_started_at FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if row is None or not row[0]:
            raise AssertionError(f"交易 #{trade_id} 没有 confirm_wait_started_at，无法前移")
        before = row[0]
        new_start = (datetime.now(UTC) - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S.%f")
        conn.execute(
            "UPDATE trades SET confirm_wait_started_at = ? WHERE id = ?", (new_start, trade_id)
        )
        conn.commit()
        return before, new_start
    finally:
        conn.close()


def _wait_scan_convert(api, ctx, trade_id: int, viewer: str, freeze_trade_id: int,
                       freeze_viewer: str, *, timeout: float = SCAN_WAIT_TIMEOUT) -> tuple[dict, list[dict]]:
    """等待真实后台扫描把等待超时交易转为 abnormal。

    同时采样冻结暂停交易状态，证明“扫描确实发生过”期间它仍 in_progress/未转异常
    （扫描查询会跳过 frozen 交易，因此冻结交易不会被误转）。
    返回 (abnormal 交易详情, 冻结交易快照列表)。
    """
    deadline = time.monotonic() + timeout
    snapshots: list[dict] = []
    while time.monotonic() < deadline:
        data = _trade_or_none(api, ctx, trade_id, viewer)
        if data is not None and data.get("status") == "abnormal":
            return data, snapshots
        frozen = _trade_or_none(api, ctx, freeze_trade_id, freeze_viewer)
        if frozen is not None:
            snapshots.append({
                "status": frozen.get("status"),
                "frozen": frozen.get("frozen"),
                "paused_at": frozen.get("confirm_wait_paused_at"),
                "remaining": frozen.get("confirm_wait_remaining_seconds"),
                "started_at": frozen.get("confirm_wait_started_at"),
            })
        time.sleep(2.0)
    raise AssertionError(f"交易 #{trade_id} 未在 {timeout:.0f}s 内被真实扫描转为 abnormal")





def _dedupe_inventory(ctx) -> None:
    """同一 (kind,key) 多次登记时保留最后一条，避免报告数据清单重复计数。"""
    latest: dict[tuple, int] = {}
    order: list[dict] = []
    for row in ctx.inventory:
        key = (row.get("kind"), row.get("key"))
        if key in latest:
            order[latest[key]] = row
        else:
            latest[key] = len(order)
            order.append(row)
    ctx.inventory[:] = order


def _refresh_report_states(api, ctx) -> None:
    """用管理端只读举报列表刷新举报对象最终状态（保证报告数据清单状态准确）。"""
    resp = api.get("/admin/reports", token=ctx.token("admin"), params={"status": "all"})
    if resp.status_code != 200:
        return
    states = {int(row["id"]): row.get("status", "") for row in resp.json() if row.get("id") is not None}
    for row in ctx.inventory:
        if row.get("kind") == "report" and row.get("id") in states:
            row["state"] = states[row["id"]]
    for item in ctx.reports.values():
        report_id = item.get("id")
        if report_id in states:
            item["status"] = states[report_id]

# ---------------------------------------------------------------------------
# 阶段主流程
# ---------------------------------------------------------------------------
def run(ctx, api, rec):
    _ensure_accounts(api, ctx)
    category_id = _active_category(api, ctx)
    db_path = str(ctx.db_path) if ctx.db_path else ""
    if not db_path or not Path(db_path).exists():
        rec.skip("US-14-AC-01_时间加速", us="US-14", sc="SC-09-01",
                 desc="单方确认 7 天超时转异常（需要 --db-path 指向真实库以模拟时间流逝）",
                 reason="未提供可用的 --db-path，无法执行计时起点前移；真实扫描链路未覆盖")
        ctx.note("p08 未执行：缺少 --db-path，无法进行时间加速；异常/冻结链路未验证。")
        return

    # -----------------------------------------------------------------
    # A. 准备样本：真实发布+审核+交易构造（全部通过 HTTP）
    # -----------------------------------------------------------------
    p_freeze = _ensure_listed_product(
        api, ctx, "p_freeze_pause", "wang", "宿舍电热水壶（阶段冻结暂停样本）", 7000,
        "product_lamp.jpg", category_id,
    )
    p_li_unrelated = _ensure_listed_product(
        api, ctx, "p_li_unrelated", "li", "台灯（阶段无关可编辑样本）", 2500,
        "product_mug.jpg", category_id,
    )
    p_li_delist = _publish_listed(
        api, ctx, "li", "p_li_delist", "雨伞（阶段上下架限制样本）", 1500,
        "product_notes.jpg", category_id,
    )
    # 冻结前先真实下架，供“冻结期禁止上架 / 解冻后恢复上架资格”对照
    api.post(f"/products/{p_li_delist['id']}/delist", token=ctx.token("li"), expected=200)
    ctx.update_product("p_li_delist", state="delisted")
    p_abnormal_open = _ensure_listed_product(
        api, ctx, "p_abnormal_open", "liu", "桌面收纳柜（阶段超时转异常样本）", 9000,
        "product_notes.jpg", category_id,
    )
    p_abnormal_disposed = _ensure_listed_product(
        api, ctx, "p_abnormal_disposed", "zhang", "骑行头盔（阶段异常处置样本）", 8000,
        "product_racket.jpg", category_id,
    )
    p_d50_other = _ensure_listed_product(
        api, ctx, "p_d50_other", "sun", "篮球（阶段第三方商品样本）", 4500,
        "product_bike.jpg", category_id,
    )
    p_dispute = _ensure_listed_product(
        api, ctx, "p_dispute_clear", "li", "计算器（阶段争议清计时样本）", 3500,
        "product_second.jpg", category_id,
    )
    p_d48 = _ensure_listed_product(
        api, ctx, "p_d48_a", "liu", "旧交易恢复冲突商品（阶段 D-48 样本）", 11000,
        "product_camera.jpg", category_id,
    )

    # --- 交易样本 ---
    tid_freeze, p_freeze_id = _ensure_single_confirm_trade(
        api, ctx, "t_freeze_pause", "li", "wang", lambda: p_freeze
    )
    tid_abnormal_open, _ = _ensure_single_confirm_trade(
        api, ctx, "t_abnormal_open", "wu", "liu", lambda: p_abnormal_open
    )
    tid_abnormal_disposed, _ = _ensure_single_confirm_trade(
        api, ctx, "t_abnormal_disposed", "chen", "zhang", lambda: p_abnormal_disposed
    )
    # 争议清计时样本：已有单方确认 → 争议 → 原计时结束 → 双方确认解决 → 恢复不启动计时
    tid_dispute: int | None = None
    existing_dispute = ctx.trades.get("t_dispute_clear")
    if existing_dispute and existing_dispute.get("id"):
        data = _trade_or_none(api, ctx, int(existing_dispute["id"]), "wu")
        if data is not None and data.get("status") in ("in_progress", "disputed"):
            tid_dispute = int(data["id"])
    if tid_dispute is None:
        tid_dispute = _create_request(api, ctx, "wu", "li", p_dispute["id"], "t_dispute_clear")
        _accept(api, ctx, tid_dispute, "li")
        _agree(api, ctx, tid_dispute, "wu", "li")
        _confirm(api, ctx, tid_dispute, "wu")
        ctx.remember_trade("t_dispute_clear", {"id": tid_dispute}, "wu", "li", state="in_progress")

    # D-48：同商品旧交易已完成、新交易仍锁单
    def _d48_product_factory():
        return _ensure_listed_product(
            api, ctx, "p_d48_a", "liu", "旧交易恢复冲突商品（阶段 D-48 样本）", 11000,
            "product_camera.jpg", category_id,
        )

    d48_pair: tuple[int, int, int] | None = None
    old_existing = ctx.trades.get("t_d48_old")
    new_existing = ctx.trades.get("t_d48_new")
    if old_existing and new_existing and old_existing.get("id") and new_existing.get("id"):
        old_data = _trade_or_none(api, ctx, int(old_existing["id"]), "zhang")
        new_data = _trade_or_none(api, ctx, int(new_existing["id"]), "chen")
        if (old_data is not None and old_data.get("status") == "completed"
                and new_data is not None and new_data.get("status") in LOCKING
                and old_data.get("product_id") == new_data.get("product_id")):
            d48_pair = (int(old_data["id"]), int(new_data["id"]), int(old_data["product_id"]))
    if d48_pair is None:
        p_d48 = _d48_product_factory()
        tid_old, old_data = _ensure_completed_trade(
            api, ctx, "t_d48_old", "zhang", "liu", lambda: p_d48
        )
        api.post(f"/products/{p_d48['id']}/relist", token=ctx.token("liu"), expected=200)
        tid_new = _create_request(api, ctx, "chen", "liu", p_d48["id"], "t_d48_new",
                                  note="D-48 新交易锁单")
        _accept(api, ctx, tid_new, "liu")
        ctx.remember_trade("t_d48_new", {"id": tid_new}, "chen", "liu", state="in_progress")
        d48_pair = (tid_old, tid_new, int(p_d48["id"]))
    tid_d48_old, tid_d48_new, p_d48_id = d48_pair

    # 冻结依据：对冻结交易的商品提交真实举报 → 管理员认领 → 作为 BR-27/34 关联事项
    report_freeze = _create_report(api, ctx.token("chen"), "product", p_freeze_id,
                                   "商品描述与实物不符（冻结依据）")
    _remember_report(ctx, "r_freeze_basis", {"id": report_freeze["id"], "target_type": "product",
                                           "reason": "商品描述与实物不符（冻结依据）"}, "processing")
    case_freeze = _report_case_id(api, ctx, report_freeze["id"])
    admin_claim_case(api, ctx, case_freeze)
    ctx.remember_case("case_freeze", {"id": case_freeze, "title": "举报事项：商品",
                                      "case_type": "report", "status": "processing"})
    ctx.items["case_freeze_id"] = case_freeze

    # 双方普通私聊（冻结期间应禁发）与第三方普通私聊（不受影响）
    conv_pair = api.post("/conversations/normal", token=ctx.token("li"),
                         json_body={"peer_user_id": ctx.accounts["wang"]["id"]}, expected=201).json()["id"]
    conv_third = api.post("/conversations/normal", token=ctx.token("li"),
                          json_body={"peer_user_id": ctx.accounts["sun"]["id"]}, expected=201).json()["id"]
    api.post(f"/conversations/{conv_third}/messages", token=ctx.token("sun"),
             json_body={"content": "冻结前的第三方会话基线"}, expected=200)
    ctx.remember_item("conversation", "conv_li_wang", conv_pair, "li↔wang 普通私聊", "normal")
    ctx.remember_item("conversation", "conv_li_sun", conv_third, "li↔sun 第三方私聊", "normal")

    # -----------------------------------------------------------------
    # B. US-14-AC-02：等待期进入争议 → 原计时结束；恢复不启动计时
    # -----------------------------------------------------------------
    tid_dispute = int(tid_dispute)
    with rec.step(
        "US-14-AC-02_争议结束计时",
        us="US-14", sc="SC-06-07",
        desc="单方确认等待中发起争议视为回应：原等待计时结束；双方确认解决恢复进行中后不启动计时",
        expected="dispute 后 status=disputed 且 confirm_wait_started_at=null；resolve 双方确认后 in_progress 且不恢复计时/当前确认清空",
    ):
        before = _trade(api, ctx, tid_dispute, "wu")
        if before["status"] == "in_progress":
            rec.must(before["confirm_wait_started_at"] is not None, "争议前存在等待计时")
            api.post(f"/trades/{tid_dispute}/disputes", token=ctx.token("wu"),
                     json_body={"description": "等待期间对方失联，申请平台介入"}, expected=200)
        disputed = _trade(api, ctx, tid_dispute, "wu")
        rec.must_eq(disputed["status"], "disputed", "争议状态")
        rec.must_eq(disputed["confirm_wait_started_at"], None, "争议清空原等待计时")
        # 双方确认解决（普通用户路径）
        api.post(f"/trades/{tid_dispute}/disputes/resolve", token=ctx.token("wu"),
                 json_body={"reason": "已沟通一致"}, expected=200)
        api.post(f"/trades/{tid_dispute}/disputes/resolve", token=ctx.token("li"),
                 json_body={"reason": "确认解决"}, expected=200)
        restored = _trade(api, ctx, tid_dispute, "wu")
        rec.must_eq(restored["status"], "in_progress", "争议解决恢复进行中")
        rec.must_eq(restored["confirm_wait_started_at"], None, "恢复不启动计时")
        rec.must_eq(restored["my_confirmed"], False, "恢复清空当前完成确认（本人）")
        rec.must_eq(restored["other_party_confirmed"], False, "恢复清空当前完成确认（对方）")
        ctx.update_trade("t_dispute_clear", state="in_progress")
        dispute_case = None
        for case in admin_list_cases(api, ctx, status="all", case_type="trade_dispute"):
            if case.get("trade_id") == tid_dispute:
                dispute_case = case
                break
        rec.must(dispute_case is not None, "争议事项已自动生成（共享池样本）")
        ctx.remember_case("case_dispute", {"id": dispute_case["id"],
                                           "title": "交易争议事项（阶段样本）",
                                           "case_type": "trade_dispute",
                                           "status": dispute_case["status"]})

    # -----------------------------------------------------------------
    # C. 冻结前置权限 + 真实冻结（暂停计时保存 remaining）
    # -----------------------------------------------------------------
    with rec.step(
        "US-14-AC-03_未认领交易访问",
        us="US-14", sc="SC-09-03",
        desc="管理员无与该交易相关的已认领事项时，不能查看/冻结该私人交易",
        expected="403 管理员须先认领与本交易相关的处置事项",
    ):
        resp = api.get(f"/admin/trades/{tid_abnormal_open}", token=ctx.token("admin"))
        rec.must_eq(resp.status_code, 403, "无相关事项读取私人交易")
        rec.must("认领" in (resp.json().get("detail") or ""), "拒绝文案")
        resp = api.post(f"/admin/trades/{tid_abnormal_open}/freeze", token=ctx.token("admin"),
                        json_body={"reason": "无依据冻结"})
        rec.must_eq(resp.status_code, 403, "无依据冻结交易")

    with rec.step(
        "US-14-AC-04d_冻结暂停计时",
        us="US-14", sc="SC-09-10",
        desc="进行中已单方确认交易被认领管理员有依据冻结：保存暂停时刻与剩余秒数、通知双方、留痕",
        expected="freeze 200；frozen=true；paused_at 非空；remaining>0；started_at 不变；trade_frozen transition；双方通知",
    ):
        before = _trade(api, ctx, tid_freeze, "li")
        rec.must_eq(before["status"], "in_progress", "冻结前交易状态")
        rec.must_eq(before["my_confirmed"], True, "冻结前已有单方完成确认")
        rec.must(before["confirm_wait_started_at"] is not None, "冻结前已开始等待计时")
        resp = api.post(f"/admin/trades/{tid_freeze}/freeze", token=ctx.token("admin"),
                        json_body={"reason": "核查商品举报期间冻结交易进度", "case_id": case_freeze},
                        expected=200)
        rec.must("已冻结" in (resp.json().get("detail") or ""), "冻结成功文案")
        frozen = _trade(api, ctx, tid_freeze, "li")
        rec.must_eq(frozen["frozen"], True, "交易冻结标记")
        rec.must_eq(frozen["frozen_reason"], "核查商品举报期间冻结交易进度", "冻结原因")
        rec.must_eq(frozen["status"], "in_progress", "冻结不改变交易状态")
        rec.must(frozen["confirm_wait_paused_at"] is not None, "保存暂停时刻")
        rec.must(int(frozen["confirm_wait_remaining_seconds"]) > 0, "保存剩余等待秒数")
        rec.must_eq(frozen["confirm_wait_started_at"], before["confirm_wait_started_at"],
                    "冻结不改写原计时起点")
        transitions = api.get(f"/trades/{tid_freeze}/transitions", token=ctx.token("li"),
                              expected=200).json()
        rec.must(any(t["trigger"] == "trade_frozen" and t["from_status"] == "in_progress"
                     and t["to_status"] == "in_progress" for t in transitions), "冻结状态转移留痕")
        rec.must(bool(_notif(_notifications(api, ctx.token("li")), "trade_frozen", tid_freeze)),
                 "冻结通知买方")
        rec.must(bool(_notif(_notifications(api, ctx.token("wang")), "trade_frozen", tid_freeze)),
                 "冻结通知卖方")
        ctx.items["paused_remaining"] = int(frozen["confirm_wait_remaining_seconds"])
        ctx.items["frozen_started_at"] = frozen["confirm_wait_started_at"]
        ctx.items["paused_at"] = frozen["confirm_wait_paused_at"]

    with rec.step(
        "US-14-AC-03_冻结依据相关性",
        us="US-14", sc="SC-09-03",
        desc="冻结/解冻必须由与本交易真正相关的事项认领管理员执行（商品审核事项不算依据）",
        expected="用无关事项冻结 → 403 关联事项与该交易无关；解冻也应校验依据",
    ):
        # 找一个本阶段自己认领过的商品审核事项（与私人交易无关）
        review_cases = admin_list_cases(api, ctx, status="disposed", case_type="product_review")
        unrelated_case = review_cases[0]["id"] if review_cases else None
        rec.must(unrelated_case is not None, "存在可用的商品审核事项作为无关依据")
        resp = api.post(f"/admin/trades/{tid_abnormal_open}/freeze", token=ctx.token("admin"),
                        json_body={"reason": "错误依据冻结", "case_id": unrelated_case})
        rec.must_eq(resp.status_code, 403, "无关事项不能冻结交易")
        rec.must("无关" in (resp.json().get("detail") or ""), "无关依据拒绝文案")
        resp = api.get(f"/admin/trades/{tid_abnormal_open}", token=ctx.token("admin"),
                       params={"case_id": unrelated_case})
        rec.must_eq(resp.status_code, 403, "无关事项不能查看交易")

    # -----------------------------------------------------------------
    # D. D-50：冻结期间双方交易操作/IM 限制与第三方隔离
    # -----------------------------------------------------------------
    with rec.step(
        "US-14-AC-04a_冻结期交易操作拒绝",
        us="US-14", sc="SC-09-04",
        desc="冻结期间双方交易操作暂停：取消、完成确认、发起新请求均拒绝，历史只读",
        expected="cancel/confirmations 403 交易已被冻结；新购买请求 403 账户存在有效交易冻结",
    ):
        li_me = api.get("/auth/me", token=ctx.token("li"), expected=200).json()
        wang_me = api.get("/auth/me", token=ctx.token("wang"), expected=200).json()
        rec.must_eq(li_me.get("has_frozen_trade"), True, "买方存在有效冻结交易")
        rec.must_eq(wang_me.get("has_frozen_trade"), True, "卖方存在有效冻结交易")
        resp = api.post(f"/trades/{tid_freeze}/cancel", token=ctx.token("li"), json_body={})
        rec.must_eq(resp.status_code, 403, "冻结期买方取消")
        resp = api.post(f"/trades/{tid_freeze}/confirmations", token=ctx.token("wang"), json_body={})
        rec.must_eq(resp.status_code, 403, "冻结期完成确认")
        resp = api.post("/trades/requests", token=ctx.token("li"),
                        json_body={"product_id": p_d50_other["id"]})
        rec.must_eq(resp.status_code, 403, "冻结期发起新购买请求")
        rec.must("冻结" in (resp.json().get("detail") or ""), "冻结期交易拒绝文案")
        # 历史与进度只读保留
        readonly = _trade(api, ctx, tid_freeze, "li")
        rec.must_eq(readonly["status"], "in_progress", "冻结期交易历史只读可见")
        rec.must_eq(readonly["conversation_archived"], False, "冻结分支未归档（历史可读）")

    with rec.step(
        "SC-09-07_冻结期禁止取消",
        us="US-14", sc="SC-09-07",
        desc="冻结期间双方不得取消或预存取消意愿（仅保留读取与管理沟通）；管理员有依据终止后解除锁单",
        expected="冻结中发起取消/同意取消均 403 交易已被冻结；终止联动在异常处置链路验证",
    ):
        resp = api.post(f"/trades/{tid_freeze}/cancel", token=ctx.token("li"), json_body={})
        rec.must_eq(resp.status_code, 403, "冻结期发起取消")
        rec.must("冻结" in (resp.json().get("detail") or ""), "冻结取消拒绝文案")
        resp = api.post(f"/trades/{tid_freeze}/cancel/confirm", token=ctx.token("wang"), json_body={})
        rec.must_eq(resp.status_code, 403, "冻结期同意取消")
        rec.must_eq(_trade(api, ctx, tid_freeze, "li")["cancel_requested_by"], None,
                    "冻结期未预存取消意愿")

    with rec.step(
        "D-50_冻结用户写限制",
        us="US-14", sc="SC-09-04",
        desc="仅冻结用户不能发布/下架/上架商品，但可编辑无关商品（D-50/BR-33）",
        expected="发布/下架/上架均 403；无关商品合规编辑 200 并写入编辑历史",
    ):
        image_key = (api.get(f"/products/{p_li_unrelated['id']}", token=ctx.token("li"),
                             expected=200).json()["image_keys"] or [""])[0]
        resp = api.post("/products", token=ctx.token("li"), json_body={
            "title": "冻结期发布尝试", "description": "不应成功", "price_cents": 100,
            "image_keys": [image_key], "tags": [{"category_id": category_id}]})
        rec.must_eq(resp.status_code, 403, "冻结用户发布")
        rec.must("冻结" in (resp.json().get("detail") or ""), "冻结发布拒绝文案")
        rec.must_eq(api.post(f"/products/{p_li_unrelated['id']}/delist",
                             token=ctx.token("li")).status_code, 403, "冻结用户主动下架")
        rec.must_eq(api.post(f"/products/{p_li_delist['id']}/relist",
                             token=ctx.token("li")).status_code, 403, "冻结用户重新上架")
        edited = api.patch(f"/products/{p_li_unrelated['id']}", token=ctx.token("li"),
                           json_body={"title": "台灯（阶段无关可编辑样本·已编辑）"}, expected=200)
        rec.must_eq(edited.json()["title"], "台灯（阶段无关可编辑样本·已编辑）", "冻结期无关商品可编辑")
        ctx.update_product("p_li_unrelated", state="listed")

    with rec.step(
        "US-14-AC-04b_冻结期IM禁发",
        us="US-14", sc="SC-09-04",
        desc="冻结期间双方普通私聊与交易分支均禁发，历史可读",
        expected="双方普通私聊发消息 403；该交易分支发消息 403；历史消息仍可读取",
    ):
        resp = api.post(f"/conversations/{conv_pair}/messages", token=ctx.token("li"),
                        json_body={"content": "冻结期普通私聊尝试"})
        rec.must_eq(resp.status_code, 403, "冻结双方普通私聊禁发")
        rec.must("冻结" in (resp.json().get("detail") or ""), "IM 冻结拒绝文案")
        trade_branch = _trade(api, ctx, tid_freeze, "li")["conversation_id"]
        resp = api.post(f"/conversations/{trade_branch}/messages", token=ctx.token("wang"),
                        json_body={"content": "冻结期交易分支尝试"})
        rec.must_eq(resp.status_code, 403, "冻结交易分支禁发")
        history = api.get(f"/conversations/{trade_branch}", token=ctx.token("li"), expected=200).json()
        rec.must(len(history["messages"]) >= 1, "冻结期仍可读取交易分支历史")

    with rec.step(
        "US-14-AC-04c_第三方会话不受影响",
        us="US-14", sc="SC-09-04",
        desc="冻结只限制该交易双方之间的普通私聊与交易分支，与第三方的会话不受影响",
        expected="li 与 sun 的普通私聊发送/读取 200",
    ):
        api.post(f"/conversations/{conv_third}/messages", token=ctx.token("li"),
                 json_body={"content": "冻结期间与第三方沟通正常"}, expected=200)
        detail = api.get(f"/conversations/{conv_third}", token=ctx.token("sun"), expected=200).json()
        rec.must(any(m["content"] == "冻结期间与第三方沟通正常" for m in detail["messages"]),
                 "第三方会话消息可见")

    # -----------------------------------------------------------------
    # E. 时间加速（仅前移计时起点）→ 真实扫描 → 冻结不转异常 / 解冻续算
    # -----------------------------------------------------------------
    with rec.step(
        "US-14-AC-04e_冻结不计时",
        us="US-14", sc="SC-09-10",
        desc="仅前移 confirm_wait_started_at 8 天，等真实后台扫描 ≥1 周期：冻结交易仍 in_progress、"
             "不转异常，暂停剩余秒数不随自然时间累计",
        expected="扫描周期内冻结交易 status=in_progress/frozen=true；paused_at 与 remaining 保持不变；"
                 "同一扫描周期另一笔同条件未冻结交易转为 abnormal（证明扫描真实发生）",
    ):
        before_row = db_query_one(
            db_path,
            "SELECT confirm_wait_started_at, confirm_wait_paused_at, confirm_wait_remaining_seconds "
            "FROM trades WHERE id = ?", (tid_freeze,),
        )
        rec.must(before_row is not None, "读取冻结交易计时字段")
        started_before, paused_before, remaining_before = before_row
        # 【证据边界】仅前移 confirm_wait_started_at，保留暂停字段
        _, _shifted = _shift_started_only(db_path, tid_freeze, 8 * 86400)
        after_row = db_query_one(
            db_path,
            "SELECT confirm_wait_started_at, confirm_wait_paused_at, confirm_wait_remaining_seconds "
            "FROM trades WHERE id = ?", (tid_freeze,),
        )
        rec.must_eq(after_row[1], paused_before, "前移起点不改暂停时刻")
        rec.must_eq(after_row[2], remaining_before, "前移起点不改剩余秒数")
        rec.must(after_row[0] != started_before, "计时起点已前移（模拟时间流逝）")
        # 另一笔同条件但未冻结交易使用框架时间加速 helper，作为真实扫描探针
        backdate_confirm_wait(db_path, tid_abnormal_open, seconds_ago=8 * 86400)
        converted, snapshots = _wait_scan_convert(
            api, ctx, tid_abnormal_open, "wu", tid_freeze, "li"
        )
        rec.must_eq(converted["status"], "abnormal", "探针交易被真实扫描转异常")
        for snap in snapshots:
            rec.must_eq(snap["status"], "in_progress", "扫描期间冻结交易仍进行中")
            rec.must_eq(snap["frozen"], True, "扫描期间冻结交易保持冻结")
            rec.must_eq(snap["paused_at"], ctx.items["paused_at"], "扫描期间暂停时刻不变")
            rec.must_eq(snap["remaining"], ctx.items["paused_remaining"], "扫描期间剩余等待不变")
        frozen_now = _trade(api, ctx, tid_freeze, "li")
        rec.must_eq(frozen_now["status"], "in_progress", "扫描后冻结交易未转异常")
        rec.must_eq(frozen_now["confirm_wait_paused_at"], ctx.items["paused_at"], "扫描后暂停时刻保持")
        rec.must_eq(int(frozen_now["confirm_wait_remaining_seconds"]),
                    int(ctx.items["paused_remaining"]), "扫描后剩余等待保持")
        ctx.note(
            f"p08 冻结不计时验证：仅前移交易 #{tid_freeze} 的 confirm_wait_started_at 至 8 天前"
            f"（保留暂停字段），另一笔同条件交易 #{tid_abnormal_open} 由真实扫描转 abnormal，"
            f"证明扫描周期内冻结交易未被误转；暂停剩余 {ctx.items['paused_remaining']}s 保持不变。"
        )

    with rec.step(
        "US-14-AC-01a_真实扫描转异常",
        us="US-14", sc="SC-09-01",
        desc="单方确认后有效等待累计超 7 天（起点前移模拟时间流逝），真实后台扫描识别并转异常+冻结",
        expected="abnormal + frozen=true + frozen_reason 含 7 天；confirm_wait_* 三字段清空；transitions confirm_timeout(actor=system)",
    ):
        abnormal = _trade(api, ctx, tid_abnormal_open, "wu")
        rec.must_eq(abnormal["status"], "abnormal", "超时交易状态")
        rec.must_eq(abnormal["frozen"], True, "超时同时冻结")
        rec.must("7" in (abnormal["frozen_reason"] or "") or "超时" in (abnormal["frozen_reason"] or "")
                 or "天" in (abnormal["frozen_reason"] or ""), "冻结原因说明超时")
        rec.must_eq(abnormal["confirm_wait_started_at"], None, "转异常清空计时起点")
        rec.must_eq(abnormal["confirm_wait_paused_at"], None, "转异常清空暂停时刻")
        rec.must_eq(abnormal["confirm_wait_remaining_seconds"], None, "转异常清空剩余秒数")
        transitions = api.get(f"/trades/{tid_abnormal_open}/transitions", token=ctx.token("wu"),
                              expected=200).json()
        timeout_rows = [t for t in transitions if t["trigger"] == "confirm_timeout"]
        rec.must(len(timeout_rows) == 1, "confirm_timeout 状态转移唯一")
        rec.must_eq(timeout_rows[0]["from_status"], "in_progress", "转移前状态")
        rec.must_eq(timeout_rows[0]["to_status"], "abnormal", "转移后状态")
        rec.must_eq(timeout_rows[0]["actor_role"], "system", "转移主体角色")
        ctx.update_trade("t_abnormal_open", state="abnormal")
        ctx.remember_item("trade_transition", "abnormal_timeout", tid_abnormal_open,
                          "单方确认超时转异常", "abnormal",
                          {"trigger": "confirm_timeout", "actor_role": "system"})

    with rec.step(
        "US-14-AC-01b_不自动结束锁单保持",
        us="US-14", sc="SC-09-02",
        desc="异常交易不按等待/约定到期自动完成或取消，锁单保持，等待管理员有依据决定结果",
        expected="异常后 status=abnormal（非 completed/terminated）；商品仍 in_transaction；分支未归档",
    ):
        abnormal = _trade(api, ctx, tid_abnormal_open, "wu")
        rec.must(abnormal["status"] not in ENDED, "异常交易未自动结束")
        product = api.get(f"/products/{p_abnormal_open['id']}", token=ctx.token("liu"), expected=200).json()
        rec.must_eq(product["status"], "in_transaction", "异常交易保持商品锁单")
        rec.must_eq(abnormal["conversation_archived"], False, "异常交易分支未归档")
        rec.must_eq(abnormal["finished_at"], None, "异常交易无结束时间")

    with rec.step(
        "US-14-AC-01c_异常事项与通知",
        us="US-14", sc="SC-09-01",
        desc="扫描转异常自动生成 ABNORMAL_TRADE 事项进入共享池，并通知交易双方",
        expected="共享池存在 pending 异常事项（trade_id 匹配）；双方收到 trade_abnormal 通知",
    ):
        case_open = _abnormal_case_of_trade(api, ctx, tid_abnormal_open)
        rec.must(case_open is not None, "共享池存在异常事项")
        rec.must_eq(case_open["case_type"], "abnormal_trade", "事项类型")
        rec.must_eq(case_open["status"], "pending", "异常事项待认领")
        rec.must_eq(case_open["claimed_by_id"], None, "异常事项未被认领")
        rec.must_eq(int(case_open["trade_id"]), tid_abnormal_open, "事项关联交易")
        rec.must(bool(_notif(_notifications(api, ctx.token("wu")), "trade_abnormal", tid_abnormal_open)),
                 "买方收到转异常通知")
        rec.must(bool(_notif(_notifications(api, ctx.token("liu")), "trade_abnormal", tid_abnormal_open)),
                 "卖方收到转异常通知")
        ctx.items["case_abnormal_open_id"] = case_open["id"]
        ctx.remember_case("case_abnormal_open", {"id": case_open["id"],
                                                 "title": "异常交易事项（待认领样本）",
                                                 "case_type": "abnormal_trade", "status": "pending"})
        rec.must_eq(api.get(f"/admin/cases/{case_open['id']}", token=ctx.token("admin")).status_code,
                    403, "未认领管理员不能查看异常事项详情")

    with rec.step(
        "US-14-AC-04f_解冻续算",
        us="US-14", sc="SC-09-10",
        desc="仅解除该笔冻结（原确认仍有效、未另有清空事件）：按剩余秒数续算，paused 清空、"
             "started_at 重锚，恢复为原进行中状态",
        expected="unfreeze 200；frozen=false；paused_at/remaining 清空；started_at 重锚≈now-(7天-剩余)；"
                 "remaining 续算≈原剩余；trade_unfrozen 留痕；双方通知；商品锁单保持",
    ):
        before_unfreeze = _trade(api, ctx, tid_freeze, "li")
        remaining_before = int(before_unfreeze["confirm_wait_remaining_seconds"])
        rec.must_eq(before_unfreeze["frozen"], True, "解冻前仍冻结")
        unfreeze = api.post(f"/admin/trades/{tid_freeze}/unfreeze", token=ctx.token("admin"),
                            json_body={"reason": "核查完成，恢复交易进度", "case_id": case_freeze},
                            expected=200)
        rec.must("已解除" in (unfreeze.json().get("detail") or ""), "解冻成功文案")
        resumed = _trade(api, ctx, tid_freeze, "li")
        rec.must_eq(resumed["frozen"], False, "解冻后非冻结")
        rec.must_eq(resumed["status"], "in_progress", "解冻后仍进行中")
        rec.must_eq(resumed["confirm_wait_paused_at"], None, "解冻清空暂停时刻")
        rec.must(resumed["confirm_wait_started_at"] is not None, "解冻后计时起点重锚")
        now = datetime.now(UTC)
        started = _parse_iso(resumed["confirm_wait_started_at"])
        elapsed_already_waited = TIMEOUT_SECONDS - remaining_before
        delta = (now - started).total_seconds()
        rec.must(abs(delta - elapsed_already_waited) < 60,
                 f"重锚起点应≈已等待 {elapsed_already_waited}s，实际 {delta:.0f}s")
        resumed_remaining = int(resumed["confirm_wait_remaining_seconds"])
        rec.must(resumed_remaining <= remaining_before, "续算后剩余不超过暂停值")
        rec.must(resumed_remaining >= remaining_before - 30, "续算剩余与暂停值一致（±30s）")
        db_row = db_query_one(
            db_path,
            "SELECT confirm_wait_paused_at, confirm_wait_remaining_seconds FROM trades WHERE id = ?",
            (tid_freeze,),
        )
        rec.must_eq(db_row[0], None, "解冻后持久化暂停时刻已清空")
        rec.must_eq(db_row[1], None, "解冻后持久化剩余秒数已清空")
        transitions = api.get(f"/trades/{tid_freeze}/transitions", token=ctx.token("li"),
                              expected=200).json()
        rec.must(any(t["trigger"] == "trade_unfrozen" for t in transitions), "解冻状态转移留痕")
        rec.must(bool(_notif(_notifications(api, ctx.token("wang")), "trade_unfrozen", tid_freeze)),
                 "解冻通知双方")
        product = api.get(f"/products/{p_freeze_id}", token=ctx.token("wang"), expected=200).json()
        rec.must_eq(product["status"], "in_transaction", "解冻保持商品锁单")
        # 解冻后恢复写权限：冻结前下架的商品可重新上架（真实接口验证）
        relisted = api.post(f"/products/{p_li_delist['id']}/relist", token=ctx.token("li"),
                            expected=200)
        rec.must_eq(relisted.json()["status"], "listed", "解冻后恢复上架资格")
        ctx.update_product("p_li_delist", state="listed")

    # -----------------------------------------------------------------
    # F. 异常事项处置：认领 → 问询/说明 → 回复 → adjust 恢复/终止
    # -----------------------------------------------------------------
    with rec.step(
        "US-14-AC-01d_异常样本待认领保留",
        us="US-14", sc="SC-09-01",
        desc="另有一笔异常交易保持 abnormal+frozen 且事项待认领（事项状态样本）",
        expected="t_abnormal_open 保持 abnormal/frozen；事项 pending 未认领",
    ):
        abnormal = _trade(api, ctx, tid_abnormal_open, "wu")
        rec.must_eq(abnormal["status"], "abnormal", "异常样本状态")
        rec.must_eq(abnormal["frozen"], True, "异常样本冻结")
        case_open = _abnormal_case_of_trade(api, ctx, tid_abnormal_open)
        rec.must(case_open is not None and case_open["status"] == "pending", "异常事项待认领样本")

    # 第二笔异常交易（用于处置链路）
    with rec.step(
        "US-14-AC-01e_处置样本转异常",
        us="US-14", sc="SC-09-01",
        desc="第二笔单方确认交易前移起点后由真实扫描转异常，作为管理员处置样本",
        expected="abnormal+frozen；异常事项进入共享池",
    ):
        backdate_confirm_wait(db_path, tid_abnormal_disposed, seconds_ago=8 * 86400)
        converted = wait_trade_status(api, ctx.token("chen"), tid_abnormal_disposed, "abnormal",
                                      timeout=SCAN_WAIT_TIMEOUT)
        rec.must_eq(converted["status"], "abnormal", "处置样本转异常")
        rec.must_eq(converted["frozen"], True, "处置样本冻结")
        case_disposed = _abnormal_case_of_trade(api, ctx, tid_abnormal_disposed)
        rec.must(case_disposed is not None, "处置样本异常事项进入共享池")
        ctx.items["case_abnormal_disposed_id"] = case_disposed["id"]
        ctx.update_trade("t_abnormal_disposed", state="abnormal")
        ctx.remember_case("case_abnormal_pending", {"id": case_disposed["id"],
                                                    "title": "异常交易事项（处置样本）",
                                                    "case_type": "abnormal_trade", "status": "pending"})
        ctx.note(
            f"p08 超时转异常：交易 #{tid_abnormal_open}、#{tid_abnormal_disposed} 仅前移"
            " trades.confirm_wait_started_at 8 天，abnormal/frozen/异常事项/双方通知均由真实后台扫描生成。"
        )

    case_abn = int(ctx.items["case_abnormal_disposed_id"])
    with rec.step(
        "US-14-AC-03b_异常事项认领",
        us="US-14", sc="SC-09-03",
        desc="异常事项在共享池：未认领详情拒绝、认领成功、重复认领 409；认领后管理读取交易需传依据事项",
        expected="未认领详情 403；claim 200；重复 claim 409；带 case_id 读交易 200 且含计时/转移字段",
    ):
        rec.must_eq(api.get(f"/admin/cases/{case_abn}", token=ctx.token("admin")).status_code, 403,
                    "未认领异常事项详情拒绝")
        resp = admin_claim_case(api, ctx, case_abn)
        rec.must_eq(resp["detail"], "认领成功", "认领成功")
        rec.must_eq(api.post(f"/admin/cases/{case_abn}/claim", token=ctx.token("admin"),
                             json_body={}).status_code, 409, "重复认领异常事项")
        view = api.get(f"/admin/trades/{tid_abnormal_disposed}", token=ctx.token("admin"),
                       params={"case_id": case_abn}, expected=200).json()
        rec.must_eq(view["status"], "abnormal", "管理视角交易状态")
        rec.must_eq(view["frozen"], True, "管理视角冻结标记")
        rec.must("confirm_wait_started_at" in view, "管理视角暴露等待计时字段")
        rec.must(any(t["trigger"] == "confirm_timeout" for t in view["transitions"]),
                 "管理视角可见超时转移留痕")

    with rec.step(
        "US-14-AC-07a_异常事项问询",
        us="US-14", sc="SC-09-05",
        desc="管理员对异常事项发起问询（US-14：双方可通过处置沟通说明；US-08-AC-05 问询→说明）",
        expected="200 问询已发送，问询对象覆盖异常交易双方",
    ):
        resp = api.post(f"/admin/cases/{case_abn}/inquiry", token=ctx.token("admin"),
                        json_body={"content": "请双方说明单方确认后的交付情况"})
        if resp.status_code != 200:
            rec.defect("requirement_gap", {
                "rule": "US-14-AC-07 / SC-09-05：异常交易双方应能通过处置沟通提交说明/申辩",
                "repro": f"POST /admin/cases/{case_abn}/inquiry（abnormal_trade 事项，trade_id={tid_abnormal_disposed}）",
                "expected": "200 问询已发送（可向交易双方发起说明要求）",
                "actual": f"HTTP {resp.status_code} {resp.text[:200]}",
                "source": "backend/app/services/trade_timeout.py:create_case; backend/app/api/v1/admin/cases.py:POST /admin/cases/{case_id}/inquiry",
            })
        rec.must_eq(resp.status_code, 200, "异常事项应可发起问询")

    with rec.step(
        "US-14-AC-07b_双方说明",
        us="US-14", sc="SC-09-05",
        desc="异常交易双方通过 /me/cases/{id}/statement 提交说明（用户侧处置沟通）",
        expected="双方 statement 各 200，说明记录可见",
    ):
        buyer_resp = api.post(f"/me/cases/{case_abn}/statement", token=ctx.token("chen"),
                              json_body={"content": "买方说明：已按约定交付"})
        seller_resp = api.post(f"/me/cases/{case_abn}/statement", token=ctx.token("zhang"),
                               json_body={"content": "卖方说明：未收到对方回应"})
        if buyer_resp.status_code != 200 or seller_resp.status_code != 200:
            rec.defect("requirement_gap", {
                "rule": "US-14-AC-07 / SC-09-05：异常交易双方均可在本人事项提交说明",
                "repro": f"POST /me/cases/{case_abn}/statement（双方 token）",
                "expected": "交易双方各 200 记录说明",
                "actual": f"买方 HTTP {buyer_resp.status_code}（{buyer_resp.text[:150]}）、"
                          f"卖方 HTTP {seller_resp.status_code}（{seller_resp.text[:150]}）",
                "source": "backend/app/api/v1/my_cases.py:POST /me/cases/{case_id}/statement",
            })
        rec.must_eq(buyer_resp.status_code, 200, "买方提交说明")
        rec.must_eq(seller_resp.status_code, 200, "卖方提交说明")

    with rec.step(
        "US-14-AC-07c_管理员回复通知双方",
        us="US-14", sc="SC-09-05",
        desc="认领管理员在异常事项回复处理说明（处置沟通单），通知交易双方",
        expected="回复 200；双方收到 appeal_result 事项沟通通知",
    ):
        reply = api.post(f"/admin/cases/{case_abn}/messages", token=ctx.token("admin"),
                         json_body={"content": "已核对：单方确认后对方长期未回应，交易转异常处理"},
                         expected=200)
        rec.must_eq(reply.json()["detail"], "回复已发送", "回复成功文案")
        rec.must(bool(_notif(_notifications(api, ctx.token("chen")), "appeal_result", case_abn)),
                 "买方收到事项回复通知")
        rec.must(bool(_notif(_notifications(api, ctx.token("zhang")), "appeal_result", case_abn)),
                 "卖方收到事项回复通知")

    with rec.step(
        "US-14-AC-05_恢复进行中",
        us="US-14", sc="SC-09-06",
        desc="认领管理员有依据把异常交易调整为进行中：保留有效约定、清空当前完成确认与旧计时、"
             "恢复不启动计时且不自动解冻",
        expected="adjust 200；status=in_progress、frozen 仍 true、确认清空、agreement_stage=awaiting_completion、"
                 "confirm_wait_started_at=null、effective_agreement 保留、branch 未归档、通知 trade_adjusted",
    ):
        before = _trade(api, ctx, tid_abnormal_disposed, "chen")
        rec.must(before["effective_agreement"] is None or isinstance(before["effective_agreement"], dict),
                 "异常交易保留有效约定结构")
        adjust = api.post(f"/admin/trades/{tid_abnormal_disposed}/adjust", token=ctx.token("admin"),
                          json_body={"to_status": "in_progress", "reason": "核查后恢复交易进度",
                                     "case_id": case_abn}, expected=200)
        rec.must("in_progress" in (adjust.json().get("detail") or ""), "恢复进行中成功文案")
        restored = _trade(api, ctx, tid_abnormal_disposed, "chen")
        rec.must_eq(restored["status"], "in_progress", "恢复后状态")
        rec.must_eq(restored["frozen"], True, "管理恢复进行中不自动解冻")
        rec.must_eq(restored["my_confirmed"], False, "恢复清空本人当前确认")
        rec.must_eq(restored["other_party_confirmed"], False, "恢复清空对方当前确认")
        rec.must_eq(restored["agreement_stage"], "awaiting_completion", "保留有效约定对应阶段")
        rec.must(restored["effective_agreement"] is not None, "保留未调整的有效约定")
        rec.must_eq(restored["confirm_wait_started_at"], None, "恢复不启动计时")
        rec.must_eq(restored["conversation_archived"], False, "恢复不归档分支")
        transitions = api.get(f"/trades/{tid_abnormal_disposed}/transitions",
                              token=ctx.token("chen"), expected=200).json()
        rec.must(any(t["trigger"] == "admin_restore" and t["actor_role"] == "admin"
                     for t in transitions), "管理恢复状态转移留痕")
        rec.must(bool(_notif(_notifications(api, ctx.token("zhang")), "trade_adjusted",
                             tid_abnormal_disposed)), "调整通知双方")
        ctx.update_trade("t_abnormal_disposed", state="in_progress")

    with rec.step(
        "US-14-AC-06a_终止结束联动",
        us="US-14", sc="SC-09-08",
        desc="管理员仅解除冻结后，有依据把交易调整为已终止：解冻/归档/商品默认下架/通知/转移留痕",
        expected="unfreeze 200（无当前确认时不恢复旧等待）；adjust terminated 200；frozen=false、finished_at 非空、"
                 "分支归档、商品 delisted、双方收到 trade_terminated、transitions admin_adjust_terminated",
    ):
        api.post(f"/admin/trades/{tid_abnormal_disposed}/unfreeze", token=ctx.token("admin"),
                 json_body={"reason": "恢复后仅解除冻结", "case_id": case_abn}, expected=200)
        unfrozen = _trade(api, ctx, tid_abnormal_disposed, "chen")
        rec.must_eq(unfrozen["frozen"], False, "仅解冻解除冻结标记")
        rec.must_eq(unfrozen["status"], "in_progress", "仅解冻保持进行中状态")
        rec.must_eq(unfrozen["confirm_wait_paused_at"], None, "无有效确认时旧等待不恢复")
        terminated = api.post(f"/admin/trades/{tid_abnormal_disposed}/adjust", token=ctx.token("admin"),
                              json_body={"to_status": "terminated", "reason": "双方均未回应，终止交易",
                                         "case_id": case_abn}, expected=200)
        rec.must("terminated" in (terminated.json().get("detail") or ""), "终止成功文案")
        ended = _trade(api, ctx, tid_abnormal_disposed, "chen")
        rec.must_eq(ended["status"], "terminated", "终止后状态")
        rec.must_eq(ended["frozen"], False, "结束自动解除本笔冻结")
        rec.must(ended["finished_at"] is not None, "终止写入结束时间")
        rec.must_eq(ended["conversation_archived"], True, "结束归档交易分支")
        product = api.get(f"/products/{p_abnormal_disposed['id']}", token=ctx.token("zhang"),
                          expected=200).json()
        rec.must_eq(product["status"], "delisted", "结束交易商品默认下架")
        rec.must(bool(_notif(_notifications(api, ctx.token("chen")), "trade_terminated",
                             tid_abnormal_disposed)), "终止通知双方（买方）")
        rec.must(bool(_notif(_notifications(api, ctx.token("zhang")), "trade_terminated",
                             tid_abnormal_disposed)), "终止通知双方（卖方）")
        transitions = api.get(f"/trades/{tid_abnormal_disposed}/transitions",
                              token=ctx.token("chen"), expected=200).json()
        rec.must(any(t["trigger"] == "admin_adjust_terminated" for t in transitions),
                 "管理终止转移留痕")
        ctx.update_trade("t_abnormal_disposed", state="terminated")
        ctx.update_product("p_abnormal_disposed", state="delisted")

    with rec.step(
        "US-14-AC-07d_事项处置与双方读取",
        us="US-14", sc="SC-09-05",
        desc="认领管理员形成异常事项结论；交易双方可在本人事项入口读取处置结论与沟通记录",
        expected="dispose 200；事项 disposed 且有结论/依据；chen/zhang 的 /me/cases/{id} 200 且 trade_id 匹配",
    ):
        dispose = api.post(f"/admin/cases/{case_abn}/dispose", token=ctx.token("admin"),
                           json_body={"conclusion": "异常交易已处置", "reason": "双方未回应，终止交易",
                                      "basis": "BR-05/BR-08"}, expected=200)
        rec.must_eq(dispose.json()["detail"], "事项已处置", "事项处置文案")
        detail = admin_case_detail(api, ctx, case_abn)
        rec.must_eq(detail["status"], "disposed", "异常事项已处置")
        rec.must_eq(detail["conclusion"], "异常交易已处置", "处置结论")
        rec.must_eq(int(detail["trade_id"]), tid_abnormal_disposed, "事项关联交易")
        for viewer in ("chen", "zhang"):
            user_case = api.get(f"/me/cases/{case_abn}", token=ctx.token(viewer), expected=200).json()
            rec.must_eq(int(user_case["trade_id"]), tid_abnormal_disposed, f"{viewer} 本人事项读取")
            rec.must_eq(user_case["status"], "disposed", f"{viewer} 事项状态")
            rec.must(len(user_case["messages"]) >= 1, f"{viewer} 事项沟通记录可见")
        ctx.remember_case("case_abnormal_disposed", {"id": case_abn,
                                                     "title": "异常交易事项（已处置）",
                                                     "case_type": "abnormal_trade", "status": "disposed"})

    # -----------------------------------------------------------------
    # G. D-48：同商品旧交易已结束、新交易仍锁单时恢复旧交易 → 409 无副作用
    # -----------------------------------------------------------------
    with rec.step(
        "US-14-AC-08_D48恢复冲突",
        us="US-14", sc="SC-09-09",
        desc="同商品旧交易已结束、新交易仍锁单：认领管理员恢复旧交易为进行中",
        expected="409 商品已存在另一笔锁单交易；旧/新交易、商品、锁单、分支、转移与通知均无副作用",
    ):
        report_d48 = _create_report(api, ctx.token("sun"), "product", p_d48_id,
                                    "商品描述与实物不符（D-48 依据）")
        _remember_report(ctx, "r_d48", {"id": report_d48["id"], "target_type": "product",
                                      "reason": "商品描述与实物不符（D-48 依据）"}, "processing")
        case_d48 = _report_case_id(api, ctx, report_d48["id"])
        admin_claim_case(api, ctx, case_d48)
        ctx.items["case_d48_id"] = case_d48
        old_before = _trade(api, ctx, tid_d48_old, "zhang")
        new_before = _trade(api, ctx, tid_d48_new, "chen")
        old_transitions_before = len(api.get(f"/trades/{tid_d48_old}/transitions",
                                             token=ctx.token("zhang"), expected=200).json())
        new_transitions_before = len(api.get(f"/trades/{tid_d48_new}/transitions",
                                             token=ctx.token("chen"), expected=200).json())
        rec.must_eq(old_before["status"], "completed", "旧交易已结束")
        rec.must_eq(new_before["status"], "in_progress", "新交易仍锁单")
        chen_adjust_before = len(_notif(_notifications(api, ctx.token("chen")), "trade_adjusted"))
        resp = api.post(f"/admin/trades/{tid_d48_old}/adjust", token=ctx.token("admin"),
                        json_body={"to_status": "in_progress", "reason": "恢复旧交易",
                                   "case_id": case_d48})
        rec.must_eq(resp.status_code, 409, "D-48 恢复冲突状态码")
        rec.must("锁单" in (resp.json().get("detail") or ""), "锁单冲突文案")
        old_after = _trade(api, ctx, tid_d48_old, "zhang")
        new_after = _trade(api, ctx, tid_d48_new, "chen")
        rec.must_eq(old_after["status"], "completed", "旧交易状态无副作用")
        rec.must_eq(new_after["status"], "in_progress", "新交易状态无副作用")
        rec.must_eq(new_after["frozen"], False, "新交易未被冻结")
        product = api.get(f"/products/{p_d48_id}", token=ctx.token("liu"), expected=200).json()
        rec.must_eq(product["status"], "in_transaction", "商品锁单状态无副作用")
        rec.must_eq(old_after["conversation_archived"], True, "旧交易分支保持归档")
        rec.must_eq(new_after["conversation_archived"], False, "新交易分支保持未归档")
        rec.must_eq(len(api.get(f"/trades/{tid_d48_old}/transitions",
                                token=ctx.token("zhang"), expected=200).json()), old_transitions_before,
                    "旧交易无新增状态转移")
        rec.must_eq(len(api.get(f"/trades/{tid_d48_new}/transitions",
                                token=ctx.token("chen"), expected=200).json()), new_transitions_before,
                    "新交易无新增状态转移")
        rec.must_eq(len(_notif(_notifications(api, ctx.token("chen")), "trade_adjusted")),
                    chen_adjust_before, "无管理调整通知副作用")

    with rec.step(
        "US-14-AC-08b_调整边界",
        us="US-14", sc="SC-09-08",
        desc="管理调整的重复/非法目标边界：调整为当前相同状态 409；非法目标状态 422 且无副作用",
        expected="completed→completed 409 交易已处于目标状态；非法目标 422 非法目标状态；旧交易仍 completed",
    ):
        resp = api.post(f"/admin/trades/{tid_d48_old}/adjust", token=ctx.token("admin"),
                        json_body={"to_status": "completed", "reason": "重复调整", "case_id": case_d48})
        rec.must_eq(resp.status_code, 409, "相同目标状态")
        rec.must("目标状态" in (resp.json().get("detail") or ""), "相同状态文案")
        resp = api.post(f"/admin/trades/{tid_d48_old}/adjust", token=ctx.token("admin"),
                        json_body={"to_status": "not_a_status", "reason": "非法", "case_id": case_d48})
        rec.must_eq(resp.status_code, 422, "非法目标状态")
        rec.must_eq(resp.json().get("detail"), "非法目标状态", "非法目标状态文案")
        rec.must_eq(_trade(api, ctx, tid_d48_old, "zhang")["status"], "completed",
                    "非法调整无副作用")

    with rec.step(
        "US-14-AC-01f_事项状态样本",
        us="US-14", sc="SC-09-01",
        desc="异常事项状态样本：待认领（未认领）与已认领并处置并存",
        expected="共享池存在 pending 的 abnormal_trade 事项；已处置异常事项记录含结论与依据",
    ):
        pending_cases = admin_list_cases(api, ctx, status="pending", case_type="abnormal_trade")
        rec.must(any(int(c["trade_id"]) == tid_abnormal_open for c in pending_cases if c.get("trade_id")),
                 "待认领异常事项样本")
        disposed_cases = admin_list_cases(api, ctx, status="disposed", case_type="abnormal_trade")
        rec.must(any(c["id"] == case_abn for c in disposed_cases), "已处置异常事项样本")
        detail = admin_case_detail(api, ctx, case_abn)
        rec.must_eq(detail["conclusion"], "异常交易已处置", "样本处置结论")
        rec.must_eq(detail["basis"], "BR-05/BR-08", "样本处置依据")

    # 最终状态样本
    with rec.step(
        "US-14-AC-01g_最终状态样本",
        us="US-14", sc="SC-09-01",
        desc="本阶段保留可复核的最终状态样本：冻结暂停交易已续算、异常样本待认领、处置样本已终止",
        expected="t_freeze_pause in_progress 有剩余计时；t_abnormal_open abnormal+frozen 事项待认领；"
                 "t_abnormal_disposed terminated；D-48 新交易 in_progress",
    ):
        frozen_resumed = _trade(api, ctx, tid_freeze, "li")
        rec.must_eq(frozen_resumed["status"], "in_progress", "冻结暂停样本最终进行中")
        rec.must_eq(frozen_resumed["frozen"], False, "冻结暂停样本最终已解冻")
        rec.must(frozen_resumed["confirm_wait_started_at"] is not None, "冻结暂停样本最终计时续算")
        abnormal_open = _trade(api, ctx, tid_abnormal_open, "wu")
        rec.must_eq(abnormal_open["status"], "abnormal", "异常待认领样本最终状态")
        rec.must_eq(abnormal_open["frozen"], True, "异常待认领样本保持冻结")
        case_open = _abnormal_case_of_trade(api, ctx, tid_abnormal_open)
        rec.must(case_open is not None and case_open["status"] == "pending", "异常待认领事项最终状态")
        rec.must_eq(_trade(api, ctx, tid_abnormal_disposed, "chen")["status"], "terminated",
                    "处置样本最终已终止")
        rec.must_eq(_trade(api, ctx, tid_d48_new, "chen")["status"], "in_progress",
                    "D-48 新交易最终锁单")
        ctx.update_trade("t_freeze_pause", state="in_progress")
        ctx.remember_item("case", "case_abnormal_open_final", case_open["id"],
                          "异常事项待认领", "pending", {"trade_id": tid_abnormal_open})

    _dedupe_inventory(ctx)
    _refresh_report_states(api, ctx)

    ctx.note(
        "p08 证据边界：唯一绕过 HTTP 的时间模拟是前移 trades.confirm_wait_started_at（8 天）；"
        "超时识别、后台扫描、abnormal 状态、冻结、异常事项、通知、认领、问询/说明、管理员调整、"
        "解冻/归档/商品下架全部由真实运行后端与真实接口完成。冻结暂停场景中前移起点时不修改"
        " confirm_wait_paused_at / confirm_wait_remaining_seconds。"
    )
    if any(d.get("kind") == "requirement_gap" for d in rec.defects):
        ctx.note(
            "p08 已记录实现缺陷：异常事项问询/双方说明存在实际失败，详情见缺陷清单"
            "（US-14-AC-07 / SC-09-05）。"
        )
    else:
        ctx.note(
            "p08 异常事项问询与双方说明检查项本轮均未记录失败，不登记该缺陷候选。"
        )
