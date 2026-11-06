from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class ParsedArticle:
    slug: str
    title: str
    body: str


@dataclass(frozen=True)
class ArticleScore:
    slug: str
    title: str
    trigram_score: float
    fts_score: float


class KbMatch(BaseModel):
    slug: str
    title: str
    score: float


class ArticleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    body: str
