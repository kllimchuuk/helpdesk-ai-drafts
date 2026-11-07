from pydantic import BaseModel


class DraftSource(BaseModel):
    slug: str
    title: str
    url: str


class Draft(BaseModel):
    text: str
    sources: list[DraftSource]
    low_confidence: bool
    is_static: bool
