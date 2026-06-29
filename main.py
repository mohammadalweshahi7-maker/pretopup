from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from dotenv import load_dotenv

from catalog import CATEGORIES, PARENT_MENUS, SUBCATEGORIES, FIXED_RATE_CATEGORIES
from config import config
import database as db
import keyboards as kb

load_dotenv()
logging.basicConfig(level=logging.INFO)
router = Router()

class UserFlow(StatesGroup):
    waiting_game_id = State()
    waiting_payment_amount = State()
    waiting_txid = State()
    waiting_support = State()

class AdminFlow(StatesGroup):
    waiting_broadcast = State()

pending_products: dict[int, str] = {}
pending_pay_method: dict[int, str] = {}

BOT: Bot | None = None

def admin_only(message: Message) -> bool:
    return message.from_user and message.from_user.id == config.admin_id

async def notify_admin(text: str, reply_markup=None):
    if BOT:
        try:
            await BOT.send_message(config.admin_id, text, reply_markup=reply_markup)
        except Exception as e:
            logging.warning("admin notify failed: %s", e)

async def user_guard(message: Message) -> bool:
    if not message.from_user:
        return False
    new = await db.create_or_update_user(message.from_user)
    if new and message.from_user.id != config.admin_id:
        await notify_admin(
            f"🆕 New user started bot\n\n"
            f"ID: <code>{message.from_user.id}</code>\n"
            f"Name: {message.from_user.first_name or '-'}\n"
            f"Username: @{message.from_user.username if message.from_user.username else '-'}"
        )
    u = await db.get_user(message.from_user.id)
    if u and u["is_banned"]:
        await message.answer("⛔ You are banned.")
        return False
    return True

@router.message(CommandStart())
async def start(message: Message):
    if not await user_guard(message): return
    await message.answer(
        "Welcome to Prime Topup! 🎮\n\nChoose an option from the menu below.",
        reply_markup=kb.main_menu()
    )

@router.message(F.text == "🎮 Voucher Products")
async def voucher(message: Message):
    if not await user_guard(message): return
    await message.answer("Voucher Products\n\n📂 Select Category:\n✨ 📊 Select one:", reply_markup=kb.voucher_categories())

@router.message(F.text == "🔤 Game ID")
async def game_id(message: Message):
    if not await user_guard(message): return
    await message.answer("Select Topup Game:\n\nTotal active game categories found. Select one:", reply_markup=kb.game_categories())

@router.message(F.text == "👛 My Wallet")
async def wallet(message: Message):
    if not await user_guard(message): return
    u = await db.get_user(message.from_user.id)
    bal = float(u["balance"] or 0) if u else 0
    text = (
        '<tg-emoji emoji-id="5276137490846075469">👛</tg-emoji> <b>Your Wallet Information</b>\n'
        '<tg-emoji emoji-id="5987568986290657784">🎮</tg-emoji> '
        f"Hello, {message.from_user.first_name or 'User'}! Here’s your current balance:\n\n"
        '<tg-emoji emoji-id="5303466028448127877">🔤</tg-emoji> <b>Telegram ID:</b>\n'
        f"<code>{message.from_user.id}</code>\n\n"
        '<tg-emoji emoji-id="5388622778817589921">💰</tg-emoji> <b>Current Balance:</b>\n'
        f"<code>{bal:.4f} $</code>\n"
        '<tg-emoji emoji-id="6093382540784046658">📊</tg-emoji> ✨ What would you like to do next? '
        "You can top up your balance using one of the following methods:"
    )
    await message.answer(text, reply_markup=kb.wallet_keyboard())

@router.message(F.text == "📊 My Orders")
async def my_orders(message: Message):
    if not await user_guard(message): return
    rows = await db.recent_orders(message.from_user.id)
    if not rows:
        await message.answer("📦 You have no orders yet.")
        return
    text = "📦 <b>My Orders</b>\n\n" + "\n\n".join(
        f"#{r['id']} | {r['title']}\n💰 {float(r['price']):.2f} USDT | {r['status']}\n📅 {r['created_at'].strftime('%d.%m.%Y %H:%M')}"
        for r in rows
    )
    await message.answer(text)

@router.message(F.text == "🌐 Language")
async def language(message: Message):
    if not await user_guard(message): return
    await message.answer("🌐 اختر اللغة / Choose Language", reply_markup=kb.langs_keyboard())

