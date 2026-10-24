import datetime as dt
import json
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

import reminders as r

TZ = ZoneInfo("America/Costa_Rica")


def rem(**overrides):
    base = {"id": "test", "text": "algo", "type": "weekly",
            "days": ["mon"], "time": "18:00", "active": True}
    base.update(overrides)
    return base


class TestExpansion(unittest.TestCase):
    def test_weekly_matches_day(self):
        # 2026-10-26 es lunes
        monday = dt.date(2026, 10, 26)
        got = r.occurrences_on(rem(), monday, TZ)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].strftime("%Y-%m-%d %H:%M"), "2026-10-26 18:00")

    def test_weekly_ignores_other_days(self):
        tuesday = dt.date(2026, 10, 27)
        self.assertEqual(r.occurrences_on(rem(), tuesday, TZ), [])

    def test_daily(self):
        item = rem(type="daily", days=None)
        got = r.occurrences_on(item, dt.date(2026, 10, 27), TZ)
        self.assertEqual(len(got), 1)

    def test_monthly_fixed_day(self):
        item = rem(type="monthly", day=15, days=None)
        self.assertEqual(len(r.occurrences_on(item, dt.date(2026, 10, 15), TZ)), 1)
        self.assertEqual(r.occurrences_on(item, dt.date(2026, 10, 14), TZ), [])

    def test_monthly_last_day(self):
        item = rem(type="monthly", day=-1, days=None)
        # febrero 2028 tiene 29 días (bisiesto)
        self.assertEqual(len(r.occurrences_on(item, dt.date(2028, 2, 29), TZ)), 1)
        self.assertEqual(r.occurrences_on(item, dt.date(2028, 2, 28), TZ), [])

    def test_once(self):
        item = rem(type="once", date="2026-11-10", days=None)
        self.assertEqual(len(r.occurrences_on(item, dt.date(2026, 11, 10), TZ)), 1)
        self.assertEqual(r.occurrences_on(item, dt.date(2026, 11, 11), TZ), [])


class TestDueWindow(unittest.TestCase):
    def at(self, text):
        return dt.datetime.fromisoformat(text).replace(tzinfo=TZ)

    def test_due_exactly_now(self):
        items = r.due_until([rem()], self.at("2026-10-26T18:00"))
        self.assertEqual(len(items), 1)

    def test_not_due_before(self):
        self.assertEqual(r.due_until([rem()], self.at("2026-10-26T17:59")), [])

    def test_within_late_window(self):
        items = r.due_until([rem()], self.at("2026-10-26T18:30"))
        self.assertEqual(len(items), 1)

    def test_outside_late_window(self):
        self.assertEqual(r.due_until([rem()], self.at("2026-10-26T19:00")), [])

    def test_lead_minutes_advances(self):
        item = rem(lead_minutes=30)
        self.assertEqual(r.due_until([item], self.at("2026-10-26T17:29")), [])
        self.assertEqual(len(r.due_until([item], self.at("2026-10-26T17:30"))), 1)

    def test_lead_reminder_not_sent_after_event_starts(self):
        item = rem(lead_minutes=30)
        self.assertEqual(r.due_until([item], self.at("2026-10-26T18:01")), [])

    def test_inactive_ignored(self):
        schedule = {"reminders": [rem(active=False)]}
        self.assertEqual(r.due_until(r.active_reminders(schedule),
                                     self.at("2026-10-26T18:00")), [])

    def test_previous_day_late_event(self):
        # evento ayer 23:50 sin aviso previo: a las 00:30 de hoy sigue siendo útil
        item = rem(type="once", date="2026-10-25", time="23:50", days=None)
        items = r.due_until([item], self.at("2026-10-26T00:30"), window_minutes=120)
        self.assertEqual(len(items), 1)


class TestState(unittest.TestCase):
    def test_dedupe_by_key(self):
        item = rem()
        now = dt.datetime(2026, 10, 26, 18, 0, tzinfo=TZ)
        first = r.due_until([item], now)
        key = first[0]["key"]
        state = {key: now.astimezone(dt.timezone.utc).isoformat()}
        pending = [x for x in r.due_until([item], now) if x["key"] not in state]
        self.assertEqual(pending, [])

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            state = {"a|2026-10-26T18:00": dt.datetime.now(dt.timezone.utc).isoformat()}
            r.save_state(path, state)
            self.assertEqual(r.load_state(path), state)

    def test_old_state_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)).isoformat()
            r.save_state(path, {"viejo|x": old})
            self.assertEqual(r.load_state(path), {})


class TestValidation(unittest.TestCase):
    def write(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8")
        json.dump(payload, handle, ensure_ascii=False)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_valid_schedule(self):
        path = self.write({"reminders": [rem()]})
        schedule = r.load_schedule(path)
        self.assertEqual(len(schedule["reminders"]), 1)

    def test_bad_time(self):
        path = self.write({"reminders": [rem(time="25:00")]})
        with self.assertRaises(r.ScheduleError):
            r.load_schedule(path)

    def test_duplicate_id(self):
        path = self.write({"reminders": [rem(), rem()]})
        with self.assertRaises(r.ScheduleError):
            r.load_schedule(path)

    def test_bad_day(self):
        path = self.write({"reminders": [rem(days=["lunes"])]})
        with self.assertRaises(r.ScheduleError):
            r.load_schedule(path)

    def test_bad_type(self):
        path = self.write({"reminders": [rem(type="semanal")]})
        with self.assertRaises(r.ScheduleError):
            r.load_schedule(path)


class TestMessage(unittest.TestCase):
    def test_format_contains_text_and_time(self):
        item = rem()
        now = dt.datetime(2026, 10, 26, 18, 0, tzinfo=TZ)
        msg = r.format_message(r.due_until([item], now)[0], now)
        self.assertIn("algo", msg)
        self.assertIn("lun 26 oct 18:00", msg)
        self.assertNotIn("retrasado", msg)

    def test_format_flags_late(self):
        item = rem()
        now = dt.datetime(2026, 10, 26, 18, 40, tzinfo=TZ)
        msg = r.format_message(r.due_until([item], now)[0], now)
        self.assertIn("retrasado", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
