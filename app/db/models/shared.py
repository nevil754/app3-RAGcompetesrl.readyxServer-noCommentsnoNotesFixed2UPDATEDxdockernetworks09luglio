from __future__ import annotations
from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = {"schema": "shared"}
    id: Mapped[str] = mapped_column(UNIQUEIDENTIFIER, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="starter")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_docs: Mapped[int] = mapped_column(Integer, default=500)
    max_users: Mapped[int] = mapped_column(Integer, default=10)
    max_tokens_day: Mapped[int] = mapped_column(BigInteger, default=100_000)
    settings: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "shared"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UNIQUEIDENTIFIER, nullable=False)
    user_id: Mapped[str | None] = mapped_column(UNIQUEIDENTIFIER)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    metadata: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)

class UsageStat(Base):
    __tablename__ = "usage_stats"
    __table_args__ = {"schema": "shared"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UNIQUEIDENTIFIER, nullable=False)
    stat_date: Mapped[datetime] = mapped_column(DateTime)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    queries_count: Mapped[int] = mapped_column(Integer, default=0)
    docs_ingested: Mapped[int] = mapped_column(Integer, default=0)

class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = {"schema": "shared"}
    id: Mapped[str] = mapped_column(UNIQUEIDENTIFIER, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UNIQUEIDENTIFIER, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[str] = mapped_column(String(500), default="read,write")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)

