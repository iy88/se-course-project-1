"""开发库只读快照：统计表行数与关键状态分布，供最终报告与数据核对。

只读打开 SQLite（URI mode=ro），不修改数据；不访问业务接口。
用法（在 backend/tests/e2e_lifecycle 下）：
  ../../.venv/bin/python tools/db_snapshot.py \
      --db ../../../var/db/app.db \
      --out ../../../var/e2e-results/<runid>/snapshot.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    return list(conn.execute(sql, params))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=20)
    snapshot: dict = {"db": args.db, "tables": {}, "users": [], "products_by_status": {}, "trades_by_status": {}, "cases_by": {}, "reports_by": {}, "notifications": {}, "counts": {}}

    tables = [
        "users", "categories", "category_aliases", "prohibited_items", "products", "product_images",
        "product_tags", "product_tag_applications", "product_edit_histories", "review_records",
        "favorites", "comments", "conversations", "messages", "conversation_reads", "trades",
        "trade_agreements", "completion_confirmations", "trade_transitions", "trade_reviews",
        "reports", "report_supplements", "disposal_cases", "disposal_messages",
        "account_restrictions", "notifications",
    ]
    for table in tables:
        try:
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            snapshot["tables"][table] = count
            snapshot["counts"][table] = count
        except sqlite3.Error as exc:
            snapshot["tables"][table] = f"ERROR: {exc}"

    try:
        for row in rows(conn, "SELECT id,email,display_name,role,status FROM users ORDER BY id"):
            snapshot["users"].append({"id": row[0], "email": row[1], "display_name": row[2], "role": row[3], "status": row[4]})
    except sqlite3.Error:
        pass
    for name, table, column in [
        ("products_by_status", "products", "status"),
        ("trades_by_status", "trades", "status"),
    ]:
        try:
            counter = Counter(r[0] for r in rows(conn, f"SELECT {column} FROM {table}"))
            snapshot[name] = dict(sorted(counter.items()))
        except sqlite3.Error:
            pass
    try:
        counter = Counter(f"{r[0]}/{r[1]}" for r in rows(conn, "SELECT case_type,status FROM disposal_cases"))
        snapshot["cases_by"] = dict(sorted(counter.items()))
    except sqlite3.Error:
        pass
    try:
        counter = Counter(f"{r[0]}/{r[1]}" for r in rows(conn, "SELECT target_type,status FROM reports"))
        snapshot["reports_by"] = dict(sorted(counter.items()))
    except sqlite3.Error:
        pass
    try:
        snapshot["notifications"] = {
            "total": conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
            "unread": conn.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0").fetchone()[0],
            "types": dict(sorted(Counter(r[0] for r in rows(conn, "SELECT type FROM notifications")).items())),
        }
    except sqlite3.Error:
        pass
    try:
        snapshot["display_restricted_products"] = [
            {"id": r[0], "title": r[1], "status": r[2], "reason": r[3], "case_id": r[4]}
            for r in rows(conn, "SELECT id,title,status,display_restricted_reason,display_restricted_case_id FROM products WHERE display_restricted = 1 ORDER BY id")
        ]
    except sqlite3.Error:
        pass
    try:
        snapshot["image_counts"] = {
            "product_images": conn.execute("SELECT COUNT(*) FROM product_images").fetchone()[0],
            "reports_with_evidence": conn.execute("SELECT COUNT(*) FROM reports WHERE evidence_keys IS NOT NULL AND evidence_keys != '[]'").fetchone()[0],
        }
        snapshot["trades_detail"] = [
            {"id": r[0], "product_id": r[1], "buyer_id": r[2], "seller_id": r[3], "status": r[4], "frozen": r[5]}
            for r in rows(conn, "SELECT id,product_id,buyer_id,seller_id,status,frozen FROM trades ORDER BY id")
        ]
    except sqlite3.Error:
        pass
    conn.close()

    out = args.out
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        print("written", out)
    print(json.dumps({k: snapshot[k] for k in ("products_by_status", "trades_by_status", "cases_by", "reports_by", "notifications", "image_counts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
