from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, StrictBool, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    language: Literal["ru", "kk", "en"] = "ru"


class SearchRequest(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(default="", max_length=2000)
    filters: dict[str, Any] | None = None
    limit: int = Field(default=5, ge=1, le=20, strict=True)
    include_uncertain: StrictBool = False


class ProposalRequest(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=1000, strict=True)

    @field_validator("product_id", mode="before")
    @classmethod
    def stringify_id(cls, value):
        if type(value) is int:
            return str(value)
        return value


class ConfirmRequest(BaseModel):
    model_config = {"extra": "forbid"}
    confirm: StrictBool


class Proposal(BaseModel):
    proposal_id: str
    product_id: str
    quantity: int
    expires_at: datetime
    product: dict[str, Any]


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    products: list[dict[str, Any]]
    pending_action: Proposal | None = None
