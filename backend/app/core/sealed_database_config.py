import base64
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


SEALED_DB_CONTEXT = b"TENNET:sealed-database-url:v1"
SEALED_DATABASE_EPHEMERAL_PUBLIC_KEY = "GkYurwaI-nIo7kPcq1Ttuvh7GkCT7Z6L5A5-_bk5Yi0="
SEALED_DATABASE_NONCE = "O4qyUZ6svGoWTjBw"
SEALED_DATABASE_CIPHERTEXT = "cGeLErXDmSYOpp8qfGeFsZpLlaKFg1yahotgE6GRXN0kjBqAqgOfwPRc6kEZdUN2IEyydHQ1U1x6wUs9dX6jadipAX6fOccoYfce_nTkuUydB1_O8BZw1j_cogl1LE3b6VFBQuzGtskpGnbKc_T_M5Q7oLchBkLWmj_iPT7gJP-NV9KXUnrcqYjaA270LTOko-wDEJdOLI1WdPs0FWTyMZAux_j670-J"


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


def decrypt_sealed_database_url(secret_key: str) -> str:
    private_key = _derive_private_key(secret_key)
    ephemeral_public_key = X25519PublicKey.from_public_bytes(
        base64.urlsafe_b64decode(SEALED_DATABASE_EPHEMERAL_PUBLIC_KEY)
    )
    shared_secret = private_key.exchange(ephemeral_public_key)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=SEALED_DB_CONTEXT,
    ).derive(shared_secret)
    plaintext = AESGCM(key).decrypt(
        base64.urlsafe_b64decode(SEALED_DATABASE_NONCE),
        base64.urlsafe_b64decode(SEALED_DATABASE_CIPHERTEXT),
        SEALED_DB_CONTEXT,
    )
    return plaintext.decode("utf-8")
