from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drafting.prompts import build_request
from drafting.schemas import Draft, DraftSource
from knowledge_base.repository import KbRepositoryImpl
from knowledge_base.schemas import ParsedArticle
from knowledge_base.service import KbService
from llm.client import LLMClient


class DraftingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LLMClient,
        *,
        min_score: float,
        public_base_url: str,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._min_score = min_score
        self._public_base_url = public_base_url.rstrip("/")

    async def draft(self, message: str) -> Draft:
        articles = await self._retrieve(message)
        result = await self._llm.complete(build_request(message, articles))
        sources = self._sources(result.cited_slugs, articles)
        return Draft(
            text=with_links(result.reply, sources),
            sources=sources,
            low_confidence=not articles,
            is_static=result.is_static,
        )

    async def _retrieve(self, message: str) -> list[ParsedArticle]:
        async with self._session_factory() as session:
            service = KbService(KbRepositoryImpl(session), min_score=self._min_score)
            return await service.find_articles(message)

    def _sources(
        self, cited_slugs: tuple[str, ...], articles: list[ParsedArticle]
    ) -> list[DraftSource]:
        cited = [article for article in articles if article.slug in set(cited_slugs)]
        return [
            DraftSource(
                slug=article.slug,
                title=article.title,
                url=f"{self._public_base_url}/kb/{article.slug}",
            )
            for article in cited or articles
        ]


def with_links(reply: str, sources: list[DraftSource]) -> str:
    if not sources:
        return reply
    links = "\n".join(f"{source.title}: {source.url}" for source in sources)
    return f"{reply.rstrip()}\n\n{links}"
