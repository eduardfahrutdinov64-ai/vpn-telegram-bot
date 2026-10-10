"""Тарифы. Цены в Telegram Stars (⭐). Меняйте под себя."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Tariff:
    id: str
    title: str
    days: int
    stars: int
    badge: str = ""

    @property
    def button_text(self) -> str:
        badge = f" · {self.badge}" if self.badge else ""
        return f"{self.title} — {self.stars} ⭐{badge}"


TARIFFS: list[Tariff] = [
    Tariff("m1", "1 месяц", 30, 100),
    Tariff("m3", "3 месяца", 90, 270, "−10%"),
    Tariff("m6", "6 месяцев", 180, 500, "−17%"),
    Tariff("m12", "12 месяцев", 365, 900, "−25%"),
]


def get_tariff(tariff_id: str) -> Tariff | None:
    return next((t for t in TARIFFS if t.id == tariff_id), None)
