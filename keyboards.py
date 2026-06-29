from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from catalog import CATEGORIES, PARENT_MENUS, SUBCATEGORIES

MAIN = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎮 Voucher Products"), KeyboardButton(text="👛 My Wallet")],
        [KeyboardButton(text="📊 My Orders"), KeyboardButton(text="🔤 Game ID")],
        [KeyboardButton(text="🎲 Product Games"), KeyboardButton(text="🌐 Language")],
        [KeyboardButton(text="‼️ About"), KeyboardButton(text="⚡ Support")],
    ],
    resize_keyboard=True,
)

def main_menu():
    return MAIN

def inline_menu(items: list[tuple[str, str]], back_cb: str | None = None, cols: int = 1) -> InlineKeyboardMarkup:
    rows, row = [], []
    for text, cb in items:
        row.append(InlineKeyboardButton(text=text, callback_data=cb))
        if len(row) == cols:
            rows.append(row); row=[]
    if row: rows.append(row)
    if back_cb:
        rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def voucher_categories():
    return inline_menu([(CATEGORIES[c], f"cat:{c}") for c in PARENT_MENUS["voucher"]], "home")

def game_categories():
    return inline_menu([(CATEGORIES[c], f"cat:{c}") for c in PARENT_MENUS["gameid"]], "home")

def subcats(parent: str):
    return inline_menu([(CATEGORIES[c], f"cat:{c}") for c in SUBCATEGORIES[parent]], "voucher")

def products_keyboard(products, back: str):
    buttons = []
    for p in products:
        price = round(float(p["base_price"]) * float(p["rate"]) / 100, 2)
        buttons.append((f"{p['title']} | {price:.2f} USDT | ✅ Available", f"buy:{p['id']}"))
    return inline_menu(buttons, back)

def wallet_keyboard():
    return inline_menu([
        ("USDT BEP20", "pay:BEP20"),
        ("USDT TRC20", "pay:TRC20"),
        ("Bybit ID", "pay:BYBIT"),
        ("📊 📝 Transaction History", "txhistory"),
        ("⬅️ Back to Menu", "home"),
    ])

def invoice_keyboard(method: str):
    return inline_menu([
        ("📋 Copy Address", f"copy:{method}"),
        ("❌ Cancel", "cancelpay"),
    ])

def langs_keyboard():
    return inline_menu([
        ("🇸🇦 العربية", "lang:ar"), ("🇺🇸 English", "lang:en"), ("🇷🇺 Русский", "lang:ru"),
        ("🇲🇲 မြန်မာ", "lang:my"), ("🇦🇿 Azərbaycan", "lang:az"),
    ], "home")
