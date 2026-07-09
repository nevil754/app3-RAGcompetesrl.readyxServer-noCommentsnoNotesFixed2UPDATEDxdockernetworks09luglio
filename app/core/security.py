from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from loguru import logger
from passlib.context import CryptContext
from app.core.settings import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)

def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.now(timezone.utc)
    token = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token

def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        logger.debug(f"JWT decode fallito: {e}")
        return None

def extract_tenant_from_token(token: str) -> tuple[str, str] | None:
    payload = decode_access_token(token)
    if not payload:
        return None
    tenant_id = payload.get("tenant_id")
    tenant_slug = payload.get("tenant_slug")
    if not tenant_id or not tenant_slug:
        logger.warning("Token JWT senza tenant_id o tenant_slug")
        return None
    return tenant_id, tenant_slug

def generate_api_key(length: int | None = None) -> tuple[str, str]:
    key_length = length or settings.api_key_length
    api_key = f"rag_{secrets.token_urlsafe(key_length)}"
    key_hash = hash_api_key(api_key)
    return api_key, key_hash

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()

def verify_api_key(plain_key: str, stored_hash: str) -> bool:
    return secrets.compare_digest( hash_api_key(plain_key), stored_hash )

def extract_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    parts = authorization_header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]