@router.message(F.text == "‼️ About")
async def about(message: Message):
    await message.answer(
        "‼️ <b>About Prime Topup</b>\n\n"
        "Prime Topup provides game top-ups and digital gift cards.\n\n"
        "✅ Codes are original and valid for storage up to 1 year.\n"
        "✅ Orders are processed fast.\n"
        "✅ Top up your wallet using USDT BEP20, USDT TRC20, or Bybit.\n"
        "✅ Use your wallet balance to place orders.\n\n"
        "For help, contact Support."
    )

@router.message(F.text == "⚡ Support")
async def support(message: Message, state: FSMContext):
    await message.answer(
        f"📞 <b>Contact Support</b>\n\n"
        f"👤 Telegram Support\n{config.support_username}\n\n"
        f"📢 Official Channel\n{config.channel_url}\n\n"
        "You can also send your message here and the admin will receive it."
    )
    await state.set_state(UserFlow.waiting_support)

@router.message(UserFlow.waiting_support)
async def support_msg(message: Message, state: FSMContext):
    await notify_admin(
        f"📩 Support message\nFrom: <code>{message.from_user.id}</code> @{message.from_user.username or '-'}\n\n{message.text or '[non-text message]'}"
    )
    await message.answer("✅ Your message has been sent to support.")
    await state.clear()

@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery):
    await call.message.answer("Main menu", reply_markup=kb.main_menu())
    await call.answer()

@router.callback_query(F.data == "voucher")
async def cb_voucher(call: CallbackQuery):
    await call.message.edit_text("Voucher Products\n\n📂 Select Category:\n✨ 📊 Select one:", reply_markup=kb.voucher_categories())
    await call.answer()

@router.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery):
    cat = call.data.split(":",1)[1]
    if cat in SUBCATEGORIES:
        msg = f"{CATEGORIES[cat]}\n📂 Select Category:\n\n✨ 📊 Total {len(SUBCATEGORIES[cat])} active subcategories found. Select one:"
        await call.message.edit_text(msg, reply_markup=kb.subcats(cat))
        await call.answer(); return
    products = await db.get_products(cat)
    if not products:
        await call.answer("No products available", show_alert=True); return
    parent_back = "gameid" if cat in PARENT_MENUS["gameid"] else "voucher"
    title = CATEGORIES.get(cat, cat)
    await call.message.edit_text(
        f"{title}\n\n✨ Here are some amazing products we have for you:",
        reply_markup=kb.products_keyboard(products, parent_back)
    )
    await call.answer()

@router.callback_query(F.data == "gameid")
async def cb_gameid(call: CallbackQuery):
    await call.message.edit_text("Select Topup Game:\n\nTotal active game categories found. Select one:", reply_markup=kb.game_categories())
    await call.answer()

@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, state: FSMContext):
    product_id = call.data.split(":",1)[1]
    product = await db.get_product(product_id)
    if not product:
        await call.answer("Product unavailable", show_alert=True); return
    price = round(float(product["base_price"]) * float(product["rate"]) / 100, 2)
    if product["ask_game_id"]:
        pending_products[call.from_user.id] = product_id
        await call.message.answer(f"{product['title']}\n💰 Price: {price:.2f} USDT\n\n📝 Enter your Game ID number:")
        await state.set_state(UserFlow.waiting_game_id)
    else:
        order = await db.create_order(call.from_user.id, product_id, product["title"], price)
        if not order:
            await call.message.answer("❌ You do not have enough balance. Please top up your wallet.")
        elif isinstance(order, dict) and order.get("error") == "MIN":
            await call.message.answer(f"❌ Minimum purchase amount: {float(order['minimum']):.2f} USDT")
        else:
            await call.message.answer("⏳ Your order is being processed. You'll be notified once it's complete.")
            await notify_admin(
                f"🆕 New voucher order\n"
                f"Order: #{order['id']}\nUser: <code>{call.from_user.id}</code> @{call.from_user.username or '-'}\n"
                f"Product: {product['title']}\nPrice: {price:.2f} USDT\n\nReply: /reply {call.from_user.id} MESSAGE"
            )
    await call.answer()

