"""Тесты бизнес-логики (без Telegram). Запуск: python -m unittest discover tests"""
import asyncio
import os
import tempfile
import unittest
from datetime import timedelta

os.environ.setdefault("TRIAL_DAYS", "3")
os.environ.setdefault("REFERRAL_BONUS_DAYS", "7")

from app.db import Database, utcnow  # noqa: E402
from app.services import SubscriptionService  # noqa: E402
from app.tariffs import get_tariff  # noqa: E402
from app.vpn.mock import MockKeyProvider  # noqa: E402
from app import texts  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        self.s = SubscriptionService(Database(self.path), MockKeyProvider())

    def tearDown(self):
        os.remove(self.path)

    def test_register_and_referral_link(self):
        self.s.register(1, "alice", "Alice")
        u, created = self.s.register(2, "bob", "Bob", "ref_1")
        self.assertTrue(created)
        self.assertEqual(u.referrer_id, 1)
        # повторный /start не меняет реферера и не создаёт пользователя заново
        u, created = self.s.register(2, "bob", "Bob", "ref_999")
        self.assertFalse(created)
        self.assertEqual(u.referrer_id, 1)

    def test_self_and_unknown_referrer_ignored(self):
        u, _ = self.s.register(5, None, None, "ref_5")
        self.assertIsNone(u.referrer_id)
        u, _ = self.s.register(6, None, None, "ref_12345")
        self.assertIsNone(u.referrer_id)
        u, _ = self.s.register(7, None, None, "ref_abc")
        self.assertIsNone(u.referrer_id)

    def test_trial_once(self):
        self.s.register(1, None, "A")
        u = run(self.s.start_trial(1))
        self.assertTrue(u.is_active)
        self.assertTrue(u.vpn_key.startswith("vless://"))
        self.assertAlmostEqual((u.sub_until - utcnow()).total_seconds(), 3 * 86400, delta=5)
        self.assertIsNone(run(self.s.start_trial(1)))

    def test_payment_extends_from_current_end(self):
        self.s.register(1, None, "A")
        run(self.s.start_trial(1))
        before = self.s.db.get_user(1).sub_until
        res = run(self.s.apply_payment(1, get_tariff("m1"), "ch_1", demo=False))
        self.assertEqual(res.user.sub_until, before + timedelta(days=30))
        self.assertIsNone(res.referrer)

    def test_payment_after_expiry_starts_now(self):
        self.s.register(1, None, "A")
        self.s.db.update_user(1, sub_until=utcnow() - timedelta(days=10))
        res = run(self.s.apply_payment(1, get_tariff("m3"), "ch_1", demo=True))
        self.assertAlmostEqual((res.user.sub_until - utcnow()).total_seconds(), 90 * 86400, delta=5)

    def test_referral_bonus_only_on_first_payment(self):
        self.s.register(1, None, "A")
        self.s.register(2, None, "B", "ref_1")
        r1 = run(self.s.apply_payment(2, get_tariff("m1"), "ch_1", demo=False))
        self.assertIsNotNone(r1.referrer)
        self.assertAlmostEqual((r1.referrer.sub_until - utcnow()).total_seconds(), 7 * 86400, delta=5)
        r2 = run(self.s.apply_payment(2, get_tariff("m1"), "ch_2", demo=False))
        self.assertIsNone(r2.referrer)

    def test_key_stable_on_extend_and_changes_with_location(self):
        self.s.register(1, None, "A")
        k1 = run(self.s.apply_payment(1, get_tariff("m1"), "c1", True)).user.vpn_key
        k2 = run(self.s.apply_payment(1, get_tariff("m1"), "c2", True)).user.vpn_key
        self.assertEqual(k1, k2)
        u = run(self.s.change_location(1, "de"))
        self.assertEqual(u.location, "de")
        self.assertNotEqual(u.vpn_key, k1)
        self.assertIn("de.example-vpn.com", u.vpn_key)

    def test_refund_removes_days_once(self):
        self.s.register(1, None, "A")
        run(self.s.apply_payment(1, get_tariff("m1"), "ch_1", demo=False))
        u = run(self.s.refund("ch_1"))
        self.assertFalse(u.is_active)
        self.assertIsNone(run(self.s.refund("ch_1")))
        self.assertEqual(self.s.db.stats()["stars"], 0)

    def test_reminders(self):
        self.s.register(1, None, "A")
        self.s.register(2, None, "B")
        self.s.db.update_user(1, sub_until=utcnow() + timedelta(hours=5))
        self.s.db.update_user(2, sub_until=utcnow() + timedelta(days=5))
        due = self.s.due_reminders()
        self.assertEqual([u.id for u in due], [1])
        self.s.mark_reminded(due[0])
        self.assertEqual(self.s.due_reminders(), [])
        # после продления напоминание снова возможно для нового срока
        run(self.s.extend(1, 0))
        self.assertEqual(len(self.s.due_reminders()), 1)

    def test_stats_and_texts(self):
        self.s.register(1, None, "A")
        run(self.s.apply_payment(1, get_tariff("m6"), "c1", demo=False))
        run(self.s.apply_payment(1, get_tariff("m1"), None, demo=True))
        st = self.s.db.stats()
        self.assertEqual((st["payments"], st["stars"], st["demo_payments"], st["active"]), (1, 500, 1, 1))
        u = self.s.db.get_user(1)
        for t in (texts.profile(u, 0), texts.key_message(u), texts.welcome("<Иван>"), texts.tariffs_text()):
            self.assertIsInstance(t, str)
        self.assertIn("&lt;Иван&gt;", texts.welcome("<Иван>"))
        self.assertEqual(texts.days_left(u.sub_until), 210)


if __name__ == "__main__":
    unittest.main()
