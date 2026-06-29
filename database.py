from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from catalog import STATIC_PRODUCTS, DEFAULT_RATES, FIXED_RATE_CATEGORIES

DB_PATH = os.getenv("DB_PATH", "prime_topup.sqlite3")
_lock = asyncio.Lock()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_dt(v: Any) -> Any:
    if isinstance(v, str):
        try:
            if "T" in v or re.match(r"\d{4}-\d{2}-\d{2}", v):
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return v
    return v


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in list(d.keys()):
        if k.endswith("_at") or k in {"created_at", "updated_at", "last_seen", "expires_at"}:
            d[k] = _parse_dt(d[k])
        if k in {"is_banned", "enabled", "ask_game_id"} and d[k] is not None:
            d[k] = bool(d[k])
    return d


def _prepare(sql: str, args: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
    # Convert asyncpg-style placeholders to sqlite placeholders while preserving $2/$1 order.
    order: list[int] = []

    def repl(match: re.Match) -> str:
        order.append(int(match.group(0)[1:]) - 1)
        return "?"

    sql = re.sub(r"\$\d+", repl, sql)
    sql = sql.replace("NOW()", "CURRENT_TIMESTAMP")
    sql = re.sub(r"\btrue\b", "1", sql, flags=re.I)
    sql = re.sub(r"\bfalse\b", "0", sql, flags=re.I)
    if order:
        args = tuple(args[i] for i in order)
    return sql, args


async def execute(sql: str, *args):
    async with _lock:
        with _connect() as con:
            con.execute(*_prepare(sql, args))
            con.commit()


async def fetch(sql: str, *args):
    async with _lock:
        with _connect() as con:
            rows = con.execute(*_prepare(sql, args)).fetchall()
            return [_row_to_dict(r) for r in rows]


async def fetchrow(sql: str, *args):
    rows = await fetch(sql, *args)
    return rows[0] if rows else None


async def fetchval(sql: str, *args):
    async with _lock:
        with _connect() as con:
            row = con.execute(*_prepare(sql, args)).fetchone()
            return None if row is None else row[0]


async def init_db():
    async with _lock:
        with _connect() as con:
            con.executescript(SCHEMA)
            # Seed rates and products once / keep admin changes.
            for cat, rate in DEFAULT_RATES.items():
                con.execute("INSERT OR IGNORE INTO category_rates(category, rate) VALUES(?,?)", (cat, rate))
            for p in STATIC_PRODUCTS:
                rate = 100.0 if p.category in FIXED_RATE_CATEGORIES else DEFAULT_RATES.get(p.category, 100.0)
                con.execute(
                    """
                    INSERT OR IGNORE INTO products(id, category, title, base_price, rate, enabled, ask_game_id, created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (p.id, p.category, p.title, p.base, rate, 1, 1 if p.ask_game_id else 0, _now()),
                )
            con.commit()


async def create_or_update_user(user) -> bool:
    async with _lock:
        with _connect() as con:
            existed = con.execute("SELECT id FROM users WHERE id=?", (user.id,)).fetchone()
            now = _now()
            con.execute(
                """
                INSERT INTO users(id, username, first_name, language_code, last_seen, created_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    language_code=excluded.language_code,
                    last_seen=excluded.last_seen
                """,
                (user.id, user.username, user.first_name, user.language_code, now, now),
            )
            con.commit()
            return existed is None


async def get_user(user_id: int):
    return await fetchrow("SELECT * FROM users WHERE id=$1", user_id)


async def add_balance(user_id: int, amount: float, note: str = "admin"):
    async with _lock:
        with _connect() as con:
            now = _now()
            con.execute("INSERT OR IGNORE INTO users(id, created_at, last_seen) VALUES(?,?,?)", (user_id, now, now))
            con.execute("UPDATE users SET balance=COALESCE(balance,0)+? WHERE id=?", (amount, user_id))
            con.execute("INSERT INTO balance_logs(user_id, amount, note, created_at) VALUES(?,?,?,?)", (user_id, amount, note, now))
            con.commit()


async def set_balance(user_id: int, amount: float):
    async with _lock:
        with _connect() as con:
            now = _now()
            con.execute("INSERT OR IGNORE INTO users(id, created_at, last_seen) VALUES(?,?,?)", (user_id, now, now))
            con.execute("UPDATE users SET balance=? WHERE id=?", (amount, user_id))
            con.commit()


async def user_balance(user_id: int) -> float:
    val = await fetchval("SELECT COALESCE(balance,0) FROM users WHERE id=$1", user_id)
    return float(val or 0)


async def create_payment(user_id: int, amount: float, method: str, address: str, expires_at):
    async with _lock:
        with _connect() as con:
            cur = con.execute(
                """
                INSERT INTO payments(user_id, amount, method, address, status, created_at, expires_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (user_id, amount, method, address, "PENDING", _now(), expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at)),
            )
            con.commit()
            return _row_to_dict(con.execute("SELECT * FROM payments WHERE id=?", (cur.lastrowid,)).fetchone())


async def cancel_pending_payment(user_id: int):
    await execute("UPDATE payments SET status='TG_STATUS_CANCELLED' WHERE user_id=$1 AND status='PENDING'", user_id)


async def latest_payments(user_id: int):
    return await fetch("SELECT * FROM payments WHERE user_id=$1 ORDER BY id DESC LIMIT 10", user_id)


async def get_products(category: str):
    return await fetch("SELECT * FROM products WHERE category=$1 AND enabled=1 ORDER BY rowid", category)


async def get_product(product_id: str):
    return await fetchrow("SELECT * FROM products WHERE id=$1 AND enabled=1", product_id)


async def product_price(row) -> float:
    return round(float(row["base_price"]) * float(row["rate"]) / 100.0, 2)


async def set_category_rate(category: str, rate: float):
    async with _lock:
        with _connect() as con:
            con.execute(
                """
                INSERT INTO category_rates(category, rate) VALUES(?,?)
                ON CONFLICT(category) DO UPDATE SET rate=excluded.rate
                """,
                (category, rate),
            )
            con.execute("UPDATE products SET rate=? WHERE category=?", (rate, category))
            con.commit()


async def set_price(product_id: str, final_price: float):
    await execute("UPDATE products SET base_price=$2, rate=100 WHERE id=$1", product_id, final_price)


async def add_product(product_id: str, category: str, title: str, base_price: float, rate: float, ask_game_id: bool=False):
    async with _lock:
        with _connect() as con:
            con.execute(
                """
                INSERT INTO products(id, category, title, base_price, rate, enabled, ask_game_id, created_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    category=excluded.category,
                    title=excluded.title,
                    base_price=excluded.base_price,
                    rate=excluded.rate,
                    enabled=1,
                    ask_game_id=excluded.ask_game_id
                """,
                (product_id, category, title, base_price, rate, 1, 1 if ask_game_id else 0, _now()),
            )
            con.commit()


async def del_product(product_id: str):
    await execute("UPDATE products SET enabled=0 WHERE id=$1", product_id)


async def create_order(user_id: int, product_id: str, title: str, price: float, game_id: Optional[str] = None):
    async with _lock:
        with _connect() as con:
            now = _now()
            con.execute("INSERT OR IGNORE INTO users(id, created_at, last_seen) VALUES(?,?,?)", (user_id, now, now))
            u = con.execute("SELECT balance, min_purchase FROM users WHERE id=?", (user_id,)).fetchone()
            bal = float(u["balance"] or 0)
            min_purchase = u["min_purchase"]
            if min_purchase is not None and float(min_purchase) > 0 and price < float(min_purchase):
                return {"error": "MIN", "minimum": float(min_purchase)}
            if bal < price:
                return None
            con.execute("UPDATE users SET balance=COALESCE(balance,0)-? WHERE id=?", (price, user_id))
            cur = con.execute(
                """
                INSERT INTO orders(user_id, product_id, title, price, game_id, status, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (user_id, product_id, title, price, game_id, "PROCESSING", now, now),
            )
            oid = cur.lastrowid
            con.execute("INSERT INTO balance_logs(user_id, amount, note, created_at) VALUES(?,?,?,?)", (user_id, -price, f"order #{oid}", now))
            con.commit()
            return _row_to_dict(con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())


async def recent_orders(user_id: int | None = None):
    if user_id:
        return await fetch("SELECT * FROM orders WHERE user_id=$1 ORDER BY id DESC LIMIT 20", user_id)
    return await fetch("SELECT * FROM orders ORDER BY id DESC LIMIT 50")


async def all_users():
    return await fetch("SELECT * FROM users ORDER BY created_at DESC")


async def all_orders():
    return await fetch("SELECT * FROM orders ORDER BY id DESC")


async def balances():
    return await fetch("SELECT id, username, first_name, balance FROM users ORDER BY balance DESC")


async def backup_json() -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "users": await all_users(),
        "orders": await all_orders(),
        "payments": await fetch("SELECT * FROM payments ORDER BY id DESC"),
        "products": await fetch("SELECT * FROM products ORDER BY category,id"),
        "rates": await fetch("SELECT * FROM category_rates ORDER BY category"),
        "coupons": await fetch("SELECT * FROM coupons ORDER BY created_at DESC"),
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language_code TEXT DEFAULT 'en',
    language TEXT DEFAULT 'en',
    balance REAL DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    min_purchase REAL,
    created_at TEXT,
    last_seen TEXT
);
CREATE TABLE IF NOT EXISTS category_rates(
    category TEXT PRIMARY KEY,
    rate REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS products(
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    base_price REAL NOT NULL,
    rate REAL NOT NULL DEFAULT 100,
    enabled INTEGER DEFAULT 1,
    ask_game_id INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product_id TEXT,
    title TEXT,
    price REAL,
    game_id TEXT,
    status TEXT DEFAULT 'PROCESSING',
    admin_note TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    method TEXT,
    address TEXT,
    txid TEXT,
    status TEXT DEFAULT 'PENDING',
    created_at TEXT,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS balance_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    note TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS coupons(
    code TEXT PRIMARY KEY,
    percent REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
"""
