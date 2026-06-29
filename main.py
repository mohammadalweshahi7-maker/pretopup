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
from aiogram.types import CallbackQuery, FSInputFile, Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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

# ---------------- Prime Topup UI, custom icons, and translations ----------------
# Telegram Bot API supports icon_custom_emoji_id for ReplyKeyboard and InlineKeyboard buttons in recent Bot API versions.
# Keep the visible button text clean; Telegram shows the custom emoji before the text when the bot/account is eligible.
CUSTOM_EMOJI = {
    # Main menu / wallet icons
    "voucher": "5987568986290657784",
    "wallet": "5276137490846075469",
    "orders": "6093382540784046658",
    "game_id": "5303466028448127877",
    "settings": "5366231924597604153",
    "product_games": "5235606515833909907",
    "about": "5303162314130758043",
    "support": "5852800639188341430",
    "balance": "5388622778817589921",

    # Voucher / product category icons sent by admin
    "roblox": "5388921730016240894",
    "steam": "5318801707394695066",
    "itunes": "5332512686112520612",
    "pubg": "5314544952422704045",
    "playstation": "5363934885893389858",
    "razer": "5201873447554145566",
    "yalla": "5911296461672289184",
    "freefire": "6048398234441750217",
}

CATEGORY_ICON_IDS = {
    "roblox": CUSTOM_EMOJI["roblox"],
    "steam": CUSTOM_EMOJI["steam"],
    "itunes": CUSTOM_EMOJI["itunes"],
    "ios": CUSTOM_EMOJI["itunes"],
    "apple": CUSTOM_EMOJI["itunes"],
    "pubg": CUSTOM_EMOJI["pubg"],
    "playstation": CUSTOM_EMOJI["playstation"],
    "psn": CUSTOM_EMOJI["playstation"],
    "razer": CUSTOM_EMOJI["razer"],
    "yalla": CUSTOM_EMOJI["yalla"],
    "ludo": CUSTOM_EMOJI["yalla"],
    "freefire": CUSTOM_EMOJI["freefire"],
    "free_fire": CUSTOM_EMOJI["freefire"],
    "garena": CUSTOM_EMOJI["freefire"],
    "valorant": CUSTOM_EMOJI["product_games"],
    "arena": CUSTOM_EMOJI["product_games"],
    "baloot": CUSTOM_EMOJI["product_games"],
    "zepeto": CUSTOM_EMOJI["product_games"],
    "mobile": CUSTOM_EMOJI["product_games"],
    "league": CUSTOM_EMOJI["product_games"],
}