@router.message(UserFlow.waiting_game_id)
async def got_game_id(message: Message, state: FSMContext):
    product_id = pending_products.pop(message.from_user.id, None)
    if not product_id:
        await state.clear(); return
    product = await db.get_product(product_id)
    price = round(float(product["base_price"]) * float(product["rate"]) / 100, 2)
    order = await db.create_order(message.from_user.id, product_id, product["title"], price, message.text.strip())
    if not order:
        await message.answer("❌ You do not have enough balance. Please top up your wallet.")
    elif isinstance(order, dict) and order.get("error") == "MIN":
        await message.answer(f"❌ Minimum purchase amount: {float(order['minimum']):.2f} USDT")
    else:
        await message.answer("⏳ Your order is being processed. You'll be notified once it's complete.")
        await notify_admin(
            f"🆕 New Game ID order\n"
            f"Order: #{order['id']}\nUser: <code>{message.from_user.id}</code> @{message.from_user.username or '-'}\n"
            f"Product: {product['title']}\nPrice: {price:.2f} USDT\nGame ID: <code>{message.text.strip()}</code>\n\n"
            f"Reply: /reply {message.from_user.id} MESSAGE"
        )
    await state.clear()

@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(call: CallbackQuery, state: FSMContext):
    method = call.data.split(":",1)[1]
    pending_pay_method[call.from_user.id] = method
    if method == "BYBIT":
        await call.message.answer(f"💳 Bybit ID\n\nSend payment to Bybit ID:\n<code>{config.bybit_id}</code>\n\nAfter payment, send TXID or screenshot details to support.")
        await call.answer(); return
    label = "BEP20" if method == "BEP20" else "TRC20"
    chain = "BEP20 / BSC" if method == "BEP20" else "TRC20 / TRON"
    await call.message.answer(
        f"💳 {label}\n\n📝 Enter the amount in USDT\nExample: 5\n\n"
        f"✍️ Enter the USDT amount you want to reserve for {chain}.\n\n"
        "⏱ This session will be reserved for 10 minutes.\n"
        "❌ If you want to cancel the process, tap the Cancel button below.\n"
        "⚠️ If the same amount is already reserved, please choose another amount or try again later."
    )
    await state.set_state(UserFlow.waiting_payment_amount)
    await call.answer()

@router.message(UserFlow.waiting_payment_amount)
async def payment_amount(message: Message, state: FSMContext):
    try:
        amount = round(float(message.text.strip().replace(",", ".")), 2)
        if amount <= 0: raise ValueError
    except Exception:
        await message.answer("❌ Please enter a valid amount, example: 5")
        return
    method = pending_pay_method.get(message.from_user.id, "BEP20")
    address = config.bep20_address if method == "BEP20" else config.trc20_address
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.create_payment(message.from_user.id, amount, method, address, expires)
    chain = "BSC / BEP20" if method == "BEP20" else "TRC20 / TRON"
    await message.answer(
        f"💰 Kindly deposit exactly <b>{amount:.2f} USDT</b> ({chain}).\n\n"
        f"📋 <b>Payment Address</b>\n<code>{address}</code>\n\n"
        "☝️ Tap and hold the address to copy.\n\n"
        f"⏰ This session will expire in 10 minutes ({expires.strftime('%d.%m.%Y %H:%M UTC')}).\n"
        "⬇️ After payment, send the Transaction ID (TXID) here.\n\n"
        "⚠️ Only payments made after this session was created will be accepted. Old TXIDs will not be accepted.\n"
        f"⚠️ The TXID amount must be exactly {amount:.2f} USDT.",
        reply_markup=kb.invoice_keyboard(method)
    )
    await state.set_state(UserFlow.waiting_txid)

@router.message(UserFlow.waiting_txid)
async def txid_received(message: Message, state: FSMContext):
    await db.execute("""UPDATE payments SET txid=$2, status='WAITING_ADMIN' WHERE user_id=$1 AND status='PENDING'""", message.from_user.id, message.text.strip())
    await message.answer("✅ TXID received. Your payment is being reviewed.")
    await notify_admin(f"💳 New payment TXID\nUser: <code>{message.from_user.id}</code>\nTXID: <code>{message.text.strip()}</code>\nUse /addbalance USER_ID AMOUNT after confirmation.")
    await state.clear()

@router.callback_query(F.data.startswith("copy:"))
async def copy_addr(call: CallbackQuery):
    method = call.data.split(":",1)[1]
    address = config.bep20_address if method == "BEP20" else config.trc20_address
    await call.message.answer(f"<code>{address}</code>")
    await call.answer("Address sent as a copyable message.")

@router.callback_query(F.data == "cancelpay")
async def cancelpay(call: CallbackQuery, state: FSMContext):
    await db.cancel_pending_payment(call.from_user.id)
    await state.clear()
    await call.message.answer("❌ Payment session cancelled.")
    await call.answer()

