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

    # Telegram разрешает максимум 4096 символов.
    # Используем запас, чтобы гарантированно не получить ошибку.
    max_length = 4000

    messages = []

    while len(text) > max_length:
        split_at = text.rfind("\n", 0, max_length)

        if split_at == -1:
            split_at = max_length

        messages.append(text[:split_at])
        text = text[split_at:].lstrip()

    if text:
        messages.append(text)

    print(
        f"Telegram: prepared {len(messages)} message(s)"
    )

    for index, message in enumerate(messages, start=1):

        print(
            f"Sending Telegram message "
            f"{index}/{len(messages)}, "
            f"length: {len(message)}"
        )

        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_notification": not strong,
            },
            timeout=30,
        )

        print(
            "Telegram HTTP status:",
            response.status_code
        )

        print(
            "Telegram response:",
            response.text
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                f"Telegram API error: {data}"
            )

        print(
            f"Telegram message {index} "
            f"sent successfully"
        )


def get_stations():
    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()

    data = response.json()

    print("Stations API HTTP status:", response.status_code)
    print(f"Stations received: {len(data.get('data', []))}")

    return data["data"]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )


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
    """
    Проверяет, доступен ли АИ-95 обычным клиентам.

    Считаем 95 доступным для всех, если:
    - available = true
    - в комментарии нет признаков ограниченной продажи.
    """

    fuel95 = station.get("availableFuel", {}).get("95", {})

    if not fuel95.get("available"):
        return False

    detail = normalize_detail(station.get("detail"))

    restricted_phrases = [
        "только по топливным картам",
        "по топливным картам",
        "только для спец",
        "для спецтранспорта",
        "для спец транспорта",
        "спецтранспорт",
        "спец транспорт",
        "только спец",
        "только для юридических лиц",
        "только для юрлиц",
        "только для юрид. лиц",
        "только для организаций",
        "служебный транспорт",
    ]

    for phrase in restricted_phrases:
        if phrase in detail:
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
    """
    API возвращает время в UTC.
    Показываем пользователю московское время.
    """

    if not value:
        return "—"

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        dt = dt.astimezone(
            ZoneInfo("Europe/Moscow")
        )

        return dt.strftime("%d.%m.%Y %H:%M:%S")

    except Exception:
        return value


def station_text(station):
    fuel = station.get("availableFuel", {})

    text = (
        f"⛽ {station.get('name', 'АЗС')}\n"
        f"📍 {station.get('address', '')}\n"
        f"🕒 Обновлено: "
        f"{format_updated_at(station.get('updatedAt'))}\n\n"
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
            f"🚗 очередь: "
            f"{old.get('queueCars')} → {new.get('queueCars')}"
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
                f"{fuel_status(old_value)} → "
                f"{fuel_status(new_value)}"
            )

    if old.get("status") != new.get("status"):
        changes.append(
            f"📌 статус: "
            f"{old.get('status')} → {new.get('status')}"
        )

    if old.get("detail") != new.get("detail"):
        changes.append(
            "📝 изменился комментарий АЗС"
        )

    if old.get("updatedAt") != new.get("updatedAt"):
        changes.append(
            f"🕒 обновлено: "
            f"{format_updated_at(old.get('updatedAt'))} → "
            f"{format_updated_at(new.get('updatedAt'))}"
        )

    return changes


def main():
    print("=== Fuel Monitor started ===")

    stations = get_stations()
    old_state = load_state()

    print(
        f"Previous state stations: "
        f"{len(old_state)}"
    )

    new_state = {}

    normal_changes = []
    priority_changes = []

    for station in stations:
        station_id = str(station["id"])
        station_name = station.get("name", "АЗС")

        print(
            f"Checking station: "
            f"{station_name} (ID {station_id})"
        )

        current = station_snapshot(station)

        new_state[station_id] = current

        # Первый запуск:
        # только сохраняем начальное состояние.
        if station_id not in old_state:
            print(
                f"  First run for station: "
                f"{station_name}"
            )
            continue

        previous = old_state[station_id]

        if previous == current:
            print("  No changes")
            continue

        print(
            f"  CHANGE DETECTED: "
            f"{station_name}"
        )

        changes = changes_text(
            previous,
            current,
        )

        # Проверяем АИ-95.
        old_95 = is_95_for_everyone(
            {
                "availableFuel": previous.get(
                    "availableFuel", {}
                ),
                "detail": previous.get("detail"),
            }
        )

        new_95 = is_95_for_everyone(station)

        print(
            f"  AI-95 for everyone: "
            f"{old_95} → {new_95}"
        )

        if new_95 and not old_95:
            print(
                f"  🚨 PRIORITY: AI-95 appeared "
                f"for everyone at {station_name}"
            )

            priority_changes.append(station)

        elif changes:
            normal_changes.append(
                (station, changes)
            )

    print(
        f"Priority changes: "
        f"{len(priority_changes)}"
    )

    print(
        f"Normal changes: "
        f"{len(normal_changes)}"
    )

    # ============================================================
    # Сначала отправляем уведомления.
    # Состояние сохраняем после успешной отправки.
    # ============================================================

    # 🚨 АИ-95 появился для всех.
    for station in priority_changes:

        message = (
            "🚨🚨🚨 АИ-95 ПОЯВИЛСЯ ДЛЯ ВСЕХ 🚨🚨🚨\n\n"
            + station_text(station)
        )

        print(
            "Sending PRIORITY Telegram notification: "
            f"{station.get('name', 'АЗС')}"
        )

        send_telegram(
            message,
            strong=True,
        )

    # 🔔 Обычные изменения.
    if normal_changes:

        message_parts = [
            "🔔 ОБНОВЛЕНИЯ НА АЗС\n"
        ]

        for station, changes in normal_changes:

            message_parts.append(
                station_text(station)
                + "\n\n"
                + "🔄 Что изменилось:\n"
                + "\n".join(changes)
                + "\n\n"
                + "━━━━━━━━━━━━━━\n"
            )

        print(
            "Sending NORMAL Telegram notification"
        )

        send_telegram(
            "\n".join(message_parts)
        )

    # Если изменений нет — это нормально.
    if not priority_changes and not normal_changes:
        print(
            "No changes detected. "
            "Telegram notification is not required."
        )

    # ============================================================
    # Сохраняем состояние.
    # ============================================================

    save_state(new_state)

    print("State saved successfully")
    print("=== Fuel Monitor finished successfully ===")


if __name__ == "__main__":
    main()