LABELS = {
    # Reliable ReplyKeyboard: visible emoji in the button text (Product Games removed as requested).
    "en": {
        "voucher": "🛒 Voucher Products", "wallet": "💰 My Wallet", "orders": "📊 My Orders",
        "gameid": "🆔 Game ID", "product_games": "🎲 Product Games", "language": "🌐 Languages",
        "about": "ℹ️ About", "support": "☎️ Contact Support",
    },
    "ar": {
        "voucher": "🛒 المنتجات", "wallet": "💰 محفظتي", "orders": "📊 طلباتي",
        "gameid": "🆔 شحن ID", "product_games": "🎲 منتجات الألعاب", "language": "🌐 اللغات",
        "about": "ℹ️ حول البوت", "support": "☎️ الدعم",
    },
    "ru": {
        "voucher": "🛒 Товары", "wallet": "💰 Кошелёк", "orders": "📊 Заказы",
        "gameid": "🆔 Game ID", "product_games": "🎲 Игры", "language": "🌐 Языки",
        "about": "ℹ️ О боте", "support": "☎️ Поддержка",
    },
    "my": {
        "voucher": "🛒 Products", "wallet": "💰 Wallet", "orders": "📊 Orders",
        "gameid": "🆔 Game ID", "product_games": "🎲 Games", "language": "🌐 Languages",
        "about": "ℹ️ About", "support": "☎️ Support",
    },
    "az": {
        "voucher": "🛒 Məhsullar", "wallet": "💰 Pul kisəsi", "orders": "📊 Sifarişlər",
        "gameid": "🆔 Game ID", "product_games": "🎲 Oyunlar", "language": "🌐 Dillər",
        "about": "ℹ️ Haqqında", "support": "☎️ Dəstək",
    },
}
TEXTS = {
    "en": {
        "start": "Welcome to <b>Prime Topup</b>! 🎮\n\nChoose an option from the menu below.",
        "voucher_title": "Voucher Products\n\n📂 Select Category:\n✨ 📊 Select one:",
        "game_title": "Select Topup Game:\n\nTotal active game categories found. Select one:",
        "choose_lang": "🌐 Choose Language",
        "lang_saved": "✅ Language saved.",
        "no_orders": "📦 You have no orders yet.",
        "generic": "Please choose an option from the menu.",
        "support_sent": "✅ Your message has been sent to support.",
        "no_balance": "❌ You do not have enough balance. Please top up your wallet.",
        "processing": "⏳ Your order is being processed. You'll be notified once it's complete.",
    },
    "ar": {
        "start": "مرحباً بك في <b>Prime Topup</b>! 🎮\n\nاختر خياراً من القائمة بالأسفل.",
        "voucher_title": "منتجات البطاقات\n\n📂 اختر القسم:\n✨ 📊 اختر واحداً:",
        "game_title": "اختر لعبة الشحن:\n\nتم العثور على أقسام شحن نشطة. اختر واحداً:",
        "choose_lang": "🌐 اختر اللغة",
        "lang_saved": "✅ تم حفظ اللغة.",
        "no_orders": "📦 لا يوجد لديك طلبات حتى الآن.",
        "generic": "يرجى اختيار خيار من القائمة.",
        "support_sent": "✅ تم إرسال رسالتك للدعم.",
        "no_balance": "❌ ليس لديك رصيد كافٍ. يرجى شحن محفظتك أولاً.",
        "processing": "⏳ طلبك قيد المعالجة. سيتم إشعارك عند اكتماله.",
    },
    "ru": {
        "start": "Добро пожаловать в <b>Prime Topup</b>! 🎮\n\nВыберите пункт в меню ниже.",
        "voucher_title": "Цифровые товары\n\n📂 Выберите категорию:\n✨ 📊 Выберите один вариант:",
        "game_title": "Выберите игру для пополнения:\n\nНайдены активные категории. Выберите одну:",
        "choose_lang": "🌐 Выберите язык",
        "lang_saved": "✅ Язык сохранён.",
        "no_orders": "📦 У вас пока нет заказов.",
        "generic": "Пожалуйста, выберите пункт меню.",
        "support_sent": "✅ Ваше сообщение отправлено в поддержку.",
        "no_balance": "❌ Недостаточно средств. Пополните кошелёк.",
        "processing": "⏳ Ваш заказ обрабатывается. Мы уведомим вас после завершения.",
    },
    "my": {
        "start": "<b>Prime Topup</b> မှ ကြိုဆိုပါတယ်! 🎮\n\nအောက်ပါ menu မှရွေးချယ်ပါ။",
        "voucher_title": "Voucher Products\n\n📂 Category ရွေးပါ:\n✨ 📊 တစ်ခုရွေးပါ:",
        "game_title": "Topup Game ရွေးပါ:\n\nActive categories တွေ့ရှိပါသည်။ တစ်ခုရွေးပါ:",
        "choose_lang": "🌐 Language ရွေးပါ",
        "lang_saved": "✅ Language saved.",
        "no_orders": "📦 Orders မရှိသေးပါ။",
        "generic": "Menu မှရွေးချယ်ပါ။",
        "support_sent": "✅ Support သို့ပို့ပြီးပါပြီ။",
        "no_balance": "❌ Balance မလုံလောက်ပါ။ Wallet ကို top up လုပ်ပါ။",
        "processing": "⏳ Your order is being processed. You'll be notified once it's complete.",
    },
    "az": {
        "start": "<b>Prime Topup</b>-a xoş gəlmisiniz! 🎮\n\nAşağıdakı menyudan seçim edin.",
        "voucher_title": "Voucher Products\n\n📂 Kateqoriya seçin:\n✨ 📊 Birini seçin:",
        "game_title": "Topup oyununu seçin:\n\nAktiv kateqoriyalar tapıldı. Birini seçin:",
        "choose_lang": "🌐 Dil seçin",
        "lang_saved": "✅ Dil yadda saxlanıldı.",
        "no_orders": "📦 Hələ sifarişiniz yoxdur.",
        "generic": "Zəhmət olmasa menyudan seçim edin.",
        "support_sent": "✅ Mesajınız dəstəyə göndərildi.",
        "no_balance": "❌ Balansınız kifayət deyil. Zəhmət olmasa cüzdanınızı artırın.",
        "processing": "⏳ Sifarişiniz emal olunur. Tamamlandıqda sizə bildiriləcək.",
    },
}

