"""Explicit paper-only configuration. No environment credentials are consulted."""

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    mode: Literal["paper"] = "paper"
    live_enabled: Literal[False] = False
    ai_enabled: Literal[False] = False
    ai_daily_budget_usd: Literal["0.00"] = "0.00"
    monitored_symbols: list[str] = Field(default_factory=list, max_length=8)
    approved_symbols: list[str] = Field(default_factory=list, max_length=0)
    poll_seconds: int = Field(default=15, ge=10, le=300)
    request_timeout_seconds: int = Field(default=8, ge=1, le=15)
    stale_after_seconds: int = Field(default=45, ge=10, le=600)
    metadata_refresh_seconds: int = Field(default=300, ge=60, le=3600)
    depth_levels: Literal[5, 10, 20, 50, 100] = 20
    retained_observations: int = Field(default=2000, ge=10, le=10000)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if len(set(self.monitored_symbols)) != len(self.monitored_symbols):
            raise ValueError("Watchlist must contain unique symbols")
        if any(not re.fullmatch(r"[A-Z0-9]{3,24}", s) for s in self.monitored_symbols):
            raise ValueError("Invalid symbol in watchlist")
        if self.stale_after_seconds <= self.poll_seconds:
            raise ValueError("Freshness window must exceed the polling interval")
        return self

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def load_settings(path: Path) -> Settings:
    with path.open("rb") as stream:
        return Settings.model_validate(tomllib.load(stream))
