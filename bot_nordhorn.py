"""
TankAlert Bot — Nordhorn
Einfacher Start: feste Koordinaten für Nordhorn, klares Menü.
"""

import asyncio
import logging
import os
import math
import aiohttp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TK_API_KEY = "551667e2-2e53-49eb-b7af-2a1c17169520"

NORDHORN_LAT = 52.4306
NORDHORN_LNG = 7.0707
RADIUS_KM = 10.0

# ─── Keyboards ───────────────────────────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="⛽ Super E5",   callback_data="fuel_e5"),
        InlineKeyboardButton(text="🟢 Super E10",  callback_data="fuel_e10"),
    )
    b.row(
        InlineKeyboardButton(text="🔵 Diesel",     callback_data="fuel_diesel"),
        InlineKeyboardButton(text="📋 Alle",       callback_data="fuel_all"),
    )
    b.row(
        InlineKeyboardButton(text="⚡ Ladestationen (EV)", callback_data="ev"),
    )
    return b.as_markup()

def back_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Zurück zum Menü", callback_data="menu"))
    return b.as_markup()

# ─── Tankerkönig API ─────────────────────────────────────────────────────────

async def fetch_fuel_prices(fuel: str = "all") -> list:
    url = "https://creativecommons.tankerkoenig.de/json/list.php"
    params = {
        "apikey": TK_API_KEY,
        "lat":    NORDHORN_LAT,
        "lng":    NORDHORN_LNG,
        "rad":    RADIUS_KM,
        "type":   fuel,
        "sort":   "price",
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(url, params=params) as r:
                data = await r.json()
                if data.get("ok"):
                    return data.get("stations", [])
                logger.error(f"TK API Fehler: {data.get('message')}")
    except Exception as e:
        logger.error(f"TK fetch Fehler: {e}")
    return []

# ─── Open Charge Map API ─────────────────────────────────────────────────────

CONNECTOR_NAME = {
    33: "CCS", 2: "CHAdeMO", 25: "Type 2 (AC)", 27: "Tesla SC", 30: "Tesla CCS"
}
STATUS_LABEL = {
    0: "❓", 10: "✅ Frei", 20: "⚠️ Teilw.", 30: "🔴 Belegt",
    50: "🔧 Wartung", 100: "❌ Außer Betrieb", 200: "🟢 Online"
}

async def fetch_ev_stations() -> list:
    url = "https://api.openchargemap.io/v3/poi/"
    params = {
        "output":       "json",
        "latitude":     NORDHORN_LAT,
        "longitude":    NORDHORN_LNG,
        "distance":     RADIUS_KM,
        "distanceunit": "KM",
        "maxresults":   10,
        "countrycode":  "DE",
        "compact":      "false",
        "verbose":      "false",
    }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=12),
            headers={"User-Agent": "TankAlertBot/1.0"}
        ) as s:
            async with s.get(url, params=params) as r:
                return await r.json(content_type=None)
    except Exception as e:
        logger.error(f"OCM fetch Fehler: {e}")
    return []

# ─── Formatters ──────────────────────────────────────────────────────────────

FUEL_EMOJI = {"e5": "⛽", "e10": "🟢", "diesel": "🔵", "all": "📋"}
FUEL_LABEL = {"e5": "Super E5", "e10": "Super E10", "diesel": "Diesel", "all": "Alle"}
MEDALS = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8."]

def format_fuel_list(stations: list, fuel: str) -> str:
    if not stations:
        return "❌ Keine Tankstellen in Nordhorn gefunden."
    label = FUEL_LABEL.get(fuel, fuel.upper())
    emoji = FUEL_EMOJI.get(fuel, "⛽")
    lines = [f"{emoji} <b>{label} — Top {min(len(stations), 8)} in Nordhorn</b>\n"]
    for i, s in enumerate(stations[:8]):
        if fuel == "all":
            prices = {k: s[k] for k in ("e5", "e10", "diesel") if s.get(k) and s[k] != "false"}
            if not prices:
                continue
            best_key = min(prices, key=prices.get)
            price_str = f"{prices[best_key]:.3f} €  ({FUEL_LABEL[best_key]})"
        else:
            price_val = s.get(fuel)
            if not price_val or price_val == "false":
                continue
            price_str = f"{price_val:.3f} €"
        status = "✅" if s.get("isOpen") else "🔴"
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        lines.append(
            f"{medal} {status} <b>{s.get('name', '?')}</b>\n"
            f"    💰 <b>{price_str}</b>  ·  📍 {s.get('dist', 0):.1f} km\n"
            f"    🏠 {s.get('street', '')}\n"
        )
    lines.append("\n🔄 <i>Daten: Tankerkönig API (CC-BY 4.0)</i>")
    return "\n".join(lines)

def haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
    return round(R * 2 * math.asin(math.sqrt(a)), 2)

def format_ev_list(stations: list) -> str:
    if not stations:
        return "❌ Keine Ladestationen in Nordhorn gefunden."
    lines = ["⚡ <b>Ladestationen — Nordhorn & Umgebung</b>\n"]
    for i, s in enumerate(stations[:8]):
        addr = s.get("AddressInfo", {})
        name = addr.get("Title", "Ladestation")
        street = addr.get("AddressLine1", "")
        operator = (s.get("OperatorInfo") or {}).get("Title", "")
        status_type = s.get("StatusType") or {}
        status_id = status_type.get("ID", 0) if status_type else 0
        status = STATUS_LABEL.get(status_id, "❓")
        num_points = s.get("NumberOfPoints") or 1
        connectors = s.get("Connections") or []
        powers = [c.get("PowerKW") for c in connectors if c.get("PowerKW")]
        max_kw = f"{max(powers):.0f} kW" if powers else "?"
        speed = "⚡ Schnell" if powers and max(powers) > 22 else "🐢 AC"
        type_ids = {(c.get("ConnectionType") or {}).get("ID") for c in connectors}
        types_str = ", ".join(CONNECTOR_NAME.get(t, "?") for t in type_ids if t) or "?"
        dist = haversine(NORDHORN_LAT, NORDHORN_LNG,
                         addr.get("Latitude", NORDHORN_LAT),
                         addr.get("Longitude", NORDHORN_LNG))
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        lines.append(
            f"{medal} <b>{name}</b>\n"
            f"    {status}  ·  📍 {dist:.1f} km  ·  {speed} ({max_kw})\n"
            f"    🔌 {types_str}  ·  {num_points} Ladepunkt(e)\n"
            f"    🏢 {operator}  ·  {street}\n"
        )
    lines.append("\n🔄 <i>Daten: Open Charge Map (CC-BY-SA)</i>")
    return "\n".join(lines)

# ─── Handlers ────────────────────────────────────────────────────────────────

router = Router()

WELCOME = (
    "⛽ <b>TankAlert — Nordhorn</b>\n\n"
    "Aktuelle Spritpreise und Ladestationen\n"
    "rund um Nordhorn auf einen Blick.\n\n"
    "Was suchst du?"
)

@router.message(CommandStart())
async def cmd_start(msg: Message):
    await msg.answer(WELCOME, reply_markup=main_menu())

@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(WELCOME, reply_markup=main_menu())

@router.callback_query(F.data.startswith("fuel_"))
async def cb_fuel(call: CallbackQuery):
    fuel = call.data.replace("fuel_", "")
    await call.answer()
    await call.message.edit_text("🔄 Lade Preise...", reply_markup=None)
    stations = await fetch_fuel_prices(fuel)
    text = format_fuel_list(stations, fuel)
    await call.message.edit_text(text, reply_markup=back_menu())

@router.callback_query(F.data == "ev")
async def cb_ev(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text("🔄 Suche Ladestationen...", reply_markup=None)
    stations = await fetch_ev_stations()
    text = format_ev_list(stations)
    await call.message.edit_text(text, reply_markup=back_menu())

@router.message(Command("prices"))
async def cmd_prices(msg: Message):
    loading = await msg.answer("🔄 Lade Preise...")
    stations = await fetch_fuel_prices("all")
    text = format_fuel_list(stations, "all")
    await loading.edit_text(text, reply_markup=back_menu())

@router.message(Command("ev"))
async def cmd_ev(msg: Message):
    loading = await msg.answer("🔄 Suche Ladestationen...")
    stations = await fetch_ev_stations()
    text = format_ev_list(stations)
    await loading.edit_text(text, reply_markup=back_menu())

# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN fehlt! Trage ihn in die .env Datei ein.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start",  description="🚗 Hauptmenü"),
        BotCommand(command="prices", description="⛽ Spritpreise Nordhorn"),
        BotCommand(command="ev",     description="⚡ Ladestationen Nordhorn"),
    ])

    logger.info("✅ TankAlert Bot gestartet — Nordhorn")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
