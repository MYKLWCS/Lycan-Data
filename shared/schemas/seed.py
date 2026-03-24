from pydantic import BaseModel, field_validator
from shared.constants import SeedType


class SeedInput(BaseModel):
    """Input to start a new investigation web."""
    seed_type: SeedType
    seed_value: str
    web_name: str | None = None
    max_depth: int = 3
    notes: str | None = None

    @field_validator("seed_value")
    @classmethod
    def strip_value(cls, v: str) -> str:
        return v.strip()

    @field_validator("max_depth")
    @classmethod
    def clamp_depth(cls, v: int) -> int:
        return max(1, min(v, 10))