@router.callback_query(F.data == "txhistory")
async def txhistory(call: CallbackQuery):
    rows = await db.latest_payments(call.from_user.id)
    if not rows:
        await call.message.answer("📊 📝 Transaction History\n\nNo transactions yet.")
        await call.answer(); return
    text = "📊 📝 <b>Transaction History</b>\n\n" + "\n\n".join(
        f"{'✅' if r['status']=='CONFIRMED' else '❌' if 'CANCEL' in r['status'] else '⏳'} #{r['id']} | {float(r['amount']):.2f} $ | {r['method']}\n"
        f"📅 {r['created_at'].strftime('%d.%m.%Y %H:%M')} | {r['status']}"
        for r in rows
    )
    await call.message.answer(text)
    await call.answer()

@router.callback_query(F.data.startswith("lang:"))
async def set_lang(call: CallbackQuery):
    lang = call.data.split(":",1)[1]
    await db.execute("UPDATE users SET language=$2 WHERE id=$1", call.from_user.id, lang)
    await call.message.answer("✅ Language saved.")
    await call.answer()

# Admin commands
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not admin_only(message): return
    await message.answer(ADMIN_HELP)

@router.message(Command("addbalance"))
async def cmd_addbalance(message: Message):
    if not admin_only(message): return
    try:
        _, uid, amount = message.text.split(maxsplit=2)
        await db.add_balance(int(uid), float(amount), "admin add")
        await message.answer("✅ Balance added.")
        await BOT.send_message(int(uid), f"✅ Your balance has been updated.\n+{float(amount):.2f} USDT")
    except Exception:
        await message.answer("Usage: /addbalance USER_ID AMOUNT")

@router.message(Command("removebalance"))
async def cmd_removebalance(message: Message):
    if not admin_only(message): return
    try:
        _, uid, amount = message.text.split(maxsplit=2)
        await db.add_balance(int(uid), -abs(float(amount)), "admin remove")
        await message.answer("✅ Balance removed.")
    except Exception:
        await message.answer("Usage: /removebalance USER_ID AMOUNT")

@router.message(Command("setbalance"))
async def cmd_setbalance(message: Message):
    if not admin_only(message): return
    try:
        _, uid, amount = message.text.split(maxsplit=2)
        await db.set_balance(int(uid), float(amount))
        await message.answer("✅ Balance set.")
    except Exception:
        await message.answer("Usage: /setbalance USER_ID AMOUNT")

@router.message(Command("check"))
async def cmd_check(message: Message):
    if not admin_only(message): return
    try:
        uid = int(message.text.split()[1])
        u = await db.get_user(uid)
        await message.answer(str(dict(u)) if u else "User not found")
    except Exception:
        await message.answer("Usage: /check USER_ID")

@router.message(Command("orders"))
async def cmd_orders(message: Message):
    if not admin_only(message): return
    rows = await db.recent_orders()
    await message.answer("📦 Orders\n\n" + "\n".join(f"#{r['id']} {r['user_id']} {r['title']} {float(r['price']):.2f} {r['status']}" for r in rows)[:3900])

