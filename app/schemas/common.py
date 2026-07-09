from __future__ import annotations
from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, Field

T = TypeVar("T")

class PaginatedResponse( BaseModel, Generic[T] ):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool
    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int):
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )

class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str | None = None

class SuccessResponse(BaseModel):
    message: str
    data: dict[str, Any] | None = None
