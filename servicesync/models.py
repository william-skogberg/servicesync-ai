"""The shared contracts for incoming requests and model-generated suggestions."""
from typing import Literal

from pydantic import BaseModel, Field

ServiceType = Literal[
    "home_cleaning", "deep_cleaning", "window_cleaning", "move_out_cleaning"
]

class NewInquiry(BaseModel):
    customer_name: str = Field(min_length=2, max_length=80)
    service_type: ServiceType
    postal_code: str = Field(pattern=r"^[0-9]{5}$")
    message: str = Field(min_length=10, max_length=1500)

class AIAnalysis(BaseModel):
    """Untrusted suggestions: never treat as an approved booking."""
    category: Literal[
        "home_cleaning", "deep_cleaning", "window_cleaning",
        "move_out_cleaning", "other"
    ]
    area_m2: int | None = Field(default=None, ge=1, le=10000)
    requested_date_text: str | None = Field(default=None, max_length=80)
    summary: str = Field(min_length=1, max_length=240)
    needs_review: bool

class CRMLead(BaseModel):
    source_id: str
    customer_name: str = Field(min_length=2, max_length=80)
    service_type: ServiceType
    postal_code: str = Field(pattern=r"^[0-9]{5}$")
    message: str = Field(min_length=10, max_length=1500)
    analysis_status: Literal["demo", "completed", "unavailable"]
    ai_analysis: AIAnalysis | None = None
