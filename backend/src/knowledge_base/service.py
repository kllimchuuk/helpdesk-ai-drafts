import re
from itertools import islice
from typing import Annotated

from fastapi import Depends
from pydantic import TypeAdapter

from config import Settings
from core.dependencies import get_settings
from knowledge_base.exceptions import KbArticleNotFoundError
from knowledge_base.models import KbArticle
from knowledge_base.repository import APOSTROPHES, KbRepository, get_kb_repository
from knowledge_base.schemas import (
    MAX_SLUG_LENGTH,
    SLUG_PATTERN,
    ArticleScore,
    KbMatch,
    ParsedArticle,
)

SCORES = TypeAdapter(list[ArticleScore])
MAX_WORDS = 100
MIN_WORD_LENGTH = 3
RESULT_LIMIT = 3
TRIGRAM_WEIGHT = 0.8
FTS_WEIGHT = 0.2
FTS_SCALE = 2.0
STRONG_SIMILARITY = 0.7
MIN_STRONG_WORDS = 3

STOP_WORDS = frozenset(
    """
    the and for you are not can how
    але або вже вам вас вони вона воно все всі дуже дякую для дня його
    ще змогу ласка мені мене можу можна можете мій моя моє нам нас нам
    при про така таке такий треба тому тільки хочу цей цього чи чому
    щоб що яка який яке які як від між над під після перед через
    будь добрий день вечір привіт вітаю доброго
    """.split()
)

APOSTROPHE_PATTERN = re.compile(f"[{re.escape(APOSTROPHES)}]")
WORD_PATTERN = re.compile(r"[^\W_]+")


def extract_words(text: str) -> list[str]:
    tokens = WORD_PATTERN.findall(APOSTROPHE_PATTERN.sub("", text.lower()))
    meaningful = filter(is_meaningful, tokens)
    return list(islice(dict.fromkeys(meaningful), MAX_WORDS))


def is_meaningful(word: str) -> bool:
    return len(word) >= MIN_WORD_LENGTH and word not in STOP_WORDS


class KbService:
    def __init__(self, repository: KbRepository, min_score: float) -> None:
        self._repository = repository
        self._min_score = min_score

    async def get_article(self, slug: str) -> KbArticle:
        if len(slug) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(slug):
            raise KbArticleNotFoundError()
        article = await self._repository.get_by_slug(slug)
        if article is None:
            raise KbArticleNotFoundError()
        return article

    async def search(self, query: str) -> list[KbMatch]:
        words = extract_words(query)
        if not words:
            return []
        rows = await self._repository.score_articles(words, STRONG_SIMILARITY)
        scored = SCORES.validate_python(rows, from_attributes=True)
        relevant = [item for item in scored if self._is_relevant(item)]
        matches = [self._to_match(item) for item in relevant]
        matches.sort(key=lambda match: match.score, reverse=True)
        return matches[:RESULT_LIMIT]

    async def find_articles(self, query: str) -> list[ParsedArticle]:
        articles = []
        for match in await self.search(query):
            article = await self._repository.get_by_slug(match.slug)
            if article is not None:
                articles.append(
                    ParsedArticle(
                        slug=article.slug, title=article.title, body=article.body
                    )
                )
        return articles

    def _is_relevant(self, item: ArticleScore) -> bool:
        return (
            self._score(item) >= self._min_score
            or item.strong_words >= MIN_STRONG_WORDS
        )

    def _to_match(self, item: ArticleScore) -> KbMatch:
        return KbMatch(slug=item.slug, title=item.title, score=self._score(item))

    @staticmethod
    def _score(item: ArticleScore) -> float:
        return TRIGRAM_WEIGHT * item.trigram_score + FTS_WEIGHT * min(
            1.0, item.fts_score * FTS_SCALE
        )


def get_kb_service(
    repository: Annotated[KbRepository, Depends(get_kb_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> KbService:
    return KbService(repository, min_score=settings.KB_MIN_SCORE)
