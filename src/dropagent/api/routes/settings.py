"""
Settings routes (STUB).

Exposes a simple system-configuration object covering scoring weights and
automation flags. The state is held **in process memory** and is reset on
restart; this is intentionally a placeholder to be backed by a database /
config table later. It exists so the dashboard can read and update settings
against a stable contract.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/settings", tags=["settings"])


class ScoringWeights(BaseModel):
    """Relative weights used by the priority scorer."""

    margin: float = Field(default=0.4, ge=0.0, le=1.0)
    demand: float = Field(default=0.3, ge=0.0, le=1.0)
    risk: float = Field(default=0.2, ge=0.0, le=1.0)
    ops_cost: float = Field(default=0.1, ge=0.0, le=1.0)


class AutomationFlags(BaseModel):
    """Toggles controlling automated behaviour of the pipeline."""

    auto_approve: bool = False
    auto_register: bool = False
    auto_order: bool = False


class Settings(BaseModel):
    """System configuration: scoring weights plus automation flags."""

    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    automation_flags: AutomationFlags = Field(default_factory=AutomationFlags)


# In-memory stub store. NOTE: not persisted — replace with DB-backed storage.
_settings = Settings()


@router.get("/", response_model=Settings)
async def get_settings_endpoint() -> Settings:
    """Return the current (in-memory, stub) settings."""
    return _settings


@router.put("/", response_model=Settings)
async def update_settings_endpoint(new_settings: Settings) -> Settings:
    """
    Replace the current (in-memory, stub) settings.

    The whole settings object is overwritten. State does not survive a restart.
    """
    global _settings
    _settings = new_settings
    return _settings
