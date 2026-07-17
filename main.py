from __future__ import annotations

import asyncio
import csv
import html
import io
import json
import logging
import re
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
    waiting_quantity = State()
    waiting_game_id = State()
    waiting_payment_amount = State()
    waiting_txid = State()
    waiting_support = State()
    waiting_bonus_code = State()

class AdminFlow(StatesGroup):
    waiting_broadcast = State()
    waiting_restore_file = State()

pending_products: dict[int, str] = {}
pending_pay_method: dict[int, str] = {}
# Track the latest bot UI message per user so menus and flows update in place
# instead of creating a new bot message after every button press.
last_ui_message: dict[int, tuple[int, int]] = {}

BOT: Bot | None = None

# Requested production values. Existing visual design and database remain unchanged.
SUPPORT_USERNAME = "@prime_Manaager"
BEP20_ADDRESS = "0x21412cac41dd664e97e4FAB0B1DB1874Da0048cA"
TRC20_ADDRESS = "TPhmLfuWvMK2MFuNgixqE62EbCN1TfGdHT"
APTOS_ADDRESS = "0x2f4165b8f2d036f768aa8b7df864223daaee9780682f82bb3077244aedee7840"

SPECIAL_PRODUCT_CATEGORIES = {
    "pre_order_cars": {
        "title": "🏎️ PRE ORDER CARS",
        "keywords": ("pre order car", "pre-order car", "car card", "cars"),
    },
    "metro_sword": {
        "title": "⚔️ METRO SWORD",
        "keywords": ("metro sword",),
    },
}

# Fixed IDs used by the special Ferrari / Metro purchase flows.
# They are seeded only when missing, so admin availability changes are preserved.
FERRARI_ONE_ID = "pre_order_car_1"
FERRARI_THREE_ID = "pre_order_car_3"
METRO_SWORD_ID = "metro_sword_fixed"
PREORDER_IMAGE_NAME = "photo_2026-07-12_10-04-04.jpg"

SPECIAL_PRODUCT_IDS = {
    "pre_order_cars": (FERRARI_ONE_ID, FERRARI_THREE_ID),
    "metro_sword": (METRO_SWORD_ID,),
}

SPECIAL_TEXT = {
    "en": {
        "ferrari_caption": "🏎️ <b>Ferrari Cards Available</b>\n\n⏳ Delivery time: up to 72 hours",
        "ferrari_one": "1 Card — 126 USDT",
        "ferrari_three": "3 Cards — 430 USDT",
        "metro_prompt": "⚔️ <b>METRO SWORD</b>\n\nPrice: 80 USDT\n\nPlease enter your PUBG Player ID:",
        "ferrari_prompt": "Please enter your PUBG Player ID:",
    },
    "ar": {
        "ferrari_caption": "🏎️ <b>بطاقات Ferrari متوفرة</b>\n\n⏳ مدة التسليم: خلال 72 ساعة كحد أقصى",
        "ferrari_one": "بطاقة واحدة — 126 USDT",
        "ferrari_three": "3 بطاقات — 430 USDT",
        "metro_prompt": "⚔️ <b>METRO SWORD</b>\n\nالسعر: 80 USDT\n\nأدخل معرف لاعب PUBG:",
        "ferrari_prompt": "أدخل معرف لاعب PUBG:",
    },
    "ru": {
        "ferrari_caption": "🏎️ <b>Карты Ferrari доступны</b>\n\n⏳ Срок доставки: до 72 часов",
        "ferrari_one": "1 карта — 126 USDT",
        "ferrari_three": "3 карты — 430 USDT",
        "metro_prompt": "⚔️ <b>METRO SWORD</b>\n\nЦена: 80 USDT\n\nВведите PUBG Player ID:",
        "ferrari_prompt": "Введите PUBG Player ID:",
    },
    "my": {
        "ferrari_caption": "🏎️ <b>Ferrari Cards Available</b>\n\n⏳ Delivery time: up to 72 hours",
        "ferrari_one": "1 Card — 126 USDT",
        "ferrari_three": "3 Cards — 430 USDT",
        "metro_prompt": "⚔️ <b>METRO SWORD</b>\n\nPrice: 80 USDT\n\nPlease enter your PUBG Player ID:",
        "ferrari_prompt": "Please enter your PUBG Player ID:",
    },
    "az": {
        "ferrari_caption": "🏎️ <b>Ferrari kartları mövcuddur</b>\n\n⏳ Çatdırılma müddəti: 72 saata qədər",
        "ferrari_one": "1 kart — 126 USDT",
        "ferrari_three": "3 kart — 430 USDT",
        "metro_prompt": "⚔️ <b>METRO SWORD</b>\n\nQiymət: 80 USDT\n\nPUBG oyunçu ID-sini daxil edin:",
        "ferrari_prompt": "PUBG oyunçu ID-sini daxil edin:",
    },
}

def special_text(lang: str, key: str) -> str:
    return SPECIAL_TEXT.get(lang, SPECIAL_TEXT["en"]).get(key, SPECIAL_TEXT["en"].get(key, key))

def preorder_image_path() -> Path | None:
    base = Path(__file__).resolve().parent
    exact = base / PREORDER_IMAGE_NAME
    if exact.exists():
        return exact
    for pattern in ("*ferrari*.jpg", "*ferrari*.jpeg", "*ferrari*.png", "*pre*order*car*.jpg", "photo_*.jpg"):
        matches = sorted(base.glob(pattern))
        if matches:
            return matches[0]
    return None

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
    "en": {
        "voucher": "🛒 Voucher Products", "wallet": "💰 My Wallet", "orders": "📊 My Orders",
        "gameid": "🆔 Game ID", "product_games": "🎲 Product Games", "language": "🌐 Languages",
        "about": "📜 Terms & Policies", "support": "☎️ Contact Support",
    },
    "ar": {
        "voucher": "🛒 المنتجات", "wallet": "💰 محفظتي", "orders": "📊 طلباتي",
        "gameid": "🆔 شحن ID", "product_games": "🎲 منتجات الألعاب", "language": "🌐 اللغات",
        "about": "📜 الشروط والسياسات", "support": "☎️ الدعم",
    },
    "ru": {
        "voucher": "🛒 Товары", "wallet": "💰 Кошелёк", "orders": "📊 Заказы",
        "gameid": "🆔 Game ID", "product_games": "🎲 Игры", "language": "🌐 Языки",
        "about": "📜 Условия и правила", "support": "☎️ Поддержка",
    },
    "my": {
        "voucher": "🛒 Products", "wallet": "💰 Wallet", "orders": "📊 Orders",
        "gameid": "🆔 Game ID", "product_games": "🎲 Games", "language": "🌐 Languages",
        "about": "📜 Terms & Policies", "support": "☎️ Support",
    },
    "az": {
        "voucher": "🛒 Məhsullar", "wallet": "💰 Pul kisəsi", "orders": "📊 Sifarişlər",
        "gameid": "🆔 Game ID", "product_games": "🎲 Oyunlar", "language": "🌐 Dillər",
        "about": "📜 Şərtlər və qaydalar", "support": "☎️ Dəstək",
    },
}

