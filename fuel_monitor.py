import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


API_URL = "https://xn--80ao4a.xn----dtbsbdgikgdbazpac.xn--p1ai/api/public/stations"

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

STATE_FILE = "fuel_state.json"


def send_telegram(text, strong=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_notification": not strong,
        },
        timeout=30,
    )

    response.raise_for_status()


def get_stations():
    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()
    return response.json()["data"]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def fuel_status(fuel):
    if not fuel:
        return "—"

    if fuel.get("available"):
        price = fuel.get("price")

        if price is not None:
            return f"✅ в наличии ({price} ₽/л)"

        return "✅ в наличии"

    return "❌ нет"


def normalize_detail(detail):
    return (detail or "").lower().replace("ё", "е")


def is_95_for_everyone(station):
    fuel95 = station.get("availableFuel", {}).get("95", {})

    if not fuel95.get("available"):
        return False

    detail = normalize_detail(station.get("detail"))

    restricted_words = [
        "только по топливным картам",
        "только для спец",
        "спецтранспорт",
        "только спец",
    ]

    for word in restricted_words:
        if word in detail:
            return False

    return True


def station_snapshot(station):
    return {
        "updatedAt": station.get("updatedAt"),
        "status": station.get("status"),
        "queueCars": station.get("queueCars"),
        "detail": station.get("detail"),
        "availableFuel": station.get("availableFuel", {}),
    }

def format_updated_at(value):
    if not value:
        return "—"

    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    dt = dt.astimezone(ZoneInfo("Europe/Moscow"))

    return dt.strftime("%d.%m.%Y %H:%M:%S")

def station_text(station):
    fuel = station.get("availableFuel", {})

    text = (
        f"⛽ {station.get('name', 'АЗС')}\n"
        f"📍 {station.get('address', '')}\n"
        f"🕒 Обновлено: {format_updated_at(station.get('updatedAt'))}\n\n"
        f"АИ-92: {fuel_status(fuel.get('92'))}\n"
        f"АИ-95: {fuel_status(fuel.get('95'))}\n"
        f"АИ-100: {fuel_status(fuel.get('100'))}\n"
        f"ДТ: {fuel_status(fuel.get('DT'))}\n"
        f"ДТ+: {fuel_status(fuel.get('DT_PLUS'))}\n"
    )

    queue = station.get("queueCars")

    if queue is not None:
        text += f"\n🚗 Очередь: {queue} авто"

    detail = station.get("detail")

    if detail:
        text += f"\n\n📝 {detail}"

    return text


def changes_text(old, new):
    changes = []

    if old.get("queueCars") != new.get("queueCars"):
        changes.append(
            f"🚗 очередь: {old.get('queueCars')} → {new.get('queueCars')}"
        )

    old_fuel = old.get("availableFuel", {})
    new_fuel = new.get("availableFuel", {})

    for fuel_name, title in [
        ("92", "АИ-92"),
        ("95", "АИ-95"),
        ("100", "АИ-100"),
        ("DT", "ДТ"),
        ("DT_PLUS", "ДТ+"),
    ]:
        old_value = old_fuel.get(fuel_name, {})
        new_value = new_fuel.get(fuel_name, {})

        if old_value != new_value:
            changes.append(
                f"⛽ {title}: "
                f"{fuel_status(old_value)} → {fuel_status(new_value)}"
            )

    if old.get("status") != new.get("status"):
        changes.append(
            f"📌 статус: {old.get('status')} → {new.get('status')}"
        )

    if old.get("detail") != new.get("detail"):
        changes.append("📝 изменился комментарий АЗС")

    return changes


def main():
    stations = get_stations()
    old_state = load_state()

    new_state = {}
    normal_changes = []
    priority_changes = []

    for station in stations:
        station_id = str(station["id"])
        current = station_snapshot(station)

        new_state[station_id] = current

        # Первый запуск — просто сохраняем состояние.
        if station_id not in old_state:
            continue

        previous = old_state[station_id]

        if previous == current:
            continue

        changes = changes_text(previous, current)

        # Проверяем появление АИ-95 для всех.
        old_95 = {
            "available": is_95_for_everyone({
                "availableFuel": previous.get("availableFuel", {}),
                "detail": previous.get("detail"),
            })
        }

        new_95 = is_95_for_everyone(station)

        if new_95 and not old_95["available"]:
            priority_changes.append(station)
        else:
            normal_changes.append((station, changes))

    save_state(new_state)

    # 🚨 Самый важный тип уведомления.
    for station in priority_changes:
        message = (
            "🚨🚨🚨 АИ-95 ПОЯВИЛСЯ ДЛЯ ВСЕХ 🚨🚨🚨\n\n"
            + station_text(station)
        )

        send_telegram(message, strong=True)

    # Обычные изменения.
    if normal_changes:
        message_parts = ["🔔 ОБНОВЛЕНИЯ НА АЗС\n"]

        for station, changes in normal_changes:
            message_parts.append(
                station_text(station)
                + "\n\n"
                + "🔄 Что изменилось:\n"
                + "\n".join(changes)
                + "\n\n"
                + "━━━━━━━━━━━━━━\n"
            )

        send_telegram("\n".join(message_parts))


if __name__ == "__main__":
    main()
