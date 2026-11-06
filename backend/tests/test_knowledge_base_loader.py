import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowledge_base.exceptions import (
    ArticleBodyEmptyError,
    ArticleContainsNulError,
    ArticleDirectoryEmptyError,
    ArticleFileError,
    ArticleFileNameMismatchError,
    ArticleFrontMatterDuplicateKeyError,
    ArticleFrontMatterLineError,
    ArticleFrontMatterMissingError,
    ArticleFrontMatterUnclosedError,
    ArticleNotUtf8Error,
    ArticleSlugInvalidError,
    ArticleTitleInvalidError,
)
from knowledge_base.loader import parse_article, read_directory, sync_articles
from knowledge_base.models import KbArticle
from tests.helpers import KB_DIRECTORY

VALID = (
    "---\nslug: reset-password\ntitle: Відновлення пароля\n---\n\n"
    "Кроки.\n\nДруга частина.\n"
)


def write(directory: Path, slug: str, text: str) -> None:
    (directory / f"{slug}.md").write_text(text)


async def stored(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, str]:
    async with session_factory() as session:
        rows = await session.execute(select(KbArticle.slug, KbArticle.title))
        return dict(rows.all())


def test_a_valid_article_is_parsed() -> None:
    article = parse_article(VALID, "reset-password.md")

    assert article.slug == "reset-password"
    assert article.title == "Відновлення пароля"
    assert article.body == "Кроки.\n\nДруга частина."


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("no front matter at all", ArticleFrontMatterMissingError),
        ("---\ntitle: Only a title\n---\nBody", ArticleSlugInvalidError),
        ("---\nslug: only-a-slug\n---\nBody", ArticleTitleInvalidError),
        ("---\nslug: a\ntitle: T\n", ArticleFrontMatterUnclosedError),
        ("---\nslug: a\ntitle: T\n---\n   \n", ArticleBodyEmptyError),
        ("---\nslug: Not Valid\ntitle: T\n---\nBody", ArticleSlugInvalidError),
        ("---\nslug: UPPER\ntitle: T\n---\nBody", ArticleSlugInvalidError),
        (
            "---\nslug: a\ntitle: T\nextra: nope\n---\nBody",
            ArticleFrontMatterLineError,
        ),
        (
            "---\nslug: a\nslug: b\ntitle: T\n---\nBody",
            ArticleFrontMatterDuplicateKeyError,
        ),
        ("---\nslug: a\ntitle:\n---\nBody", ArticleTitleInvalidError),
    ],
)
def test_a_broken_article_is_rejected(text: str, error: type[ArticleFileError]) -> None:
    with pytest.raises(error):
        parse_article(text, "a.md")


def test_the_file_name_must_match_the_slug(tmp_path: Path) -> None:
    write(tmp_path, "other-name", VALID)

    with pytest.raises(ArticleFileNameMismatchError):
        read_directory(tmp_path)


def test_the_real_content_directory_is_valid_and_short() -> None:
    articles = read_directory(KB_DIRECTORY)

    assert 5 <= len(articles) <= 10
    assert len({article.slug for article in articles}) == len(articles)
    for article in articles:
        assert 60 <= len(article.body.split()) <= 300, article.slug


async def test_sync_stores_the_articles(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    write(tmp_path, "reset-password", VALID)

    count = await sync_articles(session_factory, tmp_path)

    assert count == 1
    assert await stored(session_factory) == {"reset-password": "Відновлення пароля"}


async def test_sync_twice_changes_nothing_and_picks_up_edits(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    write(tmp_path, "reset-password", VALID)
    await sync_articles(session_factory, tmp_path)

    await sync_articles(session_factory, tmp_path)
    write(
        tmp_path,
        "reset-password",
        VALID.replace("Відновлення пароля", "Новий заголовок"),
    )
    await sync_articles(session_factory, tmp_path)

    assert await stored(session_factory) == {"reset-password": "Новий заголовок"}


async def test_sync_removes_articles_whose_file_is_gone(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    write(tmp_path, "reset-password", VALID)
    write(tmp_path, "other", VALID.replace("reset-password", "other"))
    await sync_articles(session_factory, tmp_path)

    (tmp_path / "other.md").unlink()
    await sync_articles(session_factory, tmp_path)

    assert set(await stored(session_factory)) == {"reset-password"}


async def test_an_invalid_file_leaves_the_stored_articles_untouched(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    write(tmp_path, "reset-password", VALID)
    await sync_articles(session_factory, tmp_path)
    write(tmp_path, "broken", "no front matter")

    with pytest.raises(ArticleFrontMatterMissingError):
        await sync_articles(session_factory, tmp_path)

    assert set(await stored(session_factory)) == {"reset-password"}


async def test_containers_syncing_at_the_same_time_do_not_clash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await asyncio.gather(
        *(sync_articles(session_factory, KB_DIRECTORY) for _ in range(6))
    )

    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(KbArticle))
    assert total == len(read_directory(KB_DIRECTORY))


async def test_an_empty_directory_is_refused_and_keeps_the_stored_articles(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    write(tmp_path, "reset-password", VALID)
    await sync_articles(session_factory, tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ArticleDirectoryEmptyError):
        await sync_articles(session_factory, empty)

    assert set(await stored(session_factory)) == {"reset-password"}


async def test_a_missing_directory_is_refused_and_keeps_the_stored_articles(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    write(tmp_path, "reset-password", VALID)
    await sync_articles(session_factory, tmp_path)

    with pytest.raises(ArticleDirectoryEmptyError):
        await sync_articles(session_factory, tmp_path / "does-not-exist")

    assert set(await stored(session_factory)) == {"reset-password"}


def test_a_slug_that_is_too_long_is_rejected() -> None:
    slug = "a" * 101

    with pytest.raises(ArticleSlugInvalidError):
        parse_article(f"---\nslug: {slug}\ntitle: T\n---\nBody", f"{slug}.md")


def test_a_title_that_is_too_long_is_rejected() -> None:
    with pytest.raises(ArticleTitleInvalidError):
        parse_article(f"---\nslug: a\ntitle: {'T' * 256}\n---\nBody", "a.md")


def test_a_nul_character_in_an_article_is_rejected() -> None:
    with pytest.raises(ArticleContainsNulError):
        parse_article("---\nslug: a\ntitle: T\n---\nBody\x00text", "a.md")


def test_a_file_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"---\nslug: a\ntitle: T\n---\n\xff\xfe broken")

    with pytest.raises(ArticleNotUtf8Error):
        read_directory(tmp_path)