@router.message(Command("reply"))
async def cmd_reply(message: Message):
    if not admin_only(message): return
    try:
        _, uid, text = message.text.split(maxsplit=2)
        await BOT.send_message(int(uid), text)
        await message.answer("✅ Sent.")
    except Exception:
        await message.answer("Usage: /reply USER_ID MESSAGE")

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not admin_only(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /broadcast MESSAGE"); return
    users = await db.all_users(); sent=0
    for u in users:
        try:
            await BOT.send_message(u["id"], parts[1]); sent += 1
            await asyncio.sleep(0.03)
        except Exception: pass
    await message.answer(f"✅ Broadcast sent to {sent} users.")

@router.message(Command("setmin"))
async def cmd_setmin(message: Message):
    if not admin_only(message): return
    try:
        _, uid, amount = message.text.split(maxsplit=2)
        await db.execute("INSERT INTO users(id) VALUES($1) ON CONFLICT DO NOTHING", int(uid))
        await db.execute("UPDATE users SET min_purchase=$2 WHERE id=$1", int(uid), float(amount))
        await message.answer("✅ Minimum updated.")
        await BOT.send_message(int(uid), f"✅ Your minimum purchase amount has been updated.\n\n💰 New Minimum Purchase:\n{float(amount):.2f} USDT")
    except Exception:
        await message.answer("Usage: /setmin USER_ID AMOUNT")

@router.message(Command("resetmin"))
async def cmd_resetmin(message: Message):
    if not admin_only(message): return
    try:
        uid = int(message.text.split()[1])
        await db.execute("UPDATE users SET min_purchase=NULL WHERE id=$1", uid)
        await BOT.send_message(uid, "✅ Your minimum purchase amount has been reset to the default value.")
        await message.answer("✅ Reset.")
    except Exception:
        await message.answer("Usage: /resetmin USER_ID")

@router.message(Command("setrate"))
async def cmd_setrate(message: Message):
    if not admin_only(message): return
    try:
        _, category, rate = message.text.split(maxsplit=2)
        await db.set_category_rate(category, float(rate))
        await message.answer(f"✅ Rate for {category} changed to {rate}%")
    except Exception:
        await message.answer("Usage: /setrate CATEGORY PERCENT")

@router.message(Command("setgamerate"))
async def cmd_setgamerate(message: Message):
    if not admin_only(message): return
    try:
        rate = float(message.text.split()[1])
        for cat in ["arena","baloot","zepeto","mobile_legends","league"]:
            await db.set_category_rate(cat, rate)
        await message.answer("✅ Game ID general rate updated. PUBG and Free Fire were not changed.")
    except Exception:
        await message.answer("Usage: /setgamerate PERCENT")

@router.message(Command("setcoderate"))
async def cmd_setcoderate(message: Message):
    if not admin_only(message): return
    try:
        rate = float(message.text.split()[1])
        await db.set_category_rate("pubg_voucher", rate)
        await message.answer("✅ PUBG code rate updated.")
    except Exception:
        await message.answer("Usage: /setcoderate PERCENT")

@router.message(Command("setprice"))
async def cmd_setprice(message: Message):
    if not admin_only(message): return
    try:
        _, _cat, pid, price = message.text.split(maxsplit=3)
        await db.set_price(pid, float(price))
        await message.answer("✅ Product price changed.")
    except Exception:
        await message.answer("Usage: /setprice CAT_KEY PRODUCT_ID PRICE")

@router.message(Command("addproduct"))
async def cmd_addproduct(message: Message):
    if not admin_only(message): return
    try:
        # /addproduct id|category|title|base_price|rate|ask_game_id(0/1)
        data = message.text.split(maxsplit=1)[1]
        pid, cat, title, base, rate, ask = [x.strip() for x in data.split("|")]
        await db.add_product(pid, cat, title, float(base), float(rate), ask == "1")
        await message.answer("✅ Product added/updated.")
    except Exception:
        await message.answer("Usage: /addproduct id|category|title|base_price|rate|ask_game_id(0/1)")

@router.message(Command("delproduct"))
async def cmd_delproduct(message: Message):
    if not admin_only(message): return
    try:
        pid = message.text.split()[1]
        await db.del_product(pid)
        await message.answer("✅ Product disabled/deleted.")
    except Exception:
        await message.answer("Usage: /delproduct PRODUCT_ID")

@router.message(Command("prices"))
async def cmd_prices(message: Message):
    if not admin_only(message): return
    rows = await db.fetch("SELECT id,category,title,base_price,rate FROM products WHERE enabled=true ORDER BY category,id")
    text = "Prices\n" + "\n".join(f"{r['category']} | {r['id']} | {r['title']} | {round(float(r['base_price'])*float(r['rate'])/100,2):.2f}" for r in rows)
    await send_text_file(message, "prices.txt", text)

@router.message(Command("payments"))
async def cmd_payments(message: Message):
    if not admin_only(message): return
    rows = await db.fetch("SELECT * FROM payments ORDER BY id DESC LIMIT 50")
    await message.answer("Payments\n" + "\n".join(f"#{r['id']} {r['user_id']} {r['amount']} {r['method']} {r['status']}" for r in rows)[:3900])

@router.message(Command("ban"))
async def cmd_ban(message: Message):
    if not admin_only(message): return
    try:
        uid=int(message.text.split()[1]); await db.execute("UPDATE users SET is_banned=true WHERE id=$1", uid); await message.answer("✅ Banned")
    except Exception: await message.answer("Usage: /ban USER_ID")

@router.message(Command("unban"))
async def cmd_unban(message: Message):
    if not admin_only(message): return
    try:
        uid=int(message.text.split()[1]); await db.execute("UPDATE users SET is_banned=false WHERE id=$1", uid); await message.answer("✅ Unbanned")
    except Exception: await message.answer("Usage: /unban USER_ID")

@router.message(Command("addcoupon","delcoupon","coupons","discount24","discountall"))
async def coupons_and_discounts(message: Message):
    if not admin_only(message): return
    cmd = message.text.split()[0]
    try:
        if cmd == "/addcoupon":
            _, code, pct = message.text.split(maxsplit=2)
            await db.execute("INSERT INTO coupons(code, percent) VALUES($1,$2) ON CONFLICT(code) DO UPDATE SET percent=$2", code.upper(), float(pct))
            await message.answer("✅ Coupon saved.")
        elif cmd == "/delcoupon":
            await db.execute("DELETE FROM coupons WHERE code=$1", message.text.split()[1].upper()); await message.answer("✅ Deleted.")
        elif cmd == "/coupons":
            rows = await db.fetch("SELECT * FROM coupons ORDER BY created_at DESC")
            await message.answer("Coupons\n" + "\n".join(f"{r['code']} {r['percent']}%" for r in rows) or "No coupons")
        elif cmd == "/discountall":
            pct = float(message.text.split()[1])
            await db.execute("UPDATE products SET rate=$1", pct)
            await message.answer("✅ All product rates changed.")
        else:
            await message.answer("/discount24 saved as placeholder. Use /setrate or /discountall for active changes.")
    except Exception:
        await message.answer("Coupon/discount command format error.")

async def export_csv(message: Message, filename: str, rows):
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(dict(rows[0]).keys()))
        writer.writeheader()
        for r in rows: writer.writerow({k: str(v) for k, v in dict(r).items()})
    path = Path(filename); path.write_text(output.getvalue(), encoding="utf-8")
    await message.answer_document(FSInputFile(path)); path.unlink(missing_ok=True)

