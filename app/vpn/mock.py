"""Демо-поставщик ключей: генерирует правдоподобную ссылку VLESS без реального сервера."""
import uuid
from datetime import datetime
from urllib.parse import quote

from app.config import Location, config
from app.vpn.base import KeyProvider

_NAMESPACE = uuid.UUID("6f1c2a8e-3b4d-4e5f-9a0b-1c2d3e4f5a6b")


class MockKeyProvider(KeyProvider):
    async def issue_key(self, user_id: int, location: Location, expires_at: datetime) -> str:
        # Один и тот же пользователь и локация -> один и тот же ключ (при продлении ключ не меняется)
        client_id = uuid.uuid5(_NAMESPACE, f"{user_id}:{location.code}")
        name = quote(f"{config.service_name} {location.title}")
        return (
            f"vless://{client_id}@{location.host}:443"
            "?type=tcp&security=reality&pbk=DEMO_PUBLIC_KEY&fp=chrome"
            "&sni=www.microsoft.com&sid=0a1b2c3d&flow=xtls-rprx-vision"
            f"#{name}"
        )

    async def revoke_key(self, user_id: int, location: Location) -> None:
        return None
