from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class IncidentCreate(BaseModel):
    service: str = Field(min_length=1)
    environment: str = "Production"
    symptoms: str = Field(min_length=1)
    logs: str = ""

    @field_validator("service", "symptoms")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class ResolveRequest(BaseModel):
    fix: str = Field(min_length=1)
    result: Literal["success", "failed"]
    engineer_feedback: str = ""
    # Optional. If omitted, minutes since the incident was reported are used.
    minutes_to_resolve: Optional[int] = Field(default=None, ge=1, le=100000)
