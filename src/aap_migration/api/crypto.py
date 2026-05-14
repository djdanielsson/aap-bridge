import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("AAP_BRIDGE_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "AAP_BRIDGE_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def reset_fernet() -> None:
    global _fernet
    _fernet = None


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        f = _get_fernet()
        return f.encrypt(value.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        f = _get_fernet()
        try:
            return f.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.warning("Failed to decrypt token; returning raw value (pre-migration data?)")
            return value
