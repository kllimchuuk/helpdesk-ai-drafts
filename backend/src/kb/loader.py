import asyncio
import logging
import re
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from core.database import build_engine, build_session_factory
from kb.exceptions import ArticleFileError
from kb.repository import KbRepositoryImpl
from kb.schemas import ParsedArticle

logger = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONT_MATTER_KEYS = ("slug", "title")


def parse_article(text: str, source: str) -> ParsedArticle:
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
    if not SLUG_PATTERN.match(slug):
        raise ArticleFileError(
            f"{source}: slug {slug!r} must be lowercase words joined by hyphens"
        )
    if not title:
        raise ArticleFileError(f"{source}: the title is empty")
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
        article = parse_article(path.read_text(encoding="utf-8"), path.name)
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
