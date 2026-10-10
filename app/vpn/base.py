"""Интерфейс поставщика VPN-ключей.

Бот ничего не знает о том, как устроены серверы: он вызывает только эти методы.
Чтобы подключить настоящую панель (3x-ui, Marzban и т.д.), напишите свой класс
с этими методами и укажите его в app/vpn/__init__.py.
"""
from abc import ABC, abstractmethod
from datetime import datetime

from app.config import Location


class KeyProvider(ABC):
    @abstractmethod
    async def issue_key(self, user_id: int, location: Location, expires_at: datetime) -> str:
        """Создать (или продлить) доступ пользователя до expires_at и вернуть ссылку-ключ."""

    @abstractmethod
    async def revoke_key(self, user_id: int, location: Location) -> None:
        """Отключить доступ пользователя на сервере."""