TEXTS = {
    "en": {
        "start": "🤖 Hello <b>{name}</b>, welcome to ✨ <b>Prime Bot</b> ✨\nYour gift card store bot!\n\n🔹 Browse gift cards\n\n🔹 Add balance to your account\n\n🔹 Buy gift cards easily\n\nPlease choose an option from the menu below:",
        "voucher_title": "Voucher Products\n\n📂 Select Category:\n✨ 📊 Select one:",
        "game_title": "Select Topup Game:\n\nTotal active game categories found. Select one:",
        "choose_lang": "🌐 Choose Language", "lang_saved": "✅ Language saved.",
        "no_orders": "📦 You have no orders yet.", "generic": "Please choose an option from the menu.",
        "support_sent": "✅ Your message has been sent to support.",
        "no_balance": "❌ You do not have enough balance. Please top up your wallet.",
        "processing": "✅ Your order was created successfully and is being processed automatically.",
        "main_menu": "Main menu", "back": "Back", "cancel": "Cancel", "available": "Available",
        "select_category": "📂 Select Category:\n\n✨ 📊 Select one:",
        "products_intro": "✨ Here are some amazing products we have for you:",
        "no_products": "No products available", "product_unavailable": "Product unavailable",
        "enter_quantity": "🧾 <b>{title}</b>\n💰 Unit price: <b>{price:.2f} USDT</b>\n\nEnter the quantity you need:",
        "invalid_quantity": "❌ Please enter a valid whole-number quantity greater than zero.",
        "enter_game_id": "📝 Enter the Game ID for this order:",
        "confirm_order": "🧾 <b>Order Confirmation</b>\n\nProduct: <b>{title}</b>\nQuantity: <b>{quantity}</b>\nTotal: <b>{total:.2f} USDT</b>{game_id_line}\n\nPlease confirm your order.",
        "confirm": "✅ Confirm", "order_cancel": "❌ Cancel", "cancelled": "❌ Order cancelled.",
        "min_purchase": "❌ Minimum purchase amount: {minimum:.2f} USDT",
        "my_orders": "📦 <b>My Orders</b>", "last_order": "🕘 <b>Last Order</b>",
        "quantity": "Quantity", "total": "Total", "status": "Status", "delivered": "Delivered",
        "wallet_title": "👛 <b>Your Wallet Information</b>",
        "wallet_hello": "🎮 Hello, {name}! Here’s your current balance:",
        "telegram_id": "🔤 <b>Telegram ID:</b>", "current_balance": "💰 <b>Current Balance:</b>",
        "wallet_next": "📊 ✨ What would you like to do next? You can top up your balance using one of the following methods:",
        "claim_bonus": "🎁 Claim Bonus", "enter_bonus": "🎁 Enter your bonus code:",
        "bonus_invalid": "❌ Invalid or unavailable bonus code.", "bonus_used": "❌ You have already used this bonus code.",
        "bonus_reserved": "✅ Coupon redeemed successfully!\n\nDeposit <b>{minimum:.2f} USDT</b> in one transaction to receive a <b>{bonus:.2f} USDT</b> bonus.",
        "bonus_activated": "🎁 Your deposit bonus has been activated successfully!\n+{bonus:.2f} USDT was added to your wallet.",
        "terms_title": "📜 <b>Terms & Policies</b>\n\nChoose a section:",
        "tos_btn": "📋 Terms of Service", "privacy_btn": "🔒 Privacy Policy", "rules_btn": "⚠️ Purchase Rules", "faq_btn": "❓ FAQ",
        "tos": "📋 <b>Terms of Service</b>\n\n• New users have no minimum deposit or purchase requirement and may deposit any amount and purchase any available product.\n• Some reseller features may require account verification or an account upgrade based on activity.\n• Orders are final after successful automatic delivery.\n• Prices may change according to market conditions.\n• Accounts involved in fraud or abuse may be suspended.",
        "privacy": "🔒 <b>Privacy Policy</b>\n\n• Customer names and account information are never shared with third parties.\n• Orders and transactions remain confidential.\n• Personal information is used only to process orders and provide support.\n• Customer data is never sold or distributed.",
        "rules": "⚠️ <b>Purchase Rules</b>\n\n• Prices may change without prior notice.\n• Digital voucher codes can be stored for up to one year unless stated otherwise.\n• Verify the product, quantity, and total before confirming.\n• Supported orders are delivered automatically 24/7.\n• Contact support immediately if a technical issue occurs.",
        "faq": "❓ <b>FAQ</b>\n\n<b>Is payment secure?</b>\nYes. Payments are processed through our secure automated system.\n\n<b>How long does delivery take?</b>\nAll supported products are delivered automatically 24/7 immediately after successful payment.\n\n<b>What payment methods are supported?</b>\nBybit ID, USDT BEP20, USDT TRC20, and Aptos.\n\n<b>Can I become a VIP reseller?</b>\nYes. Contact support for VIP requirements and benefits.",
        "support_title": "📞 <b>Contact Support</b>", "telegram_support": "👤 Telegram Support", "official_channel": "📢 Official Channel",
        "support_note": "You can also send your message here and the admin will receive it.",
        "payment_amount_prompt": "💳 {label}\n\n📝 Enter the amount in USDT\nExample: 5\n\n✍️ Enter the USDT amount you want to reserve for {chain}.\n\n⏱ This session will be reserved for 10 minutes.\n❌ Tap Cancel to stop.\n⚠️ If the same amount is already reserved, choose another amount.",
        "invalid_amount": "❌ Please enter a valid amount, example: 5", "txid_received": "✅ Hash / TXID received. Your payment is being reviewed.",
        "payment_cancelled": "❌ Payment session cancelled.", "copy_address": "Copy Address", "transaction_history": "Transaction History",
        "banned": "⛔ You are banned.", "address_sent": "Address sent as a copyable message.", "no_transactions": "No transactions yet.",
        "invoice": "💰 Kindly deposit exactly <b>{amount:.2f} USDT</b> ({chain}).\n\n📋 <b>Payment Address</b>\n<code>{address}</code>\n\n☝️ Tap and hold the address to copy.\n\n⬇️ After payment, send the Hash / TXID link here.",
        "bybit_payment": "💳 Bybit ID\n\nSend payment to Bybit ID:\n<code>{bybit_id}</code>\n\nAfter payment, send TXID or screenshot details to support.",
    },
    "ar": {
        "start": "🤖 مرحباً <b>{name}</b> في ✨ <b>برايم بوت</b> ✨\nبوت متجر بطاقات الهدايا!\n\n🔹 تصفح بطاقات الهدايا\n\n🔹 أضف رصيد إلى حسابك\n\n🔹 اشتر بطاقات الهدايا بسهولة\n\nيرجى اختيار خيار من القائمة أدناه:",
        "voucher_title": "منتجات البطاقات\n\n📂 اختر القسم:\n✨ 📊 اختر واحداً:",
        "game_title": "اختر لعبة الشحن:\n\nتم العثور على أقسام شحن نشطة. اختر واحداً:",
        "choose_lang": "🌐 اختر اللغة", "lang_saved": "✅ تم حفظ اللغة.",
        "no_orders": "📦 لا يوجد لديك طلبات حتى الآن.", "generic": "يرجى اختيار خيار من القائمة.",
        "support_sent": "✅ تم إرسال رسالتك للدعم.", "no_balance": "❌ ليس لديك رصيد كافٍ. يرجى شحن محفظتك أولاً.",
        "processing": "✅ تم إنشاء طلبك بنجاح ويجري تنفيذه تلقائيًا.",
        "main_menu": "القائمة الرئيسية", "back": "رجوع", "cancel": "إلغاء", "available": "متوفر",
        "select_category": "📂 اختر القسم:\n\n✨ 📊 اختر واحداً:", "products_intro": "✨ هذه المنتجات المتوفرة لدينا:",
        "no_products": "لا توجد منتجات متوفرة", "product_unavailable": "المنتج غير متوفر",
        "enter_quantity": "🧾 <b>{title}</b>\n💰 سعر القطعة: <b>{price:.2f} USDT</b>\n\nأدخل الكمية التي تحتاجها:",
        "invalid_quantity": "❌ أدخل كمية صحيحة أكبر من صفر.", "enter_game_id": "📝 أدخل Game ID الخاص بهذا الطلب:",
        "confirm_order": "🧾 <b>تأكيد الطلب</b>\n\nالمنتج: <b>{title}</b>\nالكمية: <b>{quantity}</b>\nالإجمالي: <b>{total:.2f} USDT</b>{game_id_line}\n\nيرجى تأكيد الطلب.",
        "confirm": "✅ تأكيد", "order_cancel": "❌ إلغاء", "cancelled": "❌ تم إلغاء الطلب.",
        "min_purchase": "❌ الحد الأدنى للشراء: {minimum:.2f} USDT",
        "my_orders": "📦 <b>طلباتي</b>", "last_order": "🕘 <b>آخر طلب</b>", "quantity": "الكمية", "total": "الإجمالي", "status": "الحالة", "delivered": "تم التسليم",
        "wallet_title": "👛 <b>معلومات محفظتك</b>", "wallet_hello": "🎮 مرحباً {name}! هذا رصيدك الحالي:",
        "telegram_id": "🔤 <b>معرّف تيليجرام:</b>", "current_balance": "💰 <b>الرصيد الحالي:</b>",
        "wallet_next": "📊 ✨ ماذا تريد أن تفعل؟ يمكنك شحن رصيدك بإحدى الطرق التالية:",
        "claim_bonus": "🎁 استرداد البونص", "enter_bonus": "🎁 أدخل كود البونص:",
        "bonus_invalid": "❌ كود البونص غير صحيح أو غير متاح.", "bonus_used": "❌ لقد استخدمت كود البونص مسبقًا.",
        "bonus_reserved": "✅ تم استرداد الكوبون بنجاح!\n\nقم بإيداع <b>{minimum:.2f} USDT</b> في عملية واحدة لتحصل على بونص <b>{bonus:.2f} USDT</b>.",
        "bonus_activated": "🎁 تم تفعيل بونص الإيداع بنجاح!\nتمت إضافة +{bonus:.2f} USDT إلى محفظتك.",
        "terms_title": "📜 <b>الشروط والسياسات</b>\n\nاختر القسم:",
        "tos_btn": "📋 شروط الاستخدام", "privacy_btn": "🔒 سياسة الخصوصية", "rules_btn": "⚠️ قواعد الشراء", "faq_btn": "❓ الأسئلة الشائعة",
        "tos": "📋 <b>شروط الاستخدام</b>\n\n• العملاء الجدد ليس لديهم حد أدنى للإيداع أو الشراء، ويمكنهم إيداع أي مبلغ وشراء أي منتج متوفر.\n• قد تتطلب بعض مزايا التجار التحقق أو ترقية الحساب حسب النشاط.\n• الطلبات نهائية بعد التسليم التلقائي الناجح.\n• قد تتغير الأسعار حسب السوق.\n• يحق لنا إيقاف الحسابات التي تستخدم النظام للاحتيال أو إساءة الاستخدام.",
        "privacy": "🔒 <b>سياسة الخصوصية</b>\n\n• لا نشارك أسماء العملاء أو بيانات حساباتهم مع أي طرف.\n• جميع الطلبات والمعاملات سرية.\n• تُستخدم البيانات فقط لمعالجة الطلبات وتقديم الدعم.\n• لا نبيع أو نوزع بيانات العملاء.",
        "rules": "⚠️ <b>قواعد الشراء</b>\n\n• قد تتغير الأسعار دون إشعار مسبق.\n• الأكواد الرقمية صالحة للتخزين حتى سنة ما لم يُذكر غير ذلك.\n• تحقق من المنتج والكمية والإجمالي قبل التأكيد.\n• جميع المنتجات المدعومة يتم تسليمها تلقائيًا على مدار 24/7.\n• تواصل مع الدعم فورًا عند حدوث مشكلة تقنية.",
        "faq": "❓ <b>الأسئلة الشائعة</b>\n\n<b>هل الدفع آمن؟</b>\nنعم، جميع المدفوعات تتم عبر نظامنا الآلي الآمن.\n\n<b>كم تستغرق عملية التسليم؟</b>\nجميع المنتجات المدعومة تُسلّم تلقائيًا على مدار 24/7 فور نجاح الدفع.\n\n<b>ما طرق الدفع المدعومة؟</b>\nBybit ID وUSDT BEP20 وUSDT TRC20 وAptos.\n\n<b>هل يمكنني الحصول على حساب VIP؟</b>\nنعم، تواصل مع الدعم لمعرفة الشروط والمزايا.",
        "support_title": "📞 <b>التواصل مع الدعم</b>", "telegram_support": "👤 دعم تيليجرام", "official_channel": "📢 القناة الرسمية",
        "support_note": "يمكنك أيضًا إرسال رسالتك هنا وسيستلمها المشرف.",
        "payment_amount_prompt": "💳 {label}\n\n📝 أدخل المبلغ بعملة USDT\nمثال: 5\n\n✍️ أدخل المبلغ الذي تريد حجزه لشبكة {chain}.\n\n⏱ يتم حجز الجلسة لمدة 10 دقائق.\n❌ اضغط إلغاء للتوقف.\n⚠️ إذا كان المبلغ محجوزًا اختر مبلغًا آخر.",
        "invalid_amount": "❌ أدخل مبلغًا صحيحًا، مثال: 5", "txid_received": "✅ تم استلام رابط Hash / TXID، ويجري التحقق من الدفعة.",
        "payment_cancelled": "❌ تم إلغاء جلسة الدفع.", "copy_address": "نسخ العنوان", "transaction_history": "سجل المعاملات",
        "banned": "⛔ تم حظر حسابك.", "address_sent": "تم إرسال العنوان كرسالة قابلة للنسخ.", "no_transactions": "لا توجد معاملات حتى الآن.",
        "invoice": "💰 يرجى إيداع <b>{amount:.2f} USDT</b> بالضبط عبر ({chain}).\n\n📋 <b>عنوان الدفع</b>\n<code>{address}</code>\n\n☝️ اضغط مطولًا على العنوان لنسخه.\n\n⬇️ بعد الدفع، أرسل رابط Hash / TXID هنا.",
        "bybit_payment": "💳 Bybit ID\n\nأرسل الدفعة إلى Bybit ID:\n<code>{bybit_id}</code>\n\nبعد الدفع، أرسل TXID أو تفاصيل العملية إلى الدعم.",
    },
    "ru": {
        "start": "🤖 Здравствуйте, <b>{name}</b>! Добро пожаловать в ✨ <b>Prime Bot</b> ✨\nБот-магазин подарочных карт!\n\n🔹 Просматривайте подарочные карты\n\n🔹 Пополняйте баланс аккаунта\n\n🔹 Легко покупайте подарочные карты\n\nВыберите нужный пункт в меню ниже:",
        "voucher_title": "Цифровые товары\n\n📂 Выберите категорию:\n✨ 📊 Выберите вариант:",
        "game_title": "Выберите игру для пополнения:\n\nВыберите активную категорию:",
        "choose_lang": "🌐 Выберите язык", "lang_saved": "✅ Язык сохранён.", "no_orders": "📦 У вас пока нет заказов.",
        "generic": "Пожалуйста, выберите пункт меню.", "support_sent": "✅ Ваше сообщение отправлено в поддержку.",
        "no_balance": "❌ Недостаточно средств. Пополните кошелёк.", "processing": "✅ Заказ успешно создан и обрабатывается автоматически.",
        "main_menu": "Главное меню", "back": "Назад", "cancel": "Отмена", "available": "Доступно",
        "select_category": "📂 Выберите категорию:\n\n✨ 📊 Выберите вариант:", "products_intro": "✨ Доступные товары:",
        "no_products": "Нет доступных товаров", "product_unavailable": "Товар недоступен",
        "enter_quantity": "🧾 <b>{title}</b>\n💰 Цена за единицу: <b>{price:.2f} USDT</b>\n\nВведите нужное количество:",
        "invalid_quantity": "❌ Введите целое количество больше нуля.", "enter_game_id": "📝 Введите Game ID для этого заказа:",
        "confirm_order": "🧾 <b>Подтверждение заказа</b>\n\nТовар: <b>{title}</b>\nКоличество: <b>{quantity}</b>\nИтого: <b>{total:.2f} USDT</b>{game_id_line}\n\nПодтвердите заказ.",
        "confirm": "✅ Подтвердить", "order_cancel": "❌ Отмена", "cancelled": "❌ Заказ отменён.", "min_purchase": "❌ Минимальная сумма покупки: {minimum:.2f} USDT",
        "my_orders": "📦 <b>Мои заказы</b>", "last_order": "🕘 <b>Последний заказ</b>", "quantity": "Количество", "total": "Итого", "status": "Статус", "delivered": "Доставлено",
        "wallet_title": "👛 <b>Информация о кошельке</b>", "wallet_hello": "🎮 Здравствуйте, {name}! Ваш текущий баланс:", "telegram_id": "🔤 <b>Telegram ID:</b>",
        "current_balance": "💰 <b>Текущий баланс:</b>", "wallet_next": "📊 ✨ Выберите способ пополнения:",
        "claim_bonus": "🎁 Получить бонус", "enter_bonus": "🎁 Введите бонус-код:", "bonus_invalid": "❌ Неверный или недоступный бонус-код.",
        "bonus_used": "❌ Вы уже использовали этот бонус-код.", "bonus_reserved": "✅ Купон успешно активирован!\n\nВнесите <b>{minimum:.2f} USDT</b> одним платежом, чтобы получить бонус <b>{bonus:.2f} USDT</b>.",
        "bonus_activated": "🎁 Бонус успешно начислен!\n+{bonus:.2f} USDT добавлено на баланс.",
        "terms_title": "📜 <b>Условия и правила</b>\n\nВыберите раздел:", "tos_btn": "📋 Условия использования", "privacy_btn": "🔒 Конфиденциальность", "rules_btn": "⚠️ Правила покупки", "faq_btn": "❓ FAQ",
        "tos": "📋 <b>Условия использования</b>\n\n• Для новых пользователей нет минимальной суммы пополнения или покупки.\n• Некоторые функции реселлера могут потребовать проверки или повышения статуса.\n• Заказы являются окончательными после успешной автоматической доставки.\n• Цены могут меняться в зависимости от рынка.\n• Аккаунты за мошенничество или злоупотребление могут быть заблокированы.",
        "privacy": "🔒 <b>Политика конфиденциальности</b>\n\n• Мы не передаём имена и данные клиентов третьим лицам.\n• Заказы и платежи конфиденциальны.\n• Данные используются только для обработки заказов и поддержки.\n• Мы не продаём данные клиентов.",
        "rules": "⚠️ <b>Правила покупки</b>\n\n• Цены могут меняться без уведомления.\n• Цифровые коды можно хранить до одного года, если не указано иное.\n• Проверьте товар, количество и сумму перед подтверждением.\n• Поддерживаемые товары доставляются автоматически 24/7.\n• При технической проблеме сразу обратитесь в поддержку.",
        "faq": "❓ <b>FAQ</b>\n\n<b>Оплата безопасна?</b>\nДа, платежи проходят через защищённую автоматическую систему.\n\n<b>Сколько длится доставка?</b>\nВсе поддерживаемые товары доставляются автоматически 24/7 сразу после успешной оплаты.\n\n<b>Какие способы оплаты?</b>\nBybit ID, USDT BEP20, USDT TRC20 и Aptos.\n\n<b>Можно получить VIP?</b>\nДа, обратитесь в поддержку.",
        "support_title": "📞 <b>Поддержка</b>", "telegram_support": "👤 Поддержка в Telegram", "official_channel": "📢 Официальный канал", "support_note": "Также можно отправить сообщение здесь — администратор его получит.",
        "payment_amount_prompt": "💳 {label}\n\n📝 Введите сумму USDT\nПример: 5\n\n✍️ Введите сумму для сети {chain}.\n\n⏱ Сессия резервируется на 10 минут.\n❌ Нажмите Отмена, чтобы остановить.\n⚠️ Если сумма занята, выберите другую.",
        "invalid_amount": "❌ Введите корректную сумму, например: 5", "txid_received": "✅ Hash / TXID получен. Платёж проверяется.", "payment_cancelled": "❌ Платёжная сессия отменена.", "copy_address": "Копировать адрес", "transaction_history": "История транзакций",
        "banned": "⛔ Ваш аккаунт заблокирован.", "address_sent": "Адрес отправлен отдельным сообщением для копирования.", "no_transactions": "Транзакций пока нет.",
        "invoice": "💰 Внесите ровно <b>{amount:.2f} USDT</b> через ({chain}).\n\n📋 <b>Адрес оплаты</b>\n<code>{address}</code>\n\n☝️ Нажмите и удерживайте адрес, чтобы скопировать.\n\n⬇️ После оплаты отправьте сюда ссылку Hash / TXID.",
        "bybit_payment": "💳 Bybit ID\n\nОтправьте оплату на Bybit ID:\n<code>{bybit_id}</code>\n\nПосле оплаты отправьте TXID или данные платежа в поддержку.",
    },
    "my": {},
    "az": {},
}

