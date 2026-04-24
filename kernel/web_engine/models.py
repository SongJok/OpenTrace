from __future__ import annotations

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""


class WebDocument(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    score: float = 0.0


class Citation(BaseModel):
    id: int
    title: str
    url: str
    snippet: str = ""


class WebContext(BaseModel):
    documents: list[WebDocument] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
