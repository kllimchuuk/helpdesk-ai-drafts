import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_SLUG_LENGTH = 100
MAX_TITLE_LENGTH = 255


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
    strong_words: int


class KbMatch(BaseModel):
    slug: str
    title: str
    score: float


class ArticleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    body: str