# Myanmar and Azerbaijani keep the existing supported-language behavior, but all new UI keys
# fall back safely to English instead of leaving broken/missing text.
TEXTS["my"] = {**TEXTS["en"], **{
    "start": "🤖 မင်္ဂလာပါ <b>{name}</b>၊ ✨ <b>Prime Bot</b> ✨ မှ ကြိုဆိုပါတယ်။\nGift Card အရောင်း Bot ဖြစ်ပါတယ်။\n\n🔹 Gift Card များကို ကြည့်ရှုပါ\n\n🔹 သင့်အကောင့်လက်ကျန်ကို ဖြည့်ပါ\n\n🔹 Gift Card များကို လွယ်ကူစွာ ဝယ်ယူပါ\n\nအောက်ပါ menu မှ ရွေးချယ်ပါ:",
    "choose_lang": "🌐 Language ရွေးပါ", "lang_saved": "✅ Language saved.",
}}
TEXTS["az"] = {**TEXTS["en"], **{
    "start": "🤖 Salam <b>{name}</b>, ✨ <b>Prime Bot</b> ✨-a xoş gəlmisiniz!\nHədiyyə kartları mağazası botu!\n\n🔹 Hədiyyə kartlarına baxın\n\n🔹 Hesabınıza balans əlavə edin\n\n🔹 Hədiyyə kartlarını asanlıqla alın\n\nAşağıdakı menyudan seçim edin:",
    "choose_lang": "🌐 Dil seçin", "lang_saved": "✅ Dil yadda saxlanıldı.",
    "main_menu": "Əsas menyu", "back": "Geri", "cancel": "Ləğv et", "available": "Mövcuddur",
}}

