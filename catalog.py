from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

@dataclass
class Product:
    id: str
    title: str
    base: float
    category: str
    ask_game_id: bool = False

# Static seed catalog. Admin can modify prices/rates in DB after first run.
# Voucher/card products generally use fixed visible USDT prices from your screenshots.
CATEGORIES: Dict[str, str] = {
    "pubg_voucher": "PUBG MOBILE VOUCHER",
    "razer_global": "RAZER GOLD GLOBAL",
    "steam_usa": "STEAM USA",
    "playstation_usa": "PlayStation USA",
    "itunes_usa": "iTunes USA",
    "ff_voucher": "GARENA FREE FIRE VOUCHERS",
    "yalla_ludo": "Yalla Ludo",
    "valorant": "VALORANT",
    "valorant_usa": "VALORANT USA",
    "valorant_ru": "VALORANT RU",
    "roblox": "ROBLOX",
    "roblox_global": "ROBLOX GLOBAL",
    "roblox_usa": "ROBLOX USA",
    "pubg_topup": "PUBG MOBIL TOPUP",
    "ff_topup": "FREE FIRE TOPUP",
    "arena": "Arena Breakout",
    "baloot": "Baloot Coin",
    "zepeto": "ZEPETO",
    "mobile_legends": "Mobile Legends",
    "league": "League of Legends",
}

PARENT_MENUS = {
    "voucher": [
        "pubg_voucher", "razer_global", "steam_usa", "playstation_usa", "itunes_usa",
        "ff_voucher", "yalla_ludo", "valorant", "roblox",
    ],
    "gameid": ["pubg_topup", "ff_topup", "arena", "baloot", "zepeto", "mobile_legends", "league"],
}

SUBCATEGORIES = {
    "valorant": ["valorant_usa", "valorant_ru"],
    "roblox": ["roblox_global", "roblox_usa"],
}

DEFAULT_RATES = {
    "pubg_voucher": 84.0,
    "ff_voucher": 84.0,
    "yalla_ludo": 83.0,
    "valorant_usa": 84.0,
    "valorant_ru": 84.0,
    "roblox_global": 82.0,
    "roblox_usa": 82.0,
    "pubg_topup": 82.0,
    "ff_topup": 82.0,
    "arena": 78.0,
    "baloot": 78.0,
    "zepeto": 78.0,
    "mobile_legends": 78.0,
    "league": 78.0,
}

