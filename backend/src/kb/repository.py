from abc import ABC, abstractmethod
from typing import Annotated

from fastapi import Depends
from sqlalchemy import ARRAY, Text, bindparam, delete, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, translate_unavailable
from kb.models import KbArticle
from kb.schemas import ArticleScore, ParsedArticle

APOSTROPHES = "’ʼ'`"

SCORE_QUERY = text(
    """
    WITH words AS (SELECT unnest(CAST(:words AS text[])) AS word),
    normalised AS (
        SELECT slug, title, tsv,
               lower(translate(title, :apostrophes, '')) AS norm_title,
               lower(translate(title || ' ' || body, :apostrophes, '')) AS norm_text
        FROM kb_articles
    )
    SELECT n.slug, n.title,
           (SELECT coalesce(avg(greatest(
                       word_similarity(w.word, n.norm_title),
                       word_similarity(w.word, n.norm_text))), 0)
              FROM words w) AS trigram_score,
           ts_rank(n.tsv, to_tsquery('simple', :tsquery), 32) AS fts_score
    FROM normalised n
    """
).bindparams(bindparam("words", type_=ARRAY(Text)))


class KbRepository(ABC):
    @abstractmethod
    async def get_by_slug(self, slug: str) -> KbArticle | None:
        raise NotImplementedError()

    @abstractmethod
    async def score_articles(self, words: list[str]) -> list[ArticleScore]:
        raise NotImplementedError()

    @abstractmethod
    async def replace_all(self, articles: list[ParsedArticle]) -> None:
        raise NotImplementedError()


class KbRepositoryImpl(KbRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @translate_unavailable
    async def get_by_slug(self, slug: str) -> KbArticle | None:
        return await self._session.get(KbArticle, slug)

    @translate_unavailable
    async def score_articles(self, words: list[str]) -> list[ArticleScore]:
        rows = await self._session.execute(
            SCORE_QUERY,
            {
                "words": words,
                "tsquery": " | ".join(words),
                "apostrophes": APOSTROPHES,
            },
        )
        return [
            ArticleScore(
                slug=row.slug,
                title=row.title,
                trigram_score=float(row.trigram_score),
                fts_score=float(row.fts_score),
            )
            for row in rows
        ]

    @translate_unavailable
    async def replace_all(self, articles: list[ParsedArticle]) -> None:
        ordered = sorted(articles, key=lambda article: article.slug)
        statement = insert(KbArticle).values(
            [
                {"slug": item.slug, "title": item.title, "body": item.body}
                for item in ordered
            ]
        )
        # One statement in slug order: containers syncing together take row locks
        # in the same order and cannot deadlock.
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[KbArticle.slug],
                set_={
                    "title": statement.excluded.title,
                    "body": statement.excluded.body,
                },
            )
        )
        await self._session.execute(
            delete(KbArticle).where(
                KbArticle.slug.not_in([item.slug for item in ordered])
            )
        )
        await self._session.commit()


def get_kb_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> KbRepository:
    return KbRepositoryImpl(session)