def icon(name: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{CUSTOM_EMOJI[name]}">{fallback}</tg-emoji>'

async def get_lang(user_id: int | None) -> str:
    if not user_id:
        return "en"
    try:
        u = await db.get_user(user_id)
        lang = (u["language"] if u and u["language"] else "en")
        return lang if lang in TEXTS else "en"
    except Exception:
        return "en"

async def tr(user_id: int | None, key: str) -> str:
    lang = await get_lang(user_id)
    return TEXTS.get(lang, TEXTS["en"]).get(key, TEXTS["en"].get(key, key))

def _button_rows(labels: dict[str, str]):
    # Product Games button removed from the bottom keyboard as requested.
    return [
        [rk_button(labels["voucher"]), rk_button(labels["wallet"])],
        [rk_button(labels["orders"]), rk_button(labels["gameid"])],
        [rk_button(labels["language"]), rk_button(labels["about"])],
        [rk_button(labels["support"])],
    ]

def main_menu_lang(lang: str = "en") -> ReplyKeyboardMarkup:
    labels = LABELS.get(lang, LABELS["en"])
    return ReplyKeyboardMarkup(keyboard=_button_rows(labels), resize_keyboard=True)

def _strip_button_emoji(text: str) -> str:
    # Accept old and new keyboard labels. This removes the leading emoji + space only.
    parts = text.split(" ", 1)
    if len(parts) == 2 and not parts[0].isalnum():
        return parts[1]
    return text

def all_labels(key: str) -> set[str]:
    # Users send the visible text when pressing a keyboard button.
    vals = {v[key] for v in LABELS.values()}
    vals |= {_strip_button_emoji(v) for v in vals}
    return vals

def _clean_key(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")

def category_icon_id(cat_key: str, title: str | None = None) -> str | None:
    haystack = f"{cat_key} {title or ''}".lower()
    haystack_clean = _clean_key(haystack)
    for key, icon_id in CATEGORY_ICON_IDS.items():
        if key in haystack or key in haystack_clean:
            return icon_id
    return None

def category_style(cat_key: str, title: str | None = None) -> str:
    # Telegram Bot API button styles: primary = blue, danger = red, success = green.
    return "primary"

def rk_button(text: str, icon_id: str | None = None) -> KeyboardButton:
    # icon_custom_emoji_id requires recent Bot API / aiogram. If unsupported by the account, Telegram may ignore the icon.
    kwargs = {"text": text}
    if icon_id:
        kwargs["icon_custom_emoji_id"] = icon_id
    return KeyboardButton(**kwargs)

def ik_button(text: str, callback_data: str, icon_id: str | None = None, style: str | None = None) -> InlineKeyboardButton:
    kwargs = {"text": text, "callback_data": callback_data}
    if icon_id:
        kwargs["icon_custom_emoji_id"] = icon_id
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)

def _patch_keyboards():
    def main_menu():
        # default menu; translated menu is sent after language changes
        return main_menu_lang("en")

    def voucher_categories():
        rows = []
        for cat in PARENT_MENUS.get("voucher", []):
            title = CATEGORIES.get(cat, cat)
            rows.append([ik_button(title, f"cat:{cat}", category_icon_id(cat, title), "primary")])
        rows.append([ik_button("Back", "home", style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def game_categories():
        rows = []
        for cat in PARENT_MENUS.get("gameid", []):
            title = CATEGORIES.get(cat, cat)
            rows.append([ik_button(title, f"cat:{cat}", category_icon_id(cat, title), "primary")])
        rows.append([ik_button("Back", "home", style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def subcats(parent: str):
        rows = []
        for cat in SUBCATEGORIES.get(parent, []):
            title = CATEGORIES.get(cat, cat)
            rows.append([ik_button(title, f"cat:{cat}", category_icon_id(cat, title), "primary")])
        rows.append([ik_button("Back", "voucher", style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def products_keyboard(products, parent_back: str):
        rows = []
        for r in products:
            price = round(float(r["base_price"]) * float(r["rate"]) / 100, 2)
            title = str(r["title"])
            # clean product button style: no stock, only Available
            rows.append([ik_button(f"{title} | {price:.2f} USDT | ✅ Available", f"buy:{r['id']}", style="primary")])
        rows.append([ik_button("Back", parent_back, style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def wallet_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button("USDT BEP20", "pay:BEP20", CUSTOM_EMOJI["wallet"], "primary"), ik_button("USDT TRC20", "pay:TRC20", CUSTOM_EMOJI["wallet"], "primary")],
            [ik_button("Bybit ID", "pay:BYBIT", CUSTOM_EMOJI["game_id"], "primary")],
            [ik_button("Transaction History", "txhistory", CUSTOM_EMOJI["orders"], "success")],
            [ik_button("Back to Menu", "home", style="danger")],
        ])

    def langs_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button("العربية", "lang:ar", CUSTOM_EMOJI["settings"])],
            [ik_button("English", "lang:en", CUSTOM_EMOJI["settings"])],
            [ik_button("Русский", "lang:ru", CUSTOM_EMOJI["settings"])],
            [ik_button("မြန်မာ", "lang:my", CUSTOM_EMOJI["settings"])],
            [ik_button("Azərbaycan", "lang:az", CUSTOM_EMOJI["settings"])],
            [ik_button("Cancel", "home", style="danger")],
        ])

    def invoice_keyboard(method: str):
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button("Copy Address", f"copy:{method}", style="success")],
            [ik_button("Cancel", "cancelpay", style="danger")],
        ])

    kb.main_menu = main_menu
    kb.voucher_categories = voucher_categories
    kb.game_categories = game_categories
    kb.subcats = subcats
    kb.products_keyboard = products_keyboard
    kb.wallet_keyboard = wallet_keyboard
    kb.langs_keyboard = langs_keyboard
    kb.invoice_keyboard = invoice_keyboard

_patch_keyboards()


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
    lang = await get_lang(message.from_user.id)
    await message.answer(
        await tr(message.from_user.id, "start"),
        reply_markup=main_menu_lang(lang)
    )

@router.message(F.text.in_(all_labels("voucher")))
async def voucher(message: Message):
    if not await user_guard(message): return
    await message.answer(await tr(message.from_user.id, "voucher_title"), reply_markup=kb.voucher_categories())

@router.message(F.text.in_(all_labels("gameid")))
async def game_id(message: Message):
    if not await user_guard(message): return
    await message.answer(await tr(message.from_user.id, "game_title"), reply_markup=kb.game_categories())

@router.message(F.text.in_(all_labels("wallet")))
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

@router.message(F.text.in_(all_labels("orders")))
async def my_orders(message: Message):
    if not await user_guard(message): return
    rows = await db.recent_orders(message.from_user.id)
    if not rows:
        await message.answer(await tr(message.from_user.id, "no_orders"))
        return
    text = "📦 <b>My Orders</b>\n\n" + "\n\n".join(
        f"#{r['id']} | {r['title']}\n💰 {float(r['price']):.2f} USDT | {r['status']}\n📅 {r['created_at'].strftime('%d.%m.%Y %H:%M')}"
        for r in rows
    )
    await message.answer(text)

@router.message(F.text.in_(all_labels("language")))
async def language(message: Message):
    if not await user_guard(message): return
    await message.answer(await tr(message.from_user.id, "choose_lang"), reply_markup=kb.langs_keyboard())

@router.message(F.text.in_(all_labels("about")))
async def about(message: Message):
    await message.answer(
        f'{icon("about", "‼️")} <b>About Prime Topup</b>\n\n'
        'Prime Topup is a digital service bot for game top-ups, voucher codes, and gift cards.\n\n'
        '<b>How it works:</b>\n'
        '1. Top up your wallet using USDT BEP20, USDT TRC20, or Bybit.\n'
        '2. Choose the product or game recharge you need.\n'
        '3. Pay from your wallet balance.\n'
        '4. Your order will be processed and you will be notified once it is complete.\n\n'
        '<b>Important information:</b>\n'
        '✅ All codes are original and safe.\n'
        '✅ Voucher codes are valid for storage up to 1 year.\n'
        '✅ Game ID orders are processed fast.\n'
        '✅ Wallet balance is used for all purchases.\n'
        '✅ You can track your orders and payment transactions inside the bot.\n'
        '✅ Multi-language support is available.\n\n'
        '<b>Support:</b>\n'
        f'For help, contact {config.support_username}\n'
        f'Official channel: {config.channel_url}'
    )

@router.message(F.text.in_(all_labels("support")))
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
    await message.answer(await tr(message.from_user.id, "support_sent"))
    await state.clear()

@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    await call.message.answer("Main menu", reply_markup=main_menu_lang(lang))
    await call.answer()

@router.callback_query(F.data == "voucher")
async def cb_voucher(call: CallbackQuery):
    await call.message.edit_text(await tr(call.from_user.id, "voucher_title"), reply_markup=kb.voucher_categories())
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
    await call.message.edit_text(await tr(call.from_user.id, "game_title"), reply_markup=kb.game_categories())
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
            await call.message.answer(await tr(call.from_user.id, "no_balance"))
        elif isinstance(order, dict) and order.get("error") == "MIN":
            await call.message.answer(f"❌ Minimum purchase amount: {float(order['minimum']):.2f} USDT")
        else:
            await call.message.answer(await tr(call.from_user.id, "processing"))
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
        await message.answer(await tr(message.from_user.id, "no_balance"))
    elif isinstance(order, dict) and order.get("error") == "MIN":
        await message.answer(f"❌ Minimum purchase amount: {float(order['minimum']):.2f} USDT")
    else:
        await message.answer(await tr(message.from_user.id, "processing"))
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
    await call.message.answer(await tr(call.from_user.id, "lang_saved"), reply_markup=main_menu_lang(lang))
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
    lang = await get_lang(message.from_user.id)
    await message.answer(await tr(message.from_user.id, "generic"), reply_markup=main_menu_lang(lang))

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
