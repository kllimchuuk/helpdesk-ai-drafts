import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from core.database import build_engine, build_session_factory
from knowledge_base.exceptions import (
    ArticleBodyEmptyError,
    ArticleContainsNulError,
    ArticleDirectoryEmptyError,
    ArticleFileNameMismatchError,
    ArticleFrontMatterDuplicateKeyError,
    ArticleFrontMatterLineError,
    ArticleFrontMatterMissingError,
    ArticleFrontMatterUnclosedError,
    ArticleNotUtf8Error,
    ArticleSlugInvalidError,
    ArticleTitleInvalidError,
)
from knowledge_base.repository import KbRepositoryImpl
from knowledge_base.schemas import (
    MAX_SLUG_LENGTH,
    MAX_TITLE_LENGTH,
    SLUG_PATTERN,
    ParsedArticle,
)

logger = logging.getLogger(__name__)

FRONT_MATTER_KEYS = ("slug", "title")


def parse_article(text: str, source: str) -> ParsedArticle:
    if "\x00" in text:
        raise ArticleContainsNulError(source)
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ArticleFrontMatterMissingError(source)
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ArticleFrontMatterUnclosedError(source) from None

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or key not in FRONT_MATTER_KEYS:
            raise ArticleFrontMatterLineError(source, line)
        if key in meta:
            raise ArticleFrontMatterDuplicateKeyError(source, key)
        meta[key] = value.strip()

    slug = meta.get("slug", "")
    title = meta.get("title", "")
    if len(slug) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise ArticleSlugInvalidError(source, slug)
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise ArticleTitleInvalidError(source, MAX_TITLE_LENGTH)
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise ArticleBodyEmptyError(source)
    return ParsedArticle(slug=slug, title=title, body=body)


def read_directory(directory: Path) -> list[ParsedArticle]:
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise ArticleDirectoryEmptyError(str(directory))
    articles = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ArticleNotUtf8Error(path.name) from None
        article = parse_article(text, path.name)
        if path.stem != article.slug:
            raise ArticleFileNameMismatchError(path.name, article.slug)
        articles.append(article)
    return articles


async def sync_articles(
    session_factory: async_sessionmaker[AsyncSession], directory: Path
) -> int:
    articles = sorted(read_directory(directory), key=lambda article: article.slug)
    async with session_factory() as session:
        await KbRepositoryImpl(session).replace_all(articles)
    return len(articles)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    engine = build_engine(settings.DATABASE_URL)
    try:
        count = await sync_articles(
            build_session_factory(engine), Path(settings.KB_CONTENT_DIR)
        )
    finally:
        await engine.dispose()
    logger.info("Loaded %d knowledge-base articles", count)


if __name__ == "__main__":
    asyncio.run(main())