CATEGORY_TRANSLATIONS = {
    "ar": {
        "Voucher Products": "منتجات البطاقات", "PUBG MOBILE VOUCHER": "قسائم PUBG MOBILE",
        "RAZER GOLD GLOBAL": "RAZER GOLD GLOBAL", "STEAM USA": "STEAM USA", "PlayStation USA": "PlayStation USA",
        "iTunes USA": "iTunes USA", "GARENA FREE FIRE VOUCHERS": "قسائم GARENA FREE FIRE",
        "Yalla Ludo": "Yalla Ludo", "VALORANT": "VALORANT", "ROBLOX": "ROBLOX",
        "🏎️ PRE ORDER CARS": "🏎️ سيارات الطلب المسبق", "⚔️ METRO SWORD": "⚔️ سيف المترو",
    },
    "ru": {
        "Voucher Products": "Цифровые товары", "PUBG MOBILE VOUCHER": "PUBG MOBILE ВАУЧЕРЫ",
        "GARENA FREE FIRE VOUCHERS": "ВАУЧЕРЫ GARENA FREE FIRE",
        "🏎️ PRE ORDER CARS": "🏎️ МАШИНЫ ПОД ЗАКАЗ", "⚔️ METRO SWORD": "⚔️ METRO SWORD",
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

async def tf(user_id: int | None, key: str, **kwargs) -> str:
    return (await tr(user_id, key)).format(**kwargs)

def tr_lang(lang: str, key: str, **kwargs) -> str:
    text = TEXTS.get(lang, TEXTS["en"]).get(key, TEXTS["en"].get(key, key))
    return text.format(**kwargs)

def localize_title(title: str, lang: str) -> str:
    return CATEGORY_TRANSLATIONS.get(lang, {}).get(str(title), str(title))

def _row_get(row, key: str, default=None):
    try:
        return row[key]
    except Exception:
        try:
            return dict(row).get(key, default)
        except Exception:
            return default

def parse_order_quantity(title: str) -> tuple[str, int]:
    match = re.search(r"\s+x(\d+)$", str(title))
    if not match:
        return str(title), 1
    return str(title)[:match.start()], int(match.group(1))

async def get_user_rate(user_id: int) -> float | None:
    try:
        rows = await db.fetch("SELECT custom_rate FROM users WHERE id=$1", user_id)
        if rows and _row_get(rows[0], "custom_rate") is not None:
            return float(_row_get(rows[0], "custom_rate"))
    except Exception:
        pass
    return None

def product_price(product, custom_rate: float | None = None) -> float:
    rate = custom_rate if custom_rate is not None else float(product["rate"])
    return round(float(product["base_price"]) * rate / 100, 2)

async def get_special_products(category: str):
    spec = SPECIAL_PRODUCT_CATEGORIES.get(category)
    if not spec:
        return []
    rows = await db.fetch("SELECT * FROM products WHERE enabled=true ORDER BY id")
    keywords = tuple(k.lower() for k in spec["keywords"])
    return [r for r in rows if any(k in str(_row_get(r, "title", "")).lower() for k in keywords)]

def is_special_product(product) -> bool:
    title = str(_row_get(product, "title", "")).lower()
    return any(any(k.lower() in title for k in spec["keywords"]) for spec in SPECIAL_PRODUCT_CATEGORIES.values())

async def ensure_feature_schema():
    # Safe additive migrations only; no existing data is deleted or rewritten.
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_rate DOUBLE PRECISION",
        """CREATE TABLE IF NOT EXISTS deposit_bonuses(
            code TEXT PRIMARY KEY,
            min_deposit DOUBLE PRECISION NOT NULL,
            bonus_amount DOUBLE PRECISION NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            max_uses INTEGER,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS user_bonus_claims(
            user_id BIGINT NOT NULL,
            code TEXT NOT NULL REFERENCES deposit_bonuses(code) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'PENDING',
            claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            activated_at TIMESTAMPTZ,
            PRIMARY KEY(user_id, code)
        )""",
    ]
    for statement in statements:
        try:
            await db.execute(statement)
        except Exception as exc:
            logging.warning("feature migration skipped: %s", exc)

async def activate_pending_bonuses(user_id: int, deposit_amount: float) -> list[float]:
    activated = []
    try:
        rows = await db.fetch(
            """SELECT c.code, b.bonus_amount
               FROM user_bonus_claims c
               JOIN deposit_bonuses b ON b.code=c.code
               WHERE c.user_id=$1 AND c.status='PENDING' AND b.enabled=true
                 AND b.min_deposit <= $2
                 AND (b.expires_at IS NULL OR b.expires_at > NOW())
               ORDER BY c.claimed_at""",
            user_id, deposit_amount,
        )
        for row in rows:
            code = str(_row_get(row, "code"))
            bonus = float(_row_get(row, "bonus_amount", 0) or 0)
            if bonus <= 0:
                continue
            await db.add_balance(user_id, bonus, f"deposit bonus {code}")
            await db.execute(
                "UPDATE user_bonus_claims SET status='ACTIVATED', activated_at=NOW() WHERE user_id=$1 AND code=$2 AND status='PENDING'",
                user_id, code,
            )
            activated.append(bonus)
    except Exception as exc:
        logging.warning("bonus activation failed: %s", exc)
    return activated

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

async def ensure_special_products():
    """Seed special products only when missing; preserve admin changes afterward."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        (FERRARI_ONE_ID, "pre_order_cars", "Ferrari Card", 126.0, 100.0, True, True, now),
        (FERRARI_THREE_ID, "pre_order_cars", "Ferrari Cards (3 Cards)", 430.0, 100.0, True, True, now),
        (METRO_SWORD_ID, "metro_sword", "METRO SWORD", 80.0, 100.0, True, True, now),
    ]
    for row in rows:
        try:
            await db.execute(
                """INSERT OR IGNORE INTO products
                (id, category, title, base_price, rate, enabled, ask_game_id, created_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                *row,
            )
        except Exception as exc:
            logging.warning("Could not seed special product %s: %s", row[0], exc)

async def set_product_availability(product_key: str, enabled: bool) -> int:
    ids = SPECIAL_PRODUCT_IDS.get(product_key.strip(), (product_key.strip(),))
    affected = 0
    for product_id in ids:
        exists = await db.fetchval("SELECT COUNT(*) FROM products WHERE id=$1", product_id)
        if exists:
            await db.execute("UPDATE products SET enabled=$2 WHERE id=$1", product_id, enabled)
            affected += 1
    return affected

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
        return main_menu_lang("en")

    def voucher_categories(lang: str = "en"):
        rows = []
        cats = list(PARENT_MENUS.get("voucher", []))
        inserted_special = False
        for cat in cats:
            title = CATEGORIES.get(cat, cat)
            rows.append([ik_button(localize_title(title, lang), f"cat:{cat}", category_icon_id(cat, title), "primary")])
            if not inserted_special and ("pubg" in str(cat).lower() or "pubg" in str(title).lower()):
                for special_key, spec in SPECIAL_PRODUCT_CATEGORIES.items():
                    rows.append([ik_button(localize_title(spec["title"], lang), f"cat:{special_key}", style="primary")])
                inserted_special = True
        if not inserted_special:
            for special_key, spec in SPECIAL_PRODUCT_CATEGORIES.items():
                rows.append([ik_button(localize_title(spec["title"], lang), f"cat:{special_key}", style="primary")])
        rows.append([ik_button(tr_lang(lang, "back"), "home", style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def game_categories(lang: str = "en"):
        rows = []
        for cat in PARENT_MENUS.get("gameid", []):
            title = CATEGORIES.get(cat, cat)
            rows.append([ik_button(localize_title(title, lang), f"cat:{cat}", category_icon_id(cat, title), "primary")])
        rows.append([ik_button(tr_lang(lang, "back"), "home", style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def subcats(parent: str, lang: str = "en"):
        rows = []
        for cat in SUBCATEGORIES.get(parent, []):
            title = CATEGORIES.get(cat, cat)
            rows.append([ik_button(localize_title(title, lang), f"cat:{cat}", category_icon_id(cat, title), "primary")])
        rows.append([ik_button(tr_lang(lang, "back"), "voucher", style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def products_keyboard(products, parent_back: str, custom_rate: float | None = None, lang: str = "en"):
        rows = []
        for r in products:
            price = product_price(r, custom_rate)
            title = localize_title(str(r["title"]), lang)
            rows.append([ik_button(f"{title} | {price:.2f} USDT | ✅ {tr_lang(lang, 'available')}", f"buy:{r['id']}", style="primary")])
        rows.append([ik_button(tr_lang(lang, "back"), parent_back, style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def wallet_keyboard(lang: str = "en"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button("USDT BEP20", "pay:BEP20", CUSTOM_EMOJI["wallet"], "primary"), ik_button("USDT TRC20", "pay:TRC20", CUSTOM_EMOJI["wallet"], "primary")],
            [ik_button("Aptos", "pay:APTOS", CUSTOM_EMOJI["wallet"], "primary"), ik_button("Bybit ID", "pay:BYBIT", CUSTOM_EMOJI["game_id"], "primary")],
            [ik_button(tr_lang(lang, "claim_bonus"), "claimbonus", style="success")],
            [ik_button(tr_lang(lang, "transaction_history"), "txhistory", CUSTOM_EMOJI["orders"], "success")],
            [ik_button(tr_lang(lang, "back"), "home", style="danger")],
        ])

    def langs_keyboard(lang: str = "en"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button("العربية", "lang:ar", CUSTOM_EMOJI["settings"])],
            [ik_button("English", "lang:en", CUSTOM_EMOJI["settings"])],
            [ik_button("Русский", "lang:ru", CUSTOM_EMOJI["settings"])],
            [ik_button("မြန်မာ", "lang:my", CUSTOM_EMOJI["settings"])],
            [ik_button("Azərbaycan", "lang:az", CUSTOM_EMOJI["settings"])],
            [ik_button(tr_lang(lang, "cancel"), "home", style="danger")],
        ])

    def invoice_keyboard(method: str, lang: str = "en"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button(tr_lang(lang, "copy_address"), f"copy:{method}", style="success")],
            [ik_button(tr_lang(lang, "cancel"), "cancelpay", style="danger")],
        ])

    def confirm_order(lang: str = "en"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button(tr_lang(lang, "confirm"), "orderconfirm", style="success")],
            [ik_button(tr_lang(lang, "order_cancel"), "ordercancel", style="danger")],
        ])

    def terms_keyboard(lang: str = "en"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [ik_button(tr_lang(lang, "tos_btn"), "policy:tos", style="primary")],
            [ik_button(tr_lang(lang, "privacy_btn"), "policy:privacy", style="primary")],
            [ik_button(tr_lang(lang, "rules_btn"), "policy:rules", style="primary")],
            [ik_button(tr_lang(lang, "faq_btn"), "policy:faq", style="primary")],
            [ik_button(tr_lang(lang, "back"), "home", style="danger")],
        ])

    kb.main_menu = main_menu
    kb.voucher_categories = voucher_categories
    kb.game_categories = game_categories
    kb.subcats = subcats
    kb.products_keyboard = products_keyboard
    kb.wallet_keyboard = wallet_keyboard
    kb.langs_keyboard = langs_keyboard
    kb.invoice_keyboard = invoice_keyboard
    kb.confirm_order = confirm_order
    kb.terms_keyboard = terms_keyboard

_patch_keyboards()


def admin_only(message: Message) -> bool:
    return message.from_user and message.from_user.id == config.admin_id

async def notify_admin(text: str, reply_markup=None):
    if BOT:
        try:
            await BOT.send_message(config.admin_id, text, reply_markup=reply_markup)
        except Exception as e:
            logging.warning("admin notify failed: %s", e)


def _remember_ui_message(message: Message | None) -> None:
    if message and message.from_user and message.chat:
        last_ui_message[message.chat.id] = (message.chat.id, message.message_id)


async def _send_ui(message: Message, text: str, reply_markup=None) -> Message:
    """Send a UI message and remember it as the one to edit next."""
    sent = await message.answer(text, reply_markup=reply_markup)
    last_ui_message[message.from_user.id] = (sent.chat.id, sent.message_id)
    return sent


async def _edit_ui_from_message(message: Message, text: str, reply_markup=None) -> Message | None:
    """Edit the user's latest bot UI message; fall back to sending once."""
    if BOT:
        target = last_ui_message.get(message.from_user.id)
        if target:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                edited = await BOT.edit_message_text(
                    chat_id=target[0],
                    message_id=target[1],
                    text=text,
                    reply_markup=reply_markup,
                )
                return edited if isinstance(edited, Message) else None
            except Exception:
                try:
                    edited = await BOT.edit_message_caption(
                        chat_id=target[0],
                        message_id=target[1],
                        caption=text,
                        reply_markup=reply_markup,
                    )
                    return edited if isinstance(edited, Message) else None
                except Exception:
                    pass
    return await _send_ui(message, text, reply_markup)


async def _edit_ui_from_callback(call: CallbackQuery, text: str, reply_markup=None) -> None:
    """Update the same callback message whenever Telegram allows it."""
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
        last_ui_message[call.from_user.id] = (call.message.chat.id, call.message.message_id)
        return
    except Exception:
        try:
            await call.message.edit_caption(caption=text, reply_markup=reply_markup)
            last_ui_message[call.from_user.id] = (call.message.chat.id, call.message.message_id)
            return
        except Exception:
            sent = await call.message.answer(text, reply_markup=reply_markup)
            last_ui_message[call.from_user.id] = (sent.chat.id, sent.message_id)

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
        await message.answer(await tr(message.from_user.id, "banned"))
        return False
    return True

@router.message(CommandStart())
async def start(message: Message):
    if not await user_guard(message): return
    lang = await get_lang(message.from_user.id)
    await _send_ui(
        message,
        tr_lang(
            lang,
            "start",
            name=html.escape(message.from_user.first_name or message.from_user.username or "User"),
        ),
        reply_markup=main_menu_lang(lang)
    )

@router.message(F.text.in_(all_labels("voucher")))
async def voucher(message: Message):
    if not await user_guard(message): return
    lang = await get_lang(message.from_user.id)
    await _send_ui(message, await tr(message.from_user.id, "voucher_title"), reply_markup=kb.voucher_categories(lang))

@router.message(F.text.in_(all_labels("gameid")))
async def game_id(message: Message):
    if not await user_guard(message): return
    lang = await get_lang(message.from_user.id)
    await _send_ui(message, await tr(message.from_user.id, "game_title"), reply_markup=kb.game_categories(lang))

@router.message(F.text.in_(all_labels("wallet")))
async def wallet(message: Message):
    if not await user_guard(message): return
    lang = await get_lang(message.from_user.id)
    u = await db.get_user(message.from_user.id)
    bal = float(u["balance"] or 0) if u else 0
    text = (
        f"{tr_lang(lang, 'wallet_title')}\n"
        f"{tr_lang(lang, 'wallet_hello', name=message.from_user.first_name or 'User')}\n\n"
        f"{tr_lang(lang, 'telegram_id')}\n<code>{message.from_user.id}</code>\n\n"
        f"{tr_lang(lang, 'current_balance')}\n<code>{bal:.4f} $</code>\n"
        f"{tr_lang(lang, 'wallet_next')}"
    )
    await _send_ui(message, text, reply_markup=kb.wallet_keyboard(lang))

@router.message(F.text.in_(all_labels("orders")))
async def my_orders(message: Message):
    if not await user_guard(message): return
    lang = await get_lang(message.from_user.id)
    rows = await db.recent_orders(message.from_user.id)
    if not rows:
        await _send_ui(message, await tr(message.from_user.id, "no_orders"))
        return
    latest = rows[0]
    latest_title, latest_qty = parse_order_quantity(str(latest["title"]))
    latest_status = str(latest["status"])
    latest_block = (
        f"{tr_lang(lang, 'last_order')}\n\n"
        f"{localize_title(latest_title, lang)}\n"
        f"{tr_lang(lang, 'quantity')}: {latest_qty}\n"
        f"{tr_lang(lang, 'total')}: {float(latest['price']):.2f} USDT\n"
        f"{tr_lang(lang, 'status')}: ✅ {latest_status.title()}"
    )
    history = []
    for r in rows:
        title, qty = parse_order_quantity(str(r["title"]))
        history.append(
            f"#{r['id']} | {localize_title(title, lang)}\n"
            f"{tr_lang(lang, 'quantity')}: {qty} | {tr_lang(lang, 'total')}: {float(r['price']):.2f} USDT\n"
            f"{tr_lang(lang, 'status')}: ✅ {str(r['status']).title()}\n"
            f"📅 {r['created_at'].strftime('%d.%m.%Y %H:%M')}"
        )
    await _send_ui(message, f"{tr_lang(lang, 'my_orders')}\n\n{latest_block}\n\n──────────\n\n" + "\n\n".join(history))

@router.message(F.text.in_(all_labels("language")))
async def language(message: Message):
    if not await user_guard(message): return
    await _send_ui(message, await tr(message.from_user.id, "choose_lang"), reply_markup=kb.langs_keyboard(await get_lang(message.from_user.id)))

@router.message(F.text.in_(all_labels("about")))
async def about(message: Message):
    if not await user_guard(message): return
    lang = await get_lang(message.from_user.id)
    await _send_ui(message, tr_lang(lang, "terms_title"), reply_markup=kb.terms_keyboard(lang))

@router.callback_query(F.data.in_({"policy:tos", "policy:privacy", "policy:rules", "policy:faq"}))
async def policy_page(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    key = call.data.split(":", 1)[1]
    if key not in {"tos", "privacy", "rules", "faq"}:
        await call.answer(); return
    await call.message.edit_text(tr_lang(lang, key), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [ik_button(tr_lang(lang, "back"), "policy:menu", style="danger")]
    ]))
    await call.answer()

@router.callback_query(F.data == "policy:menu")
async def policy_menu(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    await call.message.edit_text(tr_lang(lang, "terms_title"), reply_markup=kb.terms_keyboard(lang))
    await call.answer()

@router.message(F.text.in_(all_labels("support")))
async def support(message: Message, state: FSMContext):
    if not await user_guard(message): return
    lang = await get_lang(message.from_user.id)
    await _send_ui(
        message,
        f"{tr_lang(lang, 'support_title')}\n\n"
        f"{tr_lang(lang, 'telegram_support')}\n{SUPPORT_USERNAME}\n\n"
        f"{tr_lang(lang, 'official_channel')}\n{config.channel_url}\n\n"
        f"{tr_lang(lang, 'support_note')}"
    )
    await state.set_state(UserFlow.waiting_support)

@router.message(UserFlow.waiting_support)
async def support_msg(message: Message, state: FSMContext):
    await notify_admin(
        f"📩 Support message\nFrom: <code>{message.from_user.id}</code> @{message.from_user.username or '-'}\n\n{message.text or '[non-text message]'}"
    )
    await _edit_ui_from_message(message, await tr(message.from_user.id, "support_sent"))
    await state.clear()

@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    # Reply keyboards cannot be attached by editing an inline message, so refresh
    # the same UI text and keep the existing persistent keyboard unchanged.
    await _edit_ui_from_callback(call, tr_lang(lang, "main_menu"))
    await call.answer()

@router.callback_query(F.data == "voucher")
async def cb_voucher(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    await call.message.edit_text(await tr(call.from_user.id, "voucher_title"), reply_markup=kb.voucher_categories(lang))
    await call.answer()

@router.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery, state: FSMContext):
    lang = await get_lang(call.from_user.id)
    cat = call.data.split(":",1)[1]
    if cat in SUBCATEGORIES:
        msg = f"{localize_title(CATEGORIES[cat], lang)}\n{tr_lang(lang, 'select_category')}"
        await call.message.edit_text(msg, reply_markup=kb.subcats(cat, lang))
        await call.answer(); return
    if cat == "pre_order_cars":
        available = await db.fetch(
            "SELECT id FROM products WHERE id IN ($1,$2) AND enabled=true ORDER BY id",
            FERRARI_ONE_ID, FERRARI_THREE_ID,
        )
        available_ids = {str(_row_get(row, "id", "")) for row in available}
        if not available_ids:
            await call.answer(tr_lang(lang, "no_products"), show_alert=True); return
        buttons = []
        if FERRARI_ONE_ID in available_ids:
            buttons.append([ik_button(special_text(lang, "ferrari_one"), f"specialbuy:{FERRARI_ONE_ID}", style="primary")])
        if FERRARI_THREE_ID in available_ids:
            buttons.append([ik_button(special_text(lang, "ferrari_three"), f"specialbuy:{FERRARI_THREE_ID}", style="primary")])
        buttons.append([ik_button(tr_lang(lang, "back"), "voucher", style="danger")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        image = preorder_image_path()
        if image:
            try:
                await call.message.delete()
            except Exception:
                pass
            sent = await call.message.answer_photo(FSInputFile(image), caption=special_text(lang, "ferrari_caption"), reply_markup=markup)
            last_ui_message[call.from_user.id] = (sent.chat.id, sent.message_id)
        else:
            logging.warning("PRE ORDER CARS image was not found: %s", PREORDER_IMAGE_NAME)
            await _edit_ui_from_callback(call, special_text(lang, "ferrari_caption"), reply_markup=markup)
        await call.answer(); return

    if cat == "metro_sword":
        product = await db.get_product(METRO_SWORD_ID)
        if not product:
            await call.answer(tr_lang(lang, "no_products"), show_alert=True); return
        await state.clear()
        await state.update_data(product_id=METRO_SWORD_ID, unit_price=80.0, quantity=1, quantity_label="1")
        await state.update_data(ui_chat_id=call.message.chat.id, ui_message_id=call.message.message_id)
        await _edit_ui_from_callback(call, special_text(lang, "metro_prompt"))
        await state.set_state(UserFlow.waiting_game_id)
        await call.answer(); return

    products = await db.get_products(cat)
    if "pubg" in str(cat).lower():
        products = [p for p in products if not is_special_product(p)]
    title = CATEGORIES.get(cat, cat)
    if not products:
        await call.answer(tr_lang(lang, "no_products"), show_alert=True); return
    parent_back = "gameid" if cat in PARENT_MENUS.get("gameid", []) else "voucher"
    user_rate = await get_user_rate(call.from_user.id)
    await call.message.edit_text(
        f"{localize_title(title, lang)}\n\n{tr_lang(lang, 'products_intro')}",
        reply_markup=kb.products_keyboard(products, parent_back, user_rate, lang)
    )
    await call.answer()

@router.callback_query(F.data == "gameid")
async def cb_gameid(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    await call.message.edit_text(await tr(call.from_user.id, "game_title"), reply_markup=kb.game_categories(lang))
    await call.answer()

@router.callback_query(F.data.startswith("specialbuy:"))
async def cb_special_buy(call: CallbackQuery, state: FSMContext):
    lang = await get_lang(call.from_user.id)
    product_id = call.data.split(":", 1)[1]
    if product_id not in {FERRARI_ONE_ID, FERRARI_THREE_ID}:
        await call.answer(tr_lang(lang, "product_unavailable"), show_alert=True); return
    product = await db.get_product(product_id)
    if not product:
        await call.answer(tr_lang(lang, "product_unavailable"), show_alert=True); return
    total = 126.0 if product_id == FERRARI_ONE_ID else 430.0
    quantity_label = "1 Card" if product_id == FERRARI_ONE_ID else "3 Cards"
    await state.clear()
    await state.update_data(product_id=product_id, unit_price=total, quantity=1, quantity_label=quantity_label, special_total=total)
    await state.update_data(ui_chat_id=call.message.chat.id, ui_message_id=call.message.message_id)
    await _edit_ui_from_callback(call, special_text(lang, "ferrari_prompt"))
    await state.set_state(UserFlow.waiting_game_id)
    await call.answer()

@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, state: FSMContext):
    lang = await get_lang(call.from_user.id)
    product_id = call.data.split(":",1)[1]
    product = await db.get_product(product_id)
    if not product:
        await call.answer(tr_lang(lang, "product_unavailable"), show_alert=True); return
    custom_rate = await get_user_rate(call.from_user.id)
    price = product_price(product, custom_rate)
    await state.clear()
    await state.update_data(product_id=product_id, unit_price=price)
    await state.update_data(ui_chat_id=call.message.chat.id, ui_message_id=call.message.message_id)
    await _edit_ui_from_callback(call, tr_lang(lang, "enter_quantity", title=localize_title(str(product["title"]), lang), price=price))
    await state.set_state(UserFlow.waiting_quantity)
    await call.answer()

@router.message(UserFlow.waiting_quantity)
async def got_quantity(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    try:
        quantity = int(message.text.strip())
        if quantity <= 0 or quantity > 100000:
            raise ValueError
    except Exception:
        await _edit_ui_from_message(message, tr_lang(lang, "invalid_quantity")); return
    data = await state.get_data()
    product = await db.get_product(data.get("product_id"))
    if not product:
        await _edit_ui_from_message(message, tr_lang(lang, "product_unavailable")); await state.clear(); return
    await state.update_data(quantity=quantity)
    if bool(product["ask_game_id"]):
        await _edit_ui_from_message(message, tr_lang(lang, "enter_game_id"))
        await state.set_state(UserFlow.waiting_game_id)
        return
    await show_order_confirmation(message, state, product, lang)

async def show_order_confirmation(message: Message, state: FSMContext, product, lang: str):
    data = await state.get_data()
    quantity = int(data.get("quantity", 1))
    unit_price = float(data.get("unit_price", product_price(product)))
    total = round(float(data.get("special_total", unit_price * quantity)), 2)
    display_quantity = data.get("quantity_label", quantity)
    game_id = str(data.get("game_id", "")).strip()
    game_id_line = f"\nGame ID: <code>{game_id}</code>" if game_id else ""
    await state.update_data(total=total)
    await _edit_ui_from_message(
        message,
        tr_lang(lang, "confirm_order", title=localize_title(str(product["title"]), lang), quantity=display_quantity, total=total, game_id_line=game_id_line),
        reply_markup=kb.confirm_order(lang),
    )

@router.message(UserFlow.waiting_game_id)
async def got_game_id(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    data = await state.get_data()
    product = await db.get_product(data.get("product_id"))
    if not product:
        await message.answer(tr_lang(lang, "product_unavailable")); await state.clear(); return
    await state.update_data(game_id=message.text.strip())
    await show_order_confirmation(message, state, product, lang)

@router.callback_query(F.data == "ordercancel")
async def order_cancel(call: CallbackQuery, state: FSMContext):
    lang = await get_lang(call.from_user.id)
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await _edit_ui_from_callback(call, tr_lang(lang, "cancelled"))
    await call.answer()

@router.callback_query(F.data == "orderconfirm")
async def order_confirm(call: CallbackQuery, state: FSMContext):
    lang = await get_lang(call.from_user.id)
    data = await state.get_data()
    product = await db.get_product(data.get("product_id"))
    if not product:
        await call.answer(tr_lang(lang, "product_unavailable"), show_alert=True); await state.clear(); return
    quantity = int(data.get("quantity", 1))
    total = round(float(data.get("total", 0)), 2)
    game_id = str(data.get("game_id", "")).strip() or None
    order_title = f"{product['title']} x{quantity}"
    order = await db.create_order(call.from_user.id, str(product["id"]), order_title, total, game_id)
    if not order:
        await _edit_ui_from_callback(call, await tr(call.from_user.id, "no_balance"))
    elif isinstance(order, dict) and order.get("error") == "MIN":
        await _edit_ui_from_callback(call, tr_lang(lang, "min_purchase", minimum=float(order["minimum"])))
    else:
        await call.message.edit_reply_markup(reply_markup=None)
        await _edit_ui_from_callback(call, await tr(call.from_user.id, "processing"))
        await notify_admin(
            f"🆕 New Order #{order['id']}\nUser: {call.from_user.id}\n"
            f"Product: {product['title']} x{quantity}\nTotal: ${total:.2f}\nStatus: processing"
            + (f"\nGame ID: <code>{game_id}</code>" if game_id else "")
        )
    await state.clear()
    await call.answer()

@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(call: CallbackQuery, state: FSMContext):
    method = call.data.split(":",1)[1]
    pending_pay_method[call.from_user.id] = method
    lang = await get_lang(call.from_user.id)
    if method == "BYBIT":
        await _edit_ui_from_callback(call, tr_lang(lang, "bybit_payment", bybit_id=config.bybit_id))
        await call.answer(); return
    label = {"BEP20": "USDT BEP20", "TRC20": "USDT TRC20", "APTOS": "Aptos"}.get(method, method)
    chain = {"BEP20": "BEP20 / BSC", "TRC20": "TRC20 / TRON", "APTOS": "Aptos"}.get(method, method)
    await state.update_data(ui_chat_id=call.message.chat.id, ui_message_id=call.message.message_id)
    await _edit_ui_from_callback(call, tr_lang(lang, "payment_amount_prompt", label=label, chain=chain))
    await state.set_state(UserFlow.waiting_payment_amount)
    await call.answer()

@router.message(UserFlow.waiting_payment_amount)
async def payment_amount(message: Message, state: FSMContext):
    try:
        amount = round(float(message.text.strip().replace(",", ".")), 2)
        if amount <= 0:
            raise ValueError
    except Exception:
        await _edit_ui_from_message(message, await tr(message.from_user.id, "invalid_amount"))
        return

    method = pending_pay_method.get(message.from_user.id, "BEP20")
    address = {"BEP20": BEP20_ADDRESS, "TRC20": TRC20_ADDRESS, "APTOS": APTOS_ADDRESS}.get(method, BEP20_ADDRESS)
    # Keep an expiry in the database only for compatibility with the old table.
    # It is NOT shown to the customer anymore.
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.create_payment(message.from_user.id, amount, method, address, expires)

    invoice_id = None
    try:
        rows = await db.fetch(
            "SELECT id FROM payments WHERE user_id=$1 AND status='PENDING' ORDER BY id DESC LIMIT 1",
            message.from_user.id,
        )
        if rows:
            invoice_id = rows[0]["id"]
    except Exception:
        invoice_id = None

    chain = {"BEP20": "BSC / BEP20", "TRC20": "TRC20 / TRON", "APTOS": "Aptos"}.get(method, method)
    lang = await get_lang(message.from_user.id)
    await state.update_data(payment_amount=amount, payment_method=method, payment_address=address, invoice_id=invoice_id)
    await _edit_ui_from_message(
        message,
        tr_lang(lang, "invoice", amount=amount, chain=chain, address=address),
        reply_markup=kb.invoice_keyboard(method, lang)
    )
    await state.set_state(UserFlow.waiting_txid)

@router.message(UserFlow.waiting_txid)
async def txid_received(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = float(data.get("payment_amount", 0) or 0)
    method = data.get("payment_method") or pending_pay_method.get(message.from_user.id, "BEP20")
    address = data.get("payment_address") or {"BEP20": BEP20_ADDRESS, "TRC20": TRC20_ADDRESS, "APTOS": APTOS_ADDRESS}.get(method, BEP20_ADDRESS)
    invoice_id = data.get("invoice_id")
    hash_link = message.text.strip()

    await db.execute(
        """UPDATE payments SET txid=$2, status='WAITING_ADMIN' WHERE user_id=$1 AND status='PENDING'""",
        message.from_user.id,
        hash_link,
    )

    if not invoice_id:
        try:
            rows = await db.fetch(
                "SELECT id, amount FROM payments WHERE user_id=$1 AND txid=$2 ORDER BY id DESC LIMIT 1",
                message.from_user.id,
                hash_link,
            )
            if rows:
                invoice_id = rows[0]["id"]
                amount = float(rows[0]["amount"])
        except Exception:
            pass

    await _edit_ui_from_message(message, await tr(message.from_user.id, "txid_received"))
    await notify_admin(
        f"💰 Manual Payment Check Requested\n\n"
        f"Invoice ID: #{invoice_id or '-'}\n"
        f"User ID: {message.from_user.id}\n"
        f"Username: @{message.from_user.username or '-'}\n"
        f"Network: {method}\n"
        f"Amount: ${amount:.2f}\n"
        f"Address: {address}\n"
        f"Hash / TXID: <code>{hash_link}</code>\n\n"
        f"Use:\n/addbalance {message.from_user.id} {amount:.2f}"
    )
    await state.clear()

@router.callback_query(F.data.startswith("copy:"))
async def copy_addr(call: CallbackQuery):
    method = call.data.split(":",1)[1]
    address = {"BEP20": BEP20_ADDRESS, "TRC20": TRC20_ADDRESS, "APTOS": APTOS_ADDRESS}.get(method, BEP20_ADDRESS)
    await call.answer(address, show_alert=True)

@router.callback_query(F.data == "cancelpay")
async def cancelpay(call: CallbackQuery, state: FSMContext):
    await db.cancel_pending_payment(call.from_user.id)
    await state.clear()
    await _edit_ui_from_callback(call, await tr(call.from_user.id, "payment_cancelled"))
    await call.answer()

@router.callback_query(F.data == "txhistory")
async def txhistory(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    rows = await db.latest_payments(call.from_user.id)
    if not rows:
        await _edit_ui_from_callback(call, f"📊 📝 <b>{tr_lang(lang, 'transaction_history')}</b>\n\n{tr_lang(lang, 'no_transactions')}")
        await call.answer(); return
    text = f"📊 📝 <b>{tr_lang(lang, 'transaction_history')}</b>\n\n" + "\n\n".join(
        f"{'✅' if r['status']=='CONFIRMED' else '❌' if 'CANCEL' in r['status'] else '⏳'} #{r['id']} | {float(r['amount']):.2f} $ | {r['method']}\n"
        f"📅 {r['created_at'].strftime('%d.%m.%Y %H:%M')} | {r['status']}"
        for r in rows
    )
    await _edit_ui_from_callback(call, text)
    await call.answer()

@router.callback_query(F.data == "claimbonus")
async def claim_bonus(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(ui_chat_id=call.message.chat.id, ui_message_id=call.message.message_id)
    await _edit_ui_from_callback(call, await tr(call.from_user.id, "enter_bonus"))
    await state.set_state(UserFlow.waiting_bonus_code)
    await call.answer()

@router.message(UserFlow.waiting_bonus_code)
async def bonus_code_received(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    lang = await get_lang(message.from_user.id)
    try:
        rows = await db.fetch(
            """SELECT code,min_deposit,bonus_amount,max_uses
               FROM deposit_bonuses
               WHERE code=$1 AND enabled=true AND (expires_at IS NULL OR expires_at > NOW())""",
            code,
        )
        if not rows:
            await _edit_ui_from_message(message, tr_lang(lang, "bonus_invalid")); await state.clear(); return
        used = await db.fetch("SELECT status FROM user_bonus_claims WHERE user_id=$1 AND code=$2", message.from_user.id, code)
        if used:
            await _edit_ui_from_message(message, tr_lang(lang, "bonus_used")); await state.clear(); return
        max_uses = _row_get(rows[0], "max_uses")
        if max_uses is not None:
            count_rows = await db.fetch("SELECT COUNT(*) AS c FROM user_bonus_claims WHERE code=$1", code)
            if count_rows and int(_row_get(count_rows[0], "c", 0)) >= int(max_uses):
                await _edit_ui_from_message(message, tr_lang(lang, "bonus_invalid")); await state.clear(); return
        await db.execute("INSERT INTO user_bonus_claims(user_id,code,status) VALUES($1,$2,'PENDING')", message.from_user.id, code)
        await _edit_ui_from_message(message, tr_lang(lang, "bonus_reserved", minimum=float(rows[0]["min_deposit"]), bonus=float(rows[0]["bonus_amount"])))
    except Exception as exc:
        logging.exception("claim bonus failed: %s", exc)
        await _edit_ui_from_message(message, tr_lang(lang, "bonus_invalid"))
    await state.clear()

@router.callback_query(F.data.startswith("lang:"))
async def set_lang(call: CallbackQuery):
    lang = call.data.split(":",1)[1]
    await db.execute("UPDATE users SET language=$2 WHERE id=$1", call.from_user.id, lang)
    await _edit_ui_from_callback(call, await tr(call.from_user.id, "lang_saved"))
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
        user_id = int(uid)
        deposit_amount = float(amount)
        await db.add_balance(user_id, deposit_amount, "admin add")
        bonuses = await activate_pending_bonuses(user_id, deposit_amount)
        await message.answer("✅ Balance added." + (f" Bonus activated: {sum(bonuses):.2f} USDT." if bonuses else ""))
        await BOT.send_message(user_id, f"✅ Your balance has been updated.\n+{deposit_amount:.2f} USDT")
        if bonuses:
            lang = await get_lang(user_id)
            for bonus in bonuses:
                await BOT.send_message(user_id, tr_lang(lang, "bonus_activated", bonus=bonus))
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
        if not u:
            await message.answer("User not found")
        else:
            data = dict(u)
            rate = await get_user_rate(uid)
            data["custom_rate"] = rate
            await message.answer(str(data))
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

@router.message(Command("setuserrate"))
async def cmd_setuserrate(message: Message):
    if not admin_only(message): return
    try:
        _, uid, rate = message.text.split(maxsplit=2)
        uid_i, rate_f = int(uid), float(rate)
        if rate_f <= 0 or rate_f > 1000:
            raise ValueError
        await db.execute("INSERT INTO users(id) VALUES($1) ON CONFLICT DO NOTHING", uid_i)
        await db.execute("UPDATE users SET custom_rate=$2 WHERE id=$1", uid_i, rate_f)
        await message.answer(f"✅ Custom rate for {uid_i}: {rate_f:g}%")
    except Exception:
        await message.answer("Usage: /setuserrate USER_ID PERCENT")

@router.message(Command("resetuserrate"))
async def cmd_resetuserrate(message: Message):
    if not admin_only(message): return
    try:
        uid = int(message.text.split()[1])
        await db.execute("UPDATE users SET custom_rate=NULL WHERE id=$1", uid)
        await message.answer("✅ Custom user rate reset.")
    except Exception:
        await message.answer("Usage: /resetuserrate USER_ID")

@router.message(Command("checkrate"))
async def cmd_checkrate(message: Message):
    if not admin_only(message): return
    try:
        uid = int(message.text.split()[1])
        rate = await get_user_rate(uid)
        await message.answer(f"User {uid}\nCustom Rate: {rate:g}%" if rate is not None else f"User {uid}\nCustom Rate: default")
    except Exception:
        await message.answer("Usage: /checkrate USER_ID")

@router.message(Command("addbonus"))
async def cmd_addbonus(message: Message):
    if not admin_only(message): return
    try:
        parts = message.text.split()
        if len(parts) not in {4, 5}:
            raise ValueError
        code = parts[1].upper(); minimum = float(parts[2]); bonus = float(parts[3]); max_uses = int(parts[4]) if len(parts) == 5 else None
        await db.execute(
            """INSERT INTO deposit_bonuses(code,min_deposit,bonus_amount,max_uses,enabled)
               VALUES($1,$2,$3,$4,true)
               ON CONFLICT(code) DO UPDATE SET min_deposit=$2,bonus_amount=$3,max_uses=$4,enabled=true""",
            code, minimum, bonus, max_uses,
        )
        await message.answer(f"✅ Bonus saved.\nCode: {code}\nDeposit: {minimum:.2f}\nBonus: {bonus:.2f}")
    except Exception:
        await message.answer("Usage: /addbonus CODE MIN_DEPOSIT BONUS_AMOUNT [MAX_USES]")

@router.message(Command("editbonus"))
async def cmd_editbonus(message: Message):
    await cmd_addbonus(message)

@router.message(Command("delbonus"))
async def cmd_delbonus(message: Message):
    if not admin_only(message): return
    try:
        code = message.text.split()[1].upper()
        await db.execute("DELETE FROM deposit_bonuses WHERE code=$1", code)
        await message.answer("✅ Bonus deleted.")
    except Exception:
        await message.answer("Usage: /delbonus CODE")

@router.message(Command("disablebonus"))
async def cmd_disablebonus(message: Message):
    if not admin_only(message): return
    try:
        code = message.text.split()[1].upper(); await db.execute("UPDATE deposit_bonuses SET enabled=false WHERE code=$1", code); await message.answer("✅ Bonus disabled.")
    except Exception: await message.answer("Usage: /disablebonus CODE")

@router.message(Command("enablebonus"))
async def cmd_enablebonus(message: Message):
    if not admin_only(message): return
    try:
        code = message.text.split()[1].upper(); await db.execute("UPDATE deposit_bonuses SET enabled=true WHERE code=$1", code); await message.answer("✅ Bonus enabled.")
    except Exception: await message.answer("Usage: /enablebonus CODE")

@router.message(Command("bonuses"))
async def cmd_bonuses(message: Message):
    if not admin_only(message): return
    rows = await db.fetch("SELECT code,min_deposit,bonus_amount,enabled,max_uses FROM deposit_bonuses ORDER BY created_at DESC")
    if not rows:
        await message.answer("No deposit bonuses."); return
    await message.answer("🎁 Deposit Bonuses\n\n" + "\n".join(
        f"{r['code']} | deposit {float(r['min_deposit']):.2f} | bonus {float(r['bonus_amount']):.2f} | {'ON' if r['enabled'] else 'OFF'} | max {r['max_uses'] or '∞'}" for r in rows
    )[:3900])

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

@router.message(Command("availability"))
async def cmd_availability(message: Message):
    if not admin_only(message): return
    try:
        _, product_key, raw_status = message.text.split(maxsplit=2)
        status = raw_status.strip().lower()
        if status not in {"available", "on", "1", "true", "unavailable", "off", "0", "false"}:
            raise ValueError
        enabled = status in {"available", "on", "1", "true"}
        affected = await set_product_availability(product_key, enabled)
        if affected == 0:
            await message.answer("❌ Product ID not found."); return
        await message.answer(("✅ Product is now available." if enabled else "✅ Product is now unavailable.") + f"\nAffected: {affected}")
    except Exception:
        await message.answer("Usage: /availability PRODUCT_ID available|unavailable")

@router.message(Command("setavailable"))
async def cmd_setavailable(message: Message):
    if not admin_only(message): return
    try:
        product_key = message.text.split(maxsplit=1)[1].strip()
        affected = await set_product_availability(product_key, True)
        await message.answer(("✅ Product is now available." if affected else "❌ Product ID not found.") + (f"\nAffected: {affected}" if affected else ""))
    except Exception:
        await message.answer("Usage: /setavailable PRODUCT_ID")

@router.message(Command("setunavailable"))
async def cmd_setunavailable(message: Message):
    if not admin_only(message): return
    try:
        product_key = message.text.split(maxsplit=1)[1].strip()
        affected = await set_product_availability(product_key, False)
        await message.answer(("✅ Product is now unavailable." if affected else "❌ Product ID not found.") + (f"\nAffected: {affected}" if affected else ""))
    except Exception:
        await message.answer("Usage: /setunavailable PRODUCT_ID")

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
async def restore(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    await state.set_state(AdminFlow.waiting_restore_file)
    await message.answer(
        "📥 Send the old backup file in JSON format.\n\n"
        "The bot will validate the file and merge its data with the current database without deleting the new data."
    )


@router.message(AdminFlow.waiting_restore_file, F.document)
async def restore_from_json(message: Message, state: FSMContext):
    if not admin_only(message):
        await state.clear()
        return

    document = message.document
    filename = (document.file_name or "").lower()
    if not filename.endswith(".json"):
        await message.answer("❌ Please send a valid .json backup file.")
        return

    # Keep the restore bounded so a wrong/huge upload cannot exhaust the worker memory.
    if document.file_size and document.file_size > 25 * 1024 * 1024:
        await message.answer("❌ The backup file is too large. Maximum allowed size is 25 MB.")
        return

    try:
        buffer = io.BytesIO()
        await message.bot.download(document, destination=buffer)
        buffer.seek(0)
        payload = json.loads(buffer.read().decode("utf-8-sig"))

        if not isinstance(payload, dict):
            raise ValueError("The JSON root must be an object.")
        if not isinstance(payload.get("users"), list):
            raise ValueError("The backup does not contain a valid users list.")

        # Create a safety snapshot of the current database before applying the old backup.
        safety_data = await db.backup_json()
        safety_path = Path(f"before_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
        safety_path.write_text(
            json.dumps(safety_data, default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        report = await db.restore_json_merge(payload)
        await state.clear()

        await message.answer_document(
            FSInputFile(safety_path),
            caption="🛡 Safety backup created automatically before restore.",
        )
        safety_path.unlink(missing_ok=True)

        await message.answer(
            "✅ Restore completed successfully.\n\n"
            f"Users: {report['users']}\n"
            f"Orders: {report['orders']}\n"
            f"Payments: {report['payments']}\n\n"
            "New products, prices, translations, coupons and settings were preserved from the updated bot. "
            "Newer database records that were not in the old backup were not deleted."
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        await message.answer(f"❌ Invalid JSON file: {exc}")
    except ValueError as exc:
        await message.answer(f"❌ Backup validation failed: {exc}")
    except Exception:
        logging.exception("Restore failed")
        await message.answer("❌ Restore failed. The current database was not intentionally cleared. Check Railway logs for details.")


@router.message(AdminFlow.waiting_restore_file)
async def restore_waiting_for_file(message: Message):
    if not admin_only(message):
        return
    await message.answer("📎 Please send the old backup as a .json document, or use /cancel to stop.")

@router.message(Command("cancel"))
async def cancel_admin_state(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    await state.clear()
    await message.answer("✅ Cancelled.")


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
/availability PRODUCT_ID available|unavailable
/setavailable PRODUCT_ID
/setunavailable PRODUCT_ID
Special groups: pre_order_cars, metro_sword
/setrate CATEGORY PERCENT
/setgamerate PERCENT
/setcoderate PERCENT
/setuserrate USER_ID PERCENT
/resetuserrate USER_ID
/checkrate USER_ID
/addbonus CODE MIN_DEPOSIT BONUS_AMOUNT [MAX_USES]
/editbonus CODE MIN_DEPOSIT BONUS_AMOUNT [MAX_USES]
/delbonus CODE
/bonuses
/disablebonus CODE
/enablebonus CODE
/backup
/restore  (then send the old .json backup file)
/exportusers
/exportorders
/exportbalances
"""

async def main():
    global BOT
    if not config.bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    await db.init_db()
    await ensure_feature_schema()
    await ensure_special_products()
    BOT = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await BOT.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(BOT)

if __name__ == "__main__":
    asyncio.run(main())
