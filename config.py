import os
from dataclasses import dataclass


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

@dataclass(frozen=True)
class Config:
    bot_token: str = env("BOT_TOKEN")
    database_url: str = env("DATABASE_URL")
    admin_id: int = int(env("ADMIN_ID", "8573174269") or 8573174269)
    bot_username: str = env("BOT_USERNAME", "@TopupPrimeBot")
    support_username: str = env("SUPPORT_USERNAME", "@bot_MD_global")
    channel_url: str = env("CHANNEL_URL", "https://t.me/MD_WEBSITE")
    bep20_address: str = env("BEP20_ADDRESS", "0x5FA9B715285d6CdC646D43FCc3EfdDAdbBf8Ef72")
    trc20_address: str = env("TRC20_ADDRESS", "TCa2BvRiSqLiuxV4HEh1mtBeeNWu11pYff")
    bybit_id: str = env("BYBIT_ID", "524739312")
    default_min_purchase: float = float(env("DEFAULT_MIN_PURCHASE", "0"))

config = Config()
