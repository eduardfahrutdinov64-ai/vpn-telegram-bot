"""Хранилище на SQLite: пользователи и платежи."""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class User:
    id: int
    username: str | None
    first_name: str | None
    created_at: datetime
    referrer_id: int | None
    trial_used: bool
    sub_until: datetime | None
    location: str | None
    vpn_key: str | None
    reminded_for: str | None
    blocked: bool

    @property
    def is_active(self) -> bool:
        return self.sub_until is not None and self.sub_until > utcnow()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    created_at    TEXT NOT NULL,
    referrer_id   INTEGER,
    trial_used    INTEGER NOT NULL DEFAULT 0,
    sub_until     TEXT,
    location      TEXT,
    vpn_key       TEXT,
    reminded_for  TEXT,
    blocked       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    tariff_id   TEXT NOT NULL,
    stars       INTEGER NOT NULL,
    charge_id   TEXT,
    demo        INTEGER NOT NULL DEFAULT 0,
    refunded    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _user(row: sqlite3.Row | None) -> User | None:
        if row is None:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            first_name=row["first_name"],
            created_at=_to_dt(row["created_at"]),
            referrer_id=row["referrer_id"],
            trial_used=bool(row["trial_used"]),
            sub_until=_to_dt(row["sub_until"]),
            location=row["location"],
            vpn_key=row["vpn_key"],
            reminded_for=row["reminded_for"],
            blocked=bool(row["blocked"]),
        )

    # ---------- пользователи ----------
    def get_user(self, user_id: int) -> User | None:
        with self._conn() as c:
            return self._user(c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def upsert_user(self, user_id: int, username: str | None, first_name: str | None,
                    referrer_id: int | None = None) -> tuple[User, bool]:
        """Создаёт пользователя или обновляет имя. Возвращает (пользователь, создан_ли)."""
        existing = self.get_user(user_id)
        with self._conn() as c:
            if existing:
                c.execute("UPDATE users SET username=?, first_name=?, blocked=0 WHERE id=?",
                          (username, first_name, user_id))
                created = False
            else:
                if referrer_id == user_id or (referrer_id and not self.get_user(referrer_id)):
                    referrer_id = None
                c.execute(
                    "INSERT INTO users (id, username, first_name, created_at, referrer_id) VALUES (?,?,?,?,?)",
                    (user_id, username, first_name, utcnow().isoformat(), referrer_id))
                created = True
        return self.get_user(user_id), created

    def update_user(self, user_id: int, **fields) -> None:
        if not fields:
            return
        values = []
        for value in fields.values():
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, bool):
                value = int(value)
            values.append(value)
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE users SET {cols} WHERE id=?", (*values, user_id))

    def all_user_ids(self) -> list[int]:
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT id FROM users WHERE blocked=0")]

    def users_expiring_between(self, start: datetime, end: datetime) -> list[User]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM users WHERE blocked=0 AND sub_until > ? AND sub_until <= ?",
                (start.isoformat(), end.isoformat())).fetchall()
        return [self._user(r) for r in rows]

    def count_referrals(self, user_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,)).fetchone()[0]

    # ---------- платежи ----------
    def add_payment(self, user_id: int, tariff_id: str, stars: int, charge_id: str | None, demo: bool) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO payments (user_id, tariff_id, stars, charge_id, demo, created_at) VALUES (?,?,?,?,?,?)",
                (user_id, tariff_id, stars, charge_id, int(demo), utcnow().isoformat()))

    def count_paid(self, user_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM payments WHERE user_id=? AND refunded=0",
                             (user_id,)).fetchone()[0]

    def get_payment_by_charge(self, charge_id: str) -> sqlite3.Row | None:
        with self._conn() as c:
            return c.execute("SELECT * FROM payments WHERE charge_id=?", (charge_id,)).fetchone()

    def mark_refunded(self, charge_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE payments SET refunded=1 WHERE charge_id=?", (charge_id,))

    # ---------- статистика ----------
    def stats(self) -> dict:
        now = utcnow().isoformat()
        with self._conn() as c:
            one = lambda q, *a: c.execute(q, a).fetchone()[0]  # noqa: E731
            return {
                "users": one("SELECT COUNT(*) FROM users"),
                "active": one("SELECT COUNT(*) FROM users WHERE sub_until > ?", now),
                "trials": one("SELECT COUNT(*) FROM users WHERE trial_used=1"),
                "payments": one("SELECT COUNT(*) FROM payments WHERE demo=0 AND refunded=0"),
                "stars": one("SELECT COALESCE(SUM(stars),0) FROM payments WHERE demo=0 AND refunded=0"),
                "demo_payments": one("SELECT COUNT(*) FROM payments WHERE demo=1"),
            }
