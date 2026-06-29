from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from catalog import STATIC_PRODUCTS, DEFAULT_RATES, FIXED_RATE_CATEGORIES
from config import config

pool: asyncpg.Pool | None = None

async def init_db() -> None:
    global pool
    if not config.database_url:
        raise RuntimeError("DATABASE_URL is required")
    pool = await asyncpg.create_pool(config.database_url, min_size=1, max_size=5)
    async with pool.acquire() as con:
        await con.execute(SCHEMA)
        await seed(con)

async def seed(con: asyncpg.Connection) -> None:
    for cat, rate in DEFAULT_RATES.items():
        await con.execute("""
            INSERT INTO category_rates(category, rate) VALUES($1,$2)
            ON CONFLICT(category) DO NOTHING
        """, cat, rate)
    for p in STATIC_PRODUCTS:
        rate = 100.0 if p.category in FIXED_RATE_CATEGORIES else DEFAULT_RATES.get(p.category, 100.0)
        await con.execute("""
            INSERT INTO products(id, category, title, base_price, rate, enabled, ask_game_id)
            VALUES($1,$2,$3,$4,$5,true,$6)
            ON CONFLICT(id) DO NOTHING
        """, p.id, p.category, p.title, p.base, rate, p.ask_game_id)

async def fetch(query: str, *args):
    assert pool
    async with pool.acquire() as con:
        return await con.fetch(query, *args)

async def fetchrow(query: str, *args):
    assert pool
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def fetchval(query: str, *args):
    assert pool
    async with pool.acquire() as con:
        return await con.fetchval(query, *args)

async def execute(query: str, *args):
    assert pool
    async with pool.acquire() as con:
        return await con.execute(query, *args)

async def create_or_update_user(user) -> bool:
    existed = await fetchval("SELECT 1 FROM users WHERE id=$1", user.id)
    await execute("""
        INSERT INTO users(id, username, first_name, language_code, last_seen)
        VALUES($1,$2,$3,$4,NOW())
        ON CONFLICT(id) DO UPDATE SET username=$2, first_name=$3, language_code=$4, last_seen=NOW()
    """, user.id, user.username, user.first_name, user.language_code)
    return existed is None

async def get_user(user_id: int):
    return await fetchrow("SELECT * FROM users WHERE id=$1", user_id)

async def add_balance(user_id: int, amount: float, note: str = "admin"):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute("INSERT INTO users(id) VALUES($1) ON CONFLICT DO NOTHING", user_id)
            await con.execute("UPDATE users SET balance=balance+$2 WHERE id=$1", user_id, amount)
            await con.execute("INSERT INTO balance_logs(user_id, amount, note) VALUES($1,$2,$3)", user_id, amount, note)

async def set_balance(user_id: int, amount: float):
    await execute("INSERT INTO users(id) VALUES($1) ON CONFLICT DO NOTHING", user_id)
    await execute("UPDATE users SET balance=$2 WHERE id=$1", user_id, amount)

async def user_balance(user_id: int) -> float:
    val = await fetchval("SELECT COALESCE(balance,0) FROM users WHERE id=$1", user_id)
    return float(val or 0)

async def create_payment(user_id: int, amount: float, method: str, address: str, expires_at):
    return await fetchrow("""
        INSERT INTO payments(user_id, amount, method, address, status, expires_at)
        VALUES($1,$2,$3,$4,'PENDING',$5)
        RETURNING *
    """, user_id, amount, method, address, expires_at)

async def cancel_pending_payment(user_id: int):
    await execute("UPDATE payments SET status='TG_STATUS_CANCELLED' WHERE user_id=$1 AND status='PENDING'", user_id)

async def latest_payments(user_id: int):
    return await fetch("SELECT * FROM payments WHERE user_id=$1 ORDER BY id DESC LIMIT 10", user_id)

async def get_products(category: str):
    return await fetch("SELECT * FROM products WHERE category=$1 AND enabled=true ORDER BY id", category)

async def get_product(product_id: str):
    return await fetchrow("SELECT * FROM products WHERE id=$1 AND enabled=true", product_id)

async def product_price(row) -> float:
    return round(float(row["base_price"]) * float(row["rate"]) / 100.0, 2)

async def set_category_rate(category: str, rate: float):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute("""
                INSERT INTO category_rates(category, rate) VALUES($1,$2)
                ON CONFLICT(category) DO UPDATE SET rate=$2
            """, category, rate)
            await con.execute("UPDATE products SET rate=$2 WHERE category=$1", category, rate)

async def set_price(product_id: str, final_price: float):
    # store as fixed final price by setting rate=100 and base=price
    await execute("UPDATE products SET base_price=$2, rate=100 WHERE id=$1", product_id, final_price)

async def add_product(product_id: str, category: str, title: str, base_price: float, rate: float, ask_game_id: bool=False):
    await execute("""
        INSERT INTO products(id, category, title, base_price, rate, enabled, ask_game_id)
        VALUES($1,$2,$3,$4,$5,true,$6)
        ON CONFLICT(id) DO UPDATE SET category=$2,title=$3,base_price=$4,rate=$5,enabled=true,ask_game_id=$6
    """, product_id, category, title, base_price, rate, ask_game_id)

async def del_product(product_id: str):
    await execute("UPDATE products SET enabled=false WHERE id=$1", product_id)

async def create_order(user_id: int, product_id: str, title: str, price: float, game_id: Optional[str] = None):
    async with pool.acquire() as con:
        async with con.transaction():
            bal = float(await con.fetchval("SELECT balance FROM users WHERE id=$1 FOR UPDATE", user_id) or 0)
            if bal < price:
                return None
            await con.execute("UPDATE users SET balance=balance-$2 WHERE id=$1", user_id, price)
            order = await con.fetchrow("""
                INSERT INTO orders(user_id, product_id, title, price, game_id, status)
                VALUES($1,$2,$3,$4,$5,'PROCESSING') RETURNING *
            """, user_id, product_id, title, price, game_id)
            await con.execute("INSERT INTO balance_logs(user_id, amount, note) VALUES($1,$2,$3)", user_id, -price, f"order #{order['id']}")
            return order

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
        "users": [dict(r) for r in await all_users()],
        "orders": [dict(r) for r in await all_orders()],
        "payments": [dict(r) for r in await fetch("SELECT * FROM payments ORDER BY id DESC")],
        "products": [dict(r) for r in await fetch("SELECT * FROM products ORDER BY category,id")],
        "rates": [dict(r) for r in await fetch("SELECT * FROM category_rates ORDER BY category")],
    }

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language_code TEXT DEFAULT 'en',
    language TEXT DEFAULT 'en',
    balance NUMERIC(14,4) DEFAULT 0,
    is_banned BOOLEAN DEFAULT false,
    min_purchase NUMERIC(14,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS category_rates(
    category TEXT PRIMARY KEY,
    rate NUMERIC(8,3) NOT NULL
);
CREATE TABLE IF NOT EXISTS products(
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    base_price NUMERIC(14,4) NOT NULL,
    rate NUMERIC(8,3) NOT NULL DEFAULT 100,
    enabled BOOLEAN DEFAULT true,
    ask_game_id BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders(
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    product_id TEXT,
    title TEXT,
    price NUMERIC(14,4),
    game_id TEXT,
    status TEXT DEFAULT 'PROCESSING',
    admin_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS payments(
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    amount NUMERIC(14,4),
    method TEXT,
    address TEXT,
    txid TEXT,
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS balance_logs(
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    amount NUMERIC(14,4),
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS coupons(
    code TEXT PRIMARY KEY,
    percent NUMERIC(8,3),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
"""
