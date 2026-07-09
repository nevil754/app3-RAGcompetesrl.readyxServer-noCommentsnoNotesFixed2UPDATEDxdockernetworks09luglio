import pytest
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    generate_api_key,
    verify_api_key,
)

class TestPasswordHashing:
    def test_hash_is_different_from_plain(self):
        plain = "MySecurePass123!"
        hashed = hash_password(plain)
        assert hashed != plain

    def test_verify_correct_password(self):
        plain = "MySecurePass123!"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_same_password_different_hash(self):

        h1 = hash_password("password")
        h2 = hash_password("password")
        assert h1 != h2

class TestJWT:
    def test_create_and_decode_token(self):
        data = {
            "sub": "user-123",
            "tenant_id": "tenant-456",
            "tenant_slug": "acme",
            "role": "admin",
        }
        token = create_access_token(data)
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "tenant-456"
        assert payload["role"] == "admin"

    def test_invalid_token_returns_none(self):
        result = decode_access_token("invalid.token.here")
        assert result is None

    def test_expired_token(self):
        from datetime import timedelta
        data = {"sub": "user-123", "tenant_id": "t", "tenant_slug": "s", "role": "user"}

        token = create_access_token(data, expires_delta=timedelta(seconds=-1))
        result = decode_access_token(token)
        assert result is None

class TestAPIKey:
    def test_generate_and_verify(self):
        plain, key_hash = generate_api_key()
        assert plain.startswith("rag_")
        assert len(plain) > 10
        assert verify_api_key(plain, key_hash) is True

    def test_wrong_key_fails_verification(self):
        _, key_hash = generate_api_key()
        assert verify_api_key("wrong_key", key_hash) is False

    def test_keys_are_unique(self):
        key1, _ = generate_api_key()
        key2, _ = generate_api_key()
        assert key1 != key2

