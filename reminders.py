#!/usr/bin/env python3
"""Recordatorios por Telegram. Pensado para correr con un cron de GitHub Actions.

Uso:
    python reminders.py                      # envía lo que ya venció
    python reminders.py --dry-run            # muestra qué enviaría, sin enviar nada
    python reminders.py --test               # manda un mensaje de prueba al chat
    python reminders.py --now 2026-10-26T18:00   # simula otra hora (para verificar)

Variables de entorno:
    TELEGRAM_BOT_TOKEN   token del bot (obligatorio salvo --dry-run)
    TELEGRAM_CHAT_ID     id del chat destino (obligatorio salvo --dry-run)
    STATE_FILE           archivo de estado (default: sent_state.json)
    REMINDER_TZ          zona horaria si el schedule.json no la define
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import sys
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Costa_Rica"
DEFAULT_WINDOW_MINUTES = 45  # avisa tarde si el cron de GitHub se demoró
DEFAULT_STATE_FILE = "sent_state.json"
STATE_MAX_AGE_DAYS = 60
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MONTH_ES = ["ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic"]

VALID_TYPES = {"once", "daily", "weekly", "monthly"}


class ScheduleError(Exception):
    """El schedule.json está mal armado."""


# ---------------------------------------------------------------- schedule ---

def load_schedule(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise ScheduleError(f"No existe el archivo de horarios: {path}")
    except json.JSONDecodeError as exc:
        raise ScheduleError(f"JSON inválido en {path}: {exc}")

    if not isinstance(raw, dict) or not isinstance(raw.get("reminders"), list):
        raise ScheduleError(f"{path}: falta la lista 'reminders'.")

    seen: set[str] = set()
    for idx, rem in enumerate(raw["reminders"]):
        where = f"reminders[{idx}]"
        if not isinstance(rem, dict):
            raise ScheduleError(f"{where}: debe ser un objeto.")
        rid = rem.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ScheduleError(f"{where}: falta 'id' (texto único).")
        if rid in seen:
            raise ScheduleError(f"{where}: 'id' repetido: {rid!r}")
        seen.add(rid)

        if not isinstance(rem.get("text"), str) or not rem["text"].strip():
            raise ScheduleError(f"[{rid}]: falta 'text' (el mensaje).")

        kind = rem.get("type", "weekly")
        if kind not in VALID_TYPES:
            raise ScheduleError(
                f"[{rid}]: 'type' inválido {kind!r}. Opciones: {sorted(VALID_TYPES)}")
        rem["type"] = kind

        _parse_time(rem.get("time"), rid)

        if kind == "weekly":
            days = rem.get("days")
            if not isinstance(days, list) or not days:
                raise ScheduleError(f"[{rid}]: 'weekly' necesita 'days', ej. [\"mon\",\"wed\"]")
            norm = []
            for day in days:
                key = str(day).strip().lower()[:3]
                if key not in WEEKDAYS:
                    raise ScheduleError(
                        f"[{rid}]: día inválido {day!r}. Usá mon, tue, wed, thu, fri, sat, sun.")
                norm.append(key)
            rem["days"] = sorted(set(norm))

        if kind == "monthly":
            day_num = rem.get("day")
            if not isinstance(day_num, int) or not (1 <= day_num <= 31 or day_num == -1):
                raise ScheduleError(
                    f"[{rid}]: 'monthly' necesita 'day' entre 1 y 31, o -1 para el último día.")

        if kind == "once":
            try:
                dt.date.fromisoformat(str(rem.get("date")))
            except ValueError:
                raise ScheduleError(f"[{rid}]: 'once' necesita 'date' en formato AAAA-MM-DD.")

        lead = rem.get("lead_minutes", 0)
        if not isinstance(lead, int) or lead < 0:
            raise ScheduleError(f"[{rid}]: 'lead_minutes' debe ser un entero >= 0.")
        rem["lead_minutes"] = lead

        if not isinstance(rem.get("active", True), bool):
            raise ScheduleError(f"[{rid}]: 'active' debe ser true o false.")

    return raw


def _parse_time(value, rid: str) -> dt.time:
    try:
        hour, minute = str(value).strip().split(":")
        parsed = dt.time(int(hour), int(minute))
    except (ValueError, AttributeError):
        raise ScheduleError(f"[{rid}]: hora inválida {value!r}. Usá \"HH:MM\", ej. \"18:30\".")
    return parsed


def active_reminders(schedule: dict) -> list[dict]:
    return [rem for rem in schedule["reminders"] if rem.get("active", True)]


def occurrences_on(rem: dict, day: dt.date, tz: ZoneInfo) -> list[dt.datetime]:
    """Momentos del día en que toca el recordatorio (normalmente 0 o 1)."""
    moment = _parse_time(rem.get("time"), rem["id"])
    kind = rem["type"]

    if kind == "once":
        if dt.date.fromisoformat(rem["date"]) == day:
            return [dt.datetime.combine(day, moment, tzinfo=tz)]
        return []

    if kind == "daily":
        return [dt.datetime.combine(day, moment, tzinfo=tz)]

    if kind == "weekly":
        return ([dt.datetime.combine(day, moment, tzinfo=tz)]
                if day.weekday() in {WEEKDAYS[d] for d in rem["days"]} else [])

    if kind == "monthly":
        last_day = calendar.monthrange(day.year, day.month)[1]
        target = last_day if rem["day"] == -1 else rem["day"]
        return ([dt.datetime.combine(day, moment, tzinfo=tz)]
                if day.day == target else [])

    return []


def due_until(reminders: list[dict], now: dt.datetime,
              window_minutes: int = DEFAULT_WINDOW_MINUTES) -> list[dict]:
    """Devuelve los recordatorios cuyo aviso ya debe salir.

    Mira ayer y hoy para cubrir avisos previos que caen antes de medianoche
    (por ejemplo un evento a las 00:15 con lead_minutes=30).
    """
    window = dt.timedelta(minutes=window_minutes)
    found: dict[str, dict] = {}

    for day in (now.date() - dt.timedelta(days=1), now.date()):
        for rem in reminders:
            for moment in occurrences_on(rem, day, now.tzinfo):
                due = moment - dt.timedelta(minutes=rem.get("lead_minutes", 0))
                # Un aviso "X minutos antes" ya no sirve si el evento empezó.
                if rem.get("lead_minutes", 0) and now > moment:
                    continue
                if due <= now <= due + window:
                    key = f'{rem["id"]}|{moment.astimezone(dt.timezone.utc).isoformat()}'
                    found.setdefault(key, {"key": key, "reminder": rem,
                                           "moment": moment, "due": due})

    return sorted(found.values(), key=lambda item: item["due"])


# ------------------------------------------------------------------ estado ---

def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        print(f"AVISO: no pude leer {path}, arranco de cero.", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: str, state: dict) -> None:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=STATE_MAX_AGE_DAYS)
    pruned = {}
    for key, iso in state.items():
        try:
            when = dt.datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            continue
        if when >= cutoff:
            pruned[key] = iso
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(pruned.items())), fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------- telegram ---

def telegram_call(token: str, method: str, payload: dict):
    url = TELEGRAM_API.format(token=token, method=method)
    data = urllib.parse.urlencode(payload).encode()
    last_error = None

    for attempt in range(1, 4):
        request = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"ok": False, "description": f"HTTP {exc.code}: {raw[:300]}"}
            if exc.code == 429:
                wait = int(body.get("parameters", {}).get("retry_after", 3))
                last_error = f"Telegram pidió esperar {wait}s (429)"
                _time.sleep(min(wait, 20))
                continue
            raise RuntimeError(f"Telegram {method} falló: {body.get('description')}") from None
        except urllib.error.URLError as exc:
            last_error = f"no pude llegar a Telegram: {exc.reason}"
            _time.sleep(attempt * 2)
            continue

        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} falló: {body}")
        return body["result"]

    raise RuntimeError(last_error or "Telegram no respondió")


def send_telegram(token: str, chat_id: str, text: str) -> None:
    telegram_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    })


# ----------------------------------------------------------------- formato ---

def format_when(moment: dt.datetime) -> str:
    return (f"{WEEKDAY_ES[moment.weekday()]} {moment.day:02d} "
            f"{MONTH_ES[moment.month - 1]} {moment.strftime('%H:%M')}")


def format_message(item: dict, now: dt.datetime) -> str:
    rem = item["reminder"]
    lines = [f'⏰ {rem["text"].strip()}', f'🗓️ {format_when(item["moment"])}']
    late = now - item["due"]
    if late > dt.timedelta(minutes=10):
        minutes = int(late.total_seconds() // 60)
        lines.append(f"⚠️ Aviso retrasado unos {minutes} min (el cron venía demorado)")
    return "\n".join(lines)


# -------------------------------------------------------------------- main ---

def _parse_now(value: str | None, tz: ZoneInfo) -> dt.datetime:
    if not value:
        return dt.datetime.now(tz)
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _force_utf8_output() -> None:
    """En Windows la consola suele ser cp1252 y los emojis rompen los prints."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description="Envía recordatorios por Telegram.")
    parser.add_argument("--schedule", default="schedule.json", help="archivo de horarios")
    parser.add_argument("--state", default=os.environ.get("STATE_FILE", DEFAULT_STATE_FILE))
    parser.add_argument("--dry-run", action="store_true",
                        help="no envía ni guarda estado; solo muestra")
    parser.add_argument("--test", action="store_true",
                        help="manda un mensaje de prueba y termina")
    parser.add_argument("--now", help="simula esta hora ISO, ej. 2026-10-26T18:00")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_MINUTES,
                        help="minutos de tolerancia para avisar tarde")
    args = parser.parse_args(argv)

    dry_run = args.dry_run or os.environ.get("DRY_RUN") == "1"

    try:
        schedule = load_schedule(args.schedule)
    except ScheduleError as exc:
        print(f"ERROR en {args.schedule}: {exc}", file=sys.stderr)
        return 1

    tz = ZoneInfo(schedule.get("timezone") or os.environ.get("REMINDER_TZ") or DEFAULT_TZ)
    now = _parse_now(args.now, tz)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if args.test:
        text = "🔔 Prueba de conexión: el bot de recordatorios está funcionando."
        if dry_run:
            print(f"[dry-run] enviaría:\n{text}")
            return 0
        if not token or not chat_id:
            print("ERROR: faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID.", file=sys.stderr)
            return 1
        try:
            send_telegram(token, chat_id, text)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("Mensaje de prueba enviado.")
        return 0

    if not dry_run and (not token or not chat_id):
        print("ERROR: faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID.", file=sys.stderr)
        return 1

    state = load_state(args.state)
    pending = [item for item in due_until(active_reminders(schedule), now, args.window)
               if item["key"] not in state]

    stamp = now.strftime("%Y-%m-%d %H:%M %Z")
    print(f"Revisando {len(active_reminders(schedule))} recordatorios activos — {stamp}")

    if not pending:
        print("Sin recordatorios pendientes.")
        return 0

    sent = 0
    failed = 0
    for item in pending:
        message = format_message(item, now)
        label = item["reminder"]["id"]
        if dry_run:
            print(f"\n--- [dry-run] {label} ---\n{message}")
            sent += 1
            continue
        try:
            send_telegram(token, chat_id, message)
        except RuntimeError as exc:
            failed += 1
            print(f"ERROR enviando {label}: {exc}", file=sys.stderr)
            continue
        state[item["key"]] = now.astimezone(dt.timezone.utc).isoformat()
        sent += 1
        print(f"Enviado: {label}")

    if not dry_run:
        save_state(args.state, state)

    print(f"\nListo: {sent} enviados, {failed} fallidos.")
    return 1 if failed and not sent else 0


if __name__ == "__main__":
    sys.exit(main())
