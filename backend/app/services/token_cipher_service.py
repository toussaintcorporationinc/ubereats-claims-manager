import base64
import hashlib
import hmac
import os

from app.core.config import get_settings

TOKEN_CIPHER_VERSION = "v1"


class TokenCipherError(Exception):
    pass


class TokenCipherService:
    """Isolated reversible token protection for V1.

    This keeps plaintext tokens out of the database and response layer while leaving
    the implementation replaceable by KMS/Fernet without touching callers.
    """

    def encrypt(self, token: str | None) -> str | None:
        if token is None:
            return None
        token_bytes = token.encode("utf-8")
        nonce = os.urandom(16)
        key = self._key()
        cipher_bytes = self._xor(token_bytes, self._keystream(key, nonce, len(token_bytes)))
        tag = hmac.new(key, nonce + cipher_bytes, hashlib.sha256).digest()[:16]
        payload = base64.urlsafe_b64encode(nonce + tag + cipher_bytes).decode("ascii")
        return f"{TOKEN_CIPHER_VERSION}.{payload}"

    def decrypt(self, encrypted_token: str | None) -> str | None:
        if encrypted_token is None:
            return None
        try:
            version, payload = encrypted_token.split(".", 1)
            if version != TOKEN_CIPHER_VERSION:
                raise TokenCipherError("Unsupported token cipher version")
            raw = base64.urlsafe_b64decode(payload.encode("ascii"))
            nonce = raw[:16]
            tag = raw[16:32]
            cipher_bytes = raw[32:]
        except (ValueError, TypeError) as exc:
            raise TokenCipherError("Invalid encrypted token") from exc

        key = self._key()
        expected_tag = hmac.new(key, nonce + cipher_bytes, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected_tag):
            raise TokenCipherError("Encrypted token integrity check failed")
        token_bytes = self._xor(cipher_bytes, self._keystream(key, nonce, len(cipher_bytes)))
        return token_bytes.decode("utf-8")

    def _key(self) -> bytes:
        return hashlib.sha256(f"{get_settings().jwt_secret_key}:token-cipher:v1".encode("utf-8")).digest()

    def _keystream(self, key: bytes, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(output[:length])

    def _xor(self, left: bytes, right: bytes) -> bytes:
        return bytes(left_byte ^ right_byte for left_byte, right_byte in zip(left, right))
