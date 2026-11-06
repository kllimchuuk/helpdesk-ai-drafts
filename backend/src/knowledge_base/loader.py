import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from core.database import build_engine, build_session_factory
from knowledge_base.exceptions import ArticleFileError
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
        raise ArticleFileError(f"{source}: NUL characters are not allowed")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ArticleFileError(f"{source}: the file must start with front matter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ArticleFileError(f"{source}: the front matter is not closed") from None

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or key not in FRONT_MATTER_KEYS:
            raise ArticleFileError(f"{source}: unexpected front matter line {line!r}")
        if key in meta:
            raise ArticleFileError(f"{source}: {key!r} is given twice")
        meta[key] = value.strip()

    slug = meta.get("slug", "")
    title = meta.get("title", "")
    if len(slug) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise ArticleFileError(
            f"{source}: slug {slug!r} must be lowercase words joined by hyphens"
        )
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise ArticleFileError(
            f"{source}: the title must be 1-{MAX_TITLE_LENGTH} characters"
        )
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise ArticleFileError(f"{source}: the article has no text")
    return ParsedArticle(slug=slug, title=title, body=body)


def read_directory(directory: Path) -> list[ParsedArticle]:
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise ArticleFileError(f"{directory}: no articles found")
    articles = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ArticleFileError(
                f"{path.name}: the file is not valid UTF-8"
            ) from None
        article = parse_article(text, path.name)
        if path.stem != article.slug:
            raise ArticleFileError(
                f"{path.name}: the file name must be {article.slug}.md"
            )
        articles.append(article)
    return articles


async def sync_articles(
    session_factory: async_sessionmaker[AsyncSession], directory: Path
) -> int:
    articles = read_directory(directory)
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
