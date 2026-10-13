"""Pydantic models cho request (response search trả dict theo hợp đồng cố định, kiểm bằng test)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchContext(BaseModel):
    previous_text: str | None = None
    previous_product_ids: list[int] = Field(default_factory=list)
    previous_filters: dict | None = None


class SearchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=10)
    mode: Literal["fast", "auto", "accurate"] = "auto"
    context: SearchContext | None = None
    debug: bool = False


class FeedbackRequest(BaseModel):
    correct: bool
    correct_product_id: int | None = None
    add_to_eval: bool = False
    split: Literal["dev", "test"] = "dev"


class DemoCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str
    industry: str | None = None
    embed_model: str | None = None
    embed_dim: int = 768
    thresholds: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class DemoPatch(BaseModel):
    name: str | None = None
    industry: str | None = None
    thresholds: dict | None = None
    settings: dict | None = None


class EnumValue(BaseModel):
    value: str
    aliases: list[str] = Field(default_factory=list)


class AttributeDef(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    label: str
    type: Literal["text", "number", "enum", "multi_enum", "bool"] = "text"
    unit: str | None = None
    unit_aliases: list[str] = Field(default_factory=list)
    label_aliases: list[str] = Field(default_factory=list)
    enum_values: list[EnumValue] = Field(default_factory=list)
    filterable: bool = False
    searchable: bool = True
    weight: float = Field(default=0.5, ge=0, le=1)
    display_order: int = 0


class ProductIn(BaseModel):
    sku: str
    name: str
    category: str | None = None
    brand: str | None = None
    price: float | None = None
    price_unit: str | None = None
    in_stock: bool = True
    short_description: str | None = None
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    sample_questions: list[str] = Field(default_factory=list)
    enrichment_status: Literal["none", "ai_draft", "reviewed"] = "none"
    extra: dict = Field(default_factory=dict)


class ProductPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    brand: str | None = None
    price: float | None = None
    price_unit: str | None = None
    in_stock: bool | None = None
    short_description: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None
    aliases: list[str] | None = None
    use_cases: list[str] | None = None
    sample_questions: list[str] | None = None
    enrichment_status: Literal["none", "ai_draft", "reviewed"] | None = None


class EvalCaseIn(BaseModel):
    query: str
    context: SearchContext | None = None
    expected_product_ids: list[int] = Field(default_factory=list)
    expected_status: Literal["matched", "ambiguous", "no_match", "out_of_scope"]
    category: str | None = None
    split: Literal["dev", "test"] = "test"
    source: Literal["manual", "ai", "log"] = "manual"


class EnrichRequest(BaseModel):
    dry_run: bool = True
    overwrite_fields: list[Literal["aliases", "use_cases", "sample_questions"]] = Field(default_factory=list)
    product_ids: list[int] | None = None


class EnrichApply(BaseModel):
    accept_product_ids: list[int] | None = None
    edits: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    mark_reviewed: bool = False
    reembed: bool = True


class EvaluateRequest(BaseModel):
    split: Literal["dev", "test", "all"] = "test"
    mode: Literal["fast", "auto", "accurate"] = "auto"
    flags: dict[str, Any] = Field(default_factory=dict)
    concurrency: int = Field(default=4, ge=1, le=16)
    wait: bool = False


class GenerateEvalRequest(BaseModel):
    dry_run: bool = True
    per_product: int = Field(default=2, ge=1, le=6)
    extra_general: int = Field(default=20, ge=0, le=80)