async def send_text_file(message: Message, filename: str, text: str):
    path = Path(filename); path.write_text(text, encoding="utf-8")
    await message.answer_document(FSInputFile(path)); path.unlink(missing_ok=True)

@router.message(Command("exportusers"))
async def export_users(message: Message):
    if admin_only(message): await export_csv(message, "users.csv", await db.all_users())

@router.message(Command("exportorders"))
async def export_orders(message: Message):
    if admin_only(message): await export_csv(message, "orders.csv", await db.all_orders())

@router.message(Command("exportbalances"))
async def export_balances(message: Message):
    if admin_only(message): await export_csv(message, "balances.csv", await db.balances())

@router.message(Command("backup"))
async def backup(message: Message):
    if not admin_only(message): return
    data = await db.backup_json()
    path = Path("backup_prime_topup.json")
    path.write_text(json.dumps(data, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    await message.answer_document(FSInputFile(path)); path.unlink(missing_ok=True)

@router.message(Command("restore"))
async def restore(message: Message):
    if not admin_only(message): return
    await message.answer("/restore is protected. Uploading and restoring JSON should be done manually after checking the backup file to avoid data loss.")

@router.message()
async def any_message(message: Message):
    if not await user_guard(message): return
    if message.from_user.id != config.admin_id:
        await notify_admin(f"💬 User message\nFrom: <code>{message.from_user.id}</code> @{message.from_user.username or '-'}\n\n{message.text or '[non-text message]'}")
    await message.answer("Please choose an option from the menu.", reply_markup=kb.main_menu())

ADMIN_HELP = """<b>MD STORE Admin Panel</b>

/addbalance USER_ID AMOUNT
/removebalance USER_ID AMOUNT
/setbalance USER_ID AMOUNT
/check USER_ID
/orders
/broadcast MESSAGE
/addcoupon CODE PERCENT
/delcoupon CODE
/coupons
/ban USER_ID
/unban USER_ID
/setmin USER_ID AMOUNT
/resetmin USER_ID
/discount24
/prices
/setprice CAT_KEY PRODUCT_ID PRICE
/discountall PERCENT
/payments
/reply USER_ID MESSAGE
/addproduct id|category|title|base_price|rate|ask_game_id(0/1)
/delproduct PRODUCT_ID
/setrate CATEGORY PERCENT
/setgamerate PERCENT
/setcoderate PERCENT
/backup
/restore
/exportusers
/exportorders
/exportbalances
"""

async def main():
    global BOT
    if not config.bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    await db.init_db()
    BOT = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await BOT.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(BOT)

if __name__ == "__main__":
    asyncio.run(main())