# Products with base means the full nominal USD value before percentage rate.
# Products with base equal to final fixed price are stored with rate 100 in DB seed.
STATIC_PRODUCTS: List[Product] = [
    # Voucher PUBG 84%
    *[Product(f"pubg_voucher_{x}", f"{x} UC", b, "pubg_voucher") for x, b in [(60,1),(325,5),(660,10),(1800,25),(3850,50),(8100,100)]],

    # Fixed voucher cards
    *[Product(f"razer_{d}", f"${d}", p, "razer_global") for d,p in [(5,4.20),(10,8.40),(20,16.80),(50,42.00),(100,84.00),(200,168.00)]],
    *[Product(f"steam_{d}", f"${d}", p, "steam_usa") for d,p in [(5,4.00),(10,8.00),(20,16.00),(50,40.00),(100,80.00),(200,160.00)]],
    *[Product(f"ps_{d}", f"${d}", p, "playstation_usa") for d,p in [(5,4.00),(10,8.00),(20,16.00),(50,40.00),(100,80.00),(200,160.00)]],
    *[Product(f"itunes_{d}", f"{d}$ US GiftCard", p, "itunes_usa") for d,p in [(5,4.10),(10,8.20),(20,16.40),(50,41.00),(100,82.00),(200,164.00)]],

    # Free Fire vouchers at 84% (base nominal USD)
    *[Product(f"ffv_{name}", name, base, "ff_voucher") for name, base in [
        ("100 Diamond",1),("210 Diamond",2),("530 Diamond",5),("1080 Diamond",10),("2200 Diamond",20),("5600 Diamond",56)
    ]],

    # Yalla Ludo at 83% from screenshot nominal USD values
    *[Product(f"yalla_{i}", title, base, "yalla_ludo") for i,(title,base) in enumerate([
        ("5 USD 2320 Diamond",4.60),("10 USD 5150 Diamond",10.24),("25 USD 13580 Diamond",27.05),
        ("50 USD 27640 Diamond",55.07),("100 USD 55800 Diamond",111.10),("50 USD GOLD",51.84),("100 USD GOLD",103.68)
    ],1)],

    # Valorant USA/RU at 84% using base derived from screenshot prices approximately.
    *[Product(f"val_usa_{vp}", f"{vp} VP", base, "valorant_usa") for vp,base in [
        (240,3.35),(325,4.07),(475,5.46),(1000,11.17),(1520,16.63),(1750,20.26),(2050,22.24),(2575,27.55),(3650,38.73),(5350,55.27),(8700,87.57),(11000,112.61)
    ]],
    *[Product(f"val_ru_{vp}", f"{vp} VP", base, "valorant_ru") for vp,base in [
        (240,3.3456),(325,4.0705),(475,5.4573),(1000,11.1714),(1520,16.6312),(1750,20.2586),(2050,22.2450),(2575,27.5455),(3650,38.7286),(5350,55.2735),(8700,87.5739),(11000,112.6080)
    ]],

    # Roblox 82%
    *[Product(f"roblox_usa_{d}", f"Roblox {d}$ US", d, "roblox_usa") for d in [4,5,10,15,25,30,50,75,100]],
    *[Product(f"roblox_global_{r}", f"{r} Robux", base, "roblox_global") for r,base in [
        (225,2.7154/0.82),(230,2.8866/0.82),(240,3.0294/0.82),(295,3.5394/0.82),(300,3.7581/0.82),
        (310,3.8352/0.82),(370,4.2832/0.82),(390,4.7532/0.82),(400,4.845/0.82),(450,5.4395/0.82),
        (500,6.2242/0.82),(600,7.293/0.82),(775,9.078/0.82),(800,8.9627/0.82),(1000,11.3322/0.82)
    ]],

    # Game ID topups
    *[Product(f"pubg_topup_{uc}", f"{uc} UC", base, "pubg_topup", True) for uc,base in [
        (60,1),(120,2),(180,3),(325,5),(385,6),(660,10),(720,11),(780,12),(985,15),(1800,25),(3850,50),(8100,100)
    ]],
    *[Product(f"ff_topup_{g}", f"Free Fire {g} Gem", base, "ff_topup", True) for g,base in [(100,1),(210,2),(530,5),(1080,10),(2200,20)]],
    *[Product(f"arena_{c}", f"Arena Breakout {c} Coins", price/0.78, "arena", True) for c,price in [(60,0.78),(310,3.90),(630,7.80),(1580,19.50),(3200,39.00),(6500,78.00)]],
    *[Product(f"baloot_{c}", f"Baloot {c:,} Coins", price/0.78, "baloot", True) for c,price in [(32800,1.17),(94300,3.12),(215800,6.24),(406800,10.40),(1080000,24.96),(2376000,49.92),(5427000,104.00),(11113600,208.00)]],
    *[Product(f"zepeto_{i}", title, price/0.78, "zepeto", True) for i,(title,price) in enumerate([
        ("ZEPETO 28 ZEMs",1.56),("ZEPETO 128 ZEMs",6.24),("ZEPETO 323 ZEMs",15.60),("ZEPETO 1000 ZEMs",46.80),
        ("ZEPETO 4,680 Coins",0.78),("ZEPETO 9,700 Coins",1.56),("ZEPETO 25,200 Coins",3.90),("ZEPETO 40,700 Coins",6.24),("ZEPETO 110,000 Coins",15.60),("ZEPETO 300,000 Coins",39.00)
    ],1)],
    *[Product(f"ml_{i}", title, price/0.78, "mobile_legends", True) for i,(title,price) in enumerate([
        ("Mobile Legends 253 + 25 Diamonds",3.90),("Mobile Legends 505 + 66 Diamonds",7.80),("Mobile Legends 1010 + 182 Diamonds",15.60),
        ("Mobile Legends 1515 + 273 Diamonds",23.40),("Mobile Legends 2525 + 480 Diamonds",39.00),("Mobile Legends 3030 + 576 Diamonds",46.80),
        ("Mobile Legends 4008 + 802 Diamonds",62.40),("Mobile Legends 5010 + 1002 Diamonds",78.00)
    ],1)],
    *[Product(f"lol_{d}", f"League of Legends Riot Cash USD {d}", d, "league", True) for d in [4.99,10,19.99,25,50,100]],
]

FIXED_RATE_CATEGORIES = {"razer_global", "steam_usa", "playstation_usa", "itunes_usa"}

def calc_price(base: float, rate: float) -> float:
    return round(base * rate / 100.0 + 1e-9, 2)
