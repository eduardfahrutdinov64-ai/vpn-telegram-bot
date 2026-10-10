from app.vpn.base import KeyProvider
from app.vpn.mock import MockKeyProvider

# Здесь выбирается поставщик ключей. Для реального сервиса замените на свой класс.
provider: KeyProvider = MockKeyProvider()

__all__ = ["KeyProvider", "provider"]
