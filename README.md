# Prime Topup Bot

Telegram Python bot for **Prime Topup** / `@TopupPrimeBot`.

## Features

- Main menu with Voucher Products, My Wallet, My Orders, Game ID, Product Games, Language, About, Support.
- Wallet system with BEP20, TRC20, Bybit ID.
- Transaction history.
- Manual fulfilment that looks automatic to customers: users immediately see: `⏳ Your order is being processed. You'll be notified once it's complete.`
- Admin notifications for new users, user messages, payments, and orders.
- Admin reply command.
- Product/rate/price management.
- Backup and CSV exports.
- PostgreSQL support for Railway.

## Railway Variables

Add these variables on Railway:

```env
BOT_TOKEN=your_botfather_token
DATABASE_URL=your_railway_postgres_url
ADMIN_ID=8573174269
BOT_USERNAME=@TopupPrimeBot
SUPPORT_USERNAME=@bot_MD_global
CHANNEL_URL=https://t.me/MD_WEBSITE
BEP20_ADDRESS=0x5FA9B715285d6CdC646D43FCc3EfdDAdbBf8Ef72
TRC20_ADDRESS=TCa2BvRiSqLiuxV4HEh1mtBeeNWu11pYff
BYBIT_ID=524739312
DEFAULT_MIN_PURCHASE=0
```

## Deploy on Railway

1. Create a GitHub repository.
2. Upload these files.
3. Create new Railway project from GitHub.
4. Add PostgreSQL plugin.
5. Copy `DATABASE_URL` into Variables.
6. Add the rest of the Variables.
7. Deploy.

## Admin Commands

```text
/admin
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
```

## Notes

Telegram bots cannot directly copy text to a user clipboard. The Copy Address button sends the wallet address as a separate copyable message.

The bot is set to polling for easier Railway deployment.
