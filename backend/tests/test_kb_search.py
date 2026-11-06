import time
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from kb.loader import sync_articles
from kb.models import KbArticle
from kb.repository import KbRepositoryImpl
from kb.service import MAX_WORDS, KbService, extract_words

TICKETS = [
    ("Не можу експортувати звіт у PDF", "export-report-pdf"),
    ("Забув пароль, як відновити доступ до акаунта?", "reset-password"),
    (
        "Скажіть, як змінити тариф і де знайти рахунок за минулий місяць",
        "billing-and-invoices",
    ),
    (
        "Хочу додати нового колегу в команду і дати йому права редактора",
        "team-roles-and-invites",
    ),
    ("Отримую помилку 429 при запитах до вашого API", "api-keys-and-limits"),
    (
        "Як зробити, щоб звіт щотижня автоматично приходив мені на пошту?",
        "scheduled-reports",
    ),
    (
        "Після експорту в CSV українські літери відображаються нерозбірливо",
        "export-excel-csv",
    ),
    (
        "Мені не приходить код двофакторної автентифікації, не можу увійти",
        "login-troubleshooting",
    ),
]
HARDER_TICKETS = [
    ("Не вдається завантажити pdf версію звіту, пише помилку", "export-report-pdf"),
    ("Експорт звіту в ексель не працює", "export-excel-csv"),
    ("Чому мене заблокувало після кількох спроб входу?", "login-troubleshooting"),
    ("Скільки коштує підписка і як її оплатити карткою", "billing-and-invoices"),
    ("Як створити ключ для API", "api-keys-and-limits"),
    ("Хочу видалити колегу з команди", "team-roles-and-invites"),
    ("Налаштувати щомісячну розсилку звіту на пошту директору", "scheduled-reports"),
    ("не приходить лист для скидання пароля", "reset-password"),
]
UNRELATED = [
    "Розкажіть про історію Київської Русі і її князів",
    "Скільки коштує квиток на потяг до Одеси?",
    "Допоможіть налаштувати роутер вдома, інтернет дуже повільний",
    "Хочу замовити піцу з доставкою на завтра ввечері",
    "Як приготувати борщ за класичним рецептом з буряком і м\u2019ясом",
    "Чи працює ваш офіс у святкові дні та які у вас вакансії для розробників",
    "Мій кіт не їсть корм вже третій день, що робити",
    "Яка завтра погода у Львові?",
    "Привіт!",
    "Дякую, добрий день",
    "asdf qwerty zxcv",
    "Де знайти найкращу піцу в місті",
]


def service(
    session: AsyncSession, min_score: float = Settings(_env_file=None).KB_MIN_SCORE
) -> KbService:
    return KbService(KbRepositoryImpl(session), min_score=min_score)


@pytest.mark.parametrize(("ticket", "expected"), TICKETS)
async def test_the_right_article_comes_first(
    loaded_kb: None,
    session_factory: async_sessionmaker[AsyncSession],
    ticket: str,
    expected: str,
) -> None:
    async with session_factory() as session:
        matches = await service(session).search(ticket)

    assert matches, ticket
    assert matches[0].slug == expected


@pytest.mark.parametrize(("ticket", "expected"), HARDER_TICKETS)
async def test_the_right_article_is_among_the_first_three(
    loaded_kb: None,
    session_factory: async_sessionmaker[AsyncSession],
    ticket: str,
    expected: str,
) -> None:
    async with session_factory() as session:
        matches = await service(session).search(ticket)

    assert expected in [match.slug for match in matches], ticket


@pytest.mark.parametrize("ticket", UNRELATED)
async def test_unrelated_text_matches_nothing(
    loaded_kb: None, session_factory: async_sessionmaker[AsyncSession], ticket: str
) -> None:
    async with session_factory() as session:
        matches = await service(session).search(ticket)

    assert matches == []


async def test_at_most_three_matches_in_descending_score_order(
    loaded_kb: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        matches = await service(session, min_score=0.0).search(
            "звіт експорт пошта пароль"
        )

    assert len(matches) == 3
    scores = [match.score for match in matches]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= score <= 1.0 for score in scores)


async def test_a_higher_threshold_returns_fewer_matches(
    loaded_kb: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        loose = await service(session, min_score=0.0).search(TICKETS[0][0])
        strict = await service(session, min_score=0.99).search(TICKETS[0][0])

    assert len(loose) > len(strict)
    assert strict == []


@pytest.mark.parametrize(
    "query",
    [
        "'; DROP TABLE kb_articles; --",
        "!&|:*()<->",
        "\\ ' \" ; -- /* */",
        "   ",
        "",
    ],
)
async def test_hostile_or_empty_queries_are_harmless(
    loaded_kb: None, session_factory: async_sessionmaker[AsyncSession], query: str
) -> None:
    async with session_factory() as session:
        matches = await service(session).search(query)
        total = await session.scalar(select(func.count()).select_from(KbArticle))

    assert matches == []
    assert total == 8


async def test_a_huge_query_is_bounded(
    loaded_kb: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    query = " ".join(f"слово{number}" for number in range(5000))

    started = time.perf_counter()
    async with session_factory() as session:
        await service(session).search(query)

    assert time.perf_counter() - started < 2.0


def test_words_are_lowercased_filtered_and_deduplicated() -> None:
    words = extract_words("Не можу ЕКСПОРТУВАТИ звіт у PDF, звіт!")

    assert words == ["експортувати", "звіт", "pdf"]


def test_apostrophes_do_not_split_words() -> None:
    assert extract_words("об\u2019єм п\u02bcять з'єднання") == [
        "обєм",
        "пять",
        "зєднання",
    ]


def test_digits_and_latin_words_are_kept() -> None:
    assert extract_words("API 429 error") == ["api", "429", "error"]


def test_the_number_of_words_is_capped() -> None:
    text = " ".join(f"слово{number}" for number in range(MAX_WORDS * 3))

    assert len(extract_words(text)) == MAX_WORDS


@pytest.mark.parametrize("apostrophe", ["\u2019", "\u02bc", "'"])
async def test_apostrophes_in_the_article_do_not_hide_a_match(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, apostrophe: str
) -> None:
    (tmp_path / "connections.md").write_text(
        "---\nslug: connections\ntitle: Підключення\n---\n"
        "Налаштуйте з'єднання з базою даних у розділі підключень.\n"
    )
    await sync_articles(session_factory, tmp_path)

    async with session_factory() as session:
        matches = await service(session, min_score=0.8).search(f"з{apostrophe}єднання")

    assert [match.slug for match in matches] == ["connections"]
