import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


SEALED_DB_CONTEXT = b"TENNET:sealed-database-url:v1"


def _derive_private_key(secret_key: str) -> X25519PrivateKey:
    seed = hashlib.sha256(
        f"{secret_key}:sealed-database-url:x25519:v1".encode("utf-8")
    ).digest()
    return X25519PrivateKey.from_private_bytes(seed)


def sealed_database_public_key(secret_key: str) -> str:
    public_bytes = _derive_private_key(secret_key).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(public_bytes).decode("ascii")
