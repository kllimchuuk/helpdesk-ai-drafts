import re
from typing import Annotated

from fastapi import Depends

from config import Settings
from core.dependencies import get_settings
from kb.exceptions import KbArticleNotFoundError
from kb.models import KbArticle
from kb.repository import KbRepository, get_kb_repository
from kb.schemas import KbMatch

MAX_WORDS = 40
MIN_WORD_LENGTH = 3
RESULT_LIMIT = 3
TRIGRAM_WEIGHT = 0.8
FTS_WEIGHT = 0.2
FTS_SCALE = 2.0

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

APOSTROPHE_PATTERN = re.compile("[’ʼ'`]")
WORD_PATTERN = re.compile(r"[^\W_]+")


def extract_words(text: str) -> list[str]:
    cleaned = APOSTROPHE_PATTERN.sub("", text.lower())
    words: list[str] = []
    for word in WORD_PATTERN.findall(cleaned):
        if len(word) < MIN_WORD_LENGTH or word in STOP_WORDS or word in words:
            continue
        words.append(word)
        if len(words) == MAX_WORDS:
            break
    return words


class KbService:
    def __init__(self, repository: KbRepository, min_score: float) -> None:
        self._repository = repository
        self._min_score = min_score

    async def get_article(self, slug: str) -> KbArticle:
        article = await self._repository.get_by_slug(slug)
        if article is None:
            raise KbArticleNotFoundError()
        return article

    async def search(self, query: str) -> list[KbMatch]:
        words = extract_words(query)
        if not words:
            return []
        scored = await self._repository.score_articles(words)
        matches = [
            KbMatch(
                slug=item.slug,
                title=item.title,
                score=TRIGRAM_WEIGHT * item.trigram_score
                + FTS_WEIGHT * min(1.0, item.fts_score * FTS_SCALE),
            )
            for item in scored
        ]
        relevant = [match for match in matches if match.score >= self._min_score]
        relevant.sort(key=lambda match: match.score, reverse=True)
        return relevant[:RESULT_LIMIT]


def get_kb_service(
    repository: Annotated[KbRepository, Depends(get_kb_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> KbService:
    return KbService(repository, min_score=settings.KB_MIN_SCORE)
