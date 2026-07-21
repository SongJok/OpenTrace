from __future__ import annotations

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    required_connectors: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    signature: str = ""
    public_key_id: str = "default"
