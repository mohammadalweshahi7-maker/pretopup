from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from catalog import CATEGORIES, PARENT_MENUS, SUBCATEGORIES

# Telegram custom emoji IDs you sent for the main menu buttons.
# Important: icon_custom_emoji_id is supported only by newer Telegram Bot API / aiogram versions.
# If Telegram does not show the custom icon on some clients, the text fallback will still work.
EMOJI_IDS = {
    "voucher": "5987568986290657784",
    "wallet": "5276137490846075469",
    "orders": "6093382540784046658",
    "gameid": "5303466028448127877",
    "product_games": "5235606515833909907",
    "about": "5303162314130758043",
    "support": "5852800639188341430",
    "settings": "5366231924597604153",
}


def kb(text: str, emoji_id: str | None = None) -> KeyboardButton:
    """Create reply keyboard button with optional Telegram custom emoji icon."""
    if emoji_id:
        return KeyboardButton(text=text, icon_custom_emoji_id=emoji_id)
    return KeyboardButton(text=text)


MAIN = ReplyKeyboardMarkup(
    keyboard=[
        [
            kb("Voucher Products", EMOJI_IDS["voucher"]),
            kb("My Wallet", EMOJI_IDS["wallet"]),
        ],
        [
            kb("My Orders", EMOJI_IDS["orders"]),
            kb("Game ID", EMOJI_IDS["gameid"]),
        ],
        [
            kb("Product Games", EMOJI_IDS["product_games"]),
            kb("Language"),  # no custom emoji ID was provided; Telegram globe fallback can be used in messages.
        ],
        [
            kb("About", EMOJI_IDS["about"]),
            kb("Support", EMOJI_IDS["support"]),
        ],
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
            rows.append(row)
            row = []
    if row:
        rows.append(row)
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
        ("🇸🇦 العربية", "lang:ar"),
        ("🇺🇸 English", "lang:en"),
        ("🇷🇺 Русский", "lang:ru"),
        ("🇲🇲 မြန်မာ", "lang:my"),
        ("🇦🇿 Azərbaycan", "lang:az"),
    ], "home")
