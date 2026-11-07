from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from knowledge_base.loader import sync_articles
from knowledge_base.models import KbArticle
from knowledge_base.repository import KbRepository, KbRepositoryImpl
from knowledge_base.schemas import ArticleScore, ParsedArticle
from knowledge_base.service import MAX_WORDS, KbService, extract_words

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
LONG_TICKETS = [
    (
        "Добрий день! Пишу вам вже втретє, бо проблема триває з понеділка і ми дуже "
        "непокоїмося, адже від цього залежить робота нашого відділу та наших клієнтів. "
        "Ми користуємось вашим сервісом вже другий рік і раніше все було добре. "
        "Не можу експортувати звіт у PDF",
        "export-report-pdf",
    ),
    (
        "Добрий день, команда Vistara. Я адміністратор у нашій компанії, ми працюємо з "
        "вашою платформою вже понад рік і загалом задоволені. Але сьогодні вранці я не "
        "зміг зайти в свій акаунт, бо забув пароль, а лист для відновлення чомусь не "
        "приходить на пошту.",
        "reset-password",
    ),
    (
        "Вітаю! Наш фінансовий відділ просить допомогти: ми хотіли б змінити тариф на "
        "більший, а також отримати рахунок для бухгалтерії за попередній місяць, бо ми "
        "не знаємо, де його завантажити.",
        "billing-and-invoices",
    ),
    (
        "Доброго дня. Наша команда розширюється, і ми хочемо запросити трьох нових "
        "колег, але не розуміємо, як налаштувати їхні права, щоб вони могли лише "
        "переглядати дашборди, а не змінювати їх.",
        "team-roles-and-invites",
    ),
    (
        "Привіт, розробники в нашій компанії інтегрують ваш сервіс у внутрішню "
        "систему. Усе працювало нормально, але від учора наші запити до API почали "
        "повертати помилку 429, хоча кількість запитів не змінювалась.",
        "api-keys-and-limits",
    ),
]
LONG_UNRELATED = [
    "Добрий день! Хотів би дізнатися, чи можна замовити для нашої компанії "
    "корпоративні подарунки до новорічних свят, адже ми шукаємо надійного "
    "постачальника солодощів та сувенірів зі знижкою для великої кількості "
    "співробітників.",
    "Вітаю, мене цікавить інформація про вільні вакансії у вашій компанії, зокрема на "
    "посаду менеджера з продажів, а також умови стажування для студентів останніх "
    "курсів університету та можливість віддаленої роботи.",
    "Доброго вечора. Підкажіть, будь ласка, як дістатися від залізничного вокзалу до "
    "вашого офісу в Києві, адже я приїжджаю потягом зі Львова і ще не знаю міста, а "
    "також чи є поруч безкоштовна парковка.",
    "Скажіть, чи плануєте ви проводити цього року конференцію для клієнтів і "
    "партнерів, бо ми хотіли б виступити з доповіддю про наш досвід, і чи можна "
    "заздалегідь "
    "отримати програму заходу та список спікерів.",
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


async def test_a_higher_threshold_returns_fewer_matches() -> None:
    repository = FixedScores([score(0, 0.6)])

    loose = await KbService(repository, min_score=0.0).search("експорт звіту")
    strict = await KbService(repository, min_score=0.99).search("експорт звіту")

    assert len(loose) == 1
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
        f"Налаштуйте з{apostrophe}єднання з базою даних у розділі підключень.\n"
    )
    await sync_articles(session_factory, tmp_path)

    async with session_factory() as session:
        matches = await service(session, min_score=0.8).search("з\u02bcєднання")

    assert [match.slug for match in matches] == ["connections"]


@pytest.mark.parametrize(("ticket", "expected"), LONG_TICKETS)
async def test_a_long_ticket_still_finds_its_article_first(
    loaded_kb: None,
    session_factory: async_sessionmaker[AsyncSession],
    ticket: str,
    expected: str,
) -> None:
    async with session_factory() as session:
        matches = await service(session).search(ticket)

    assert matches, ticket
    assert matches[0].slug == expected


@pytest.mark.parametrize("ticket", LONG_UNRELATED)
async def test_a_long_unrelated_ticket_matches_nothing(
    loaded_kb: None, session_factory: async_sessionmaker[AsyncSession], ticket: str
) -> None:
    async with session_factory() as session:
        matches = await service(session).search(ticket)

    assert matches == []


class FixedScores(KbRepository):
    def __init__(self, scores: list[ArticleScore]) -> None:
        self.scores = scores
        self.words_seen: list[list[str]] = []

    async def get_by_slug(self, slug: str) -> None:
        return None

    async def score_articles(
        self, words: list[str], strong_similarity: float
    ) -> list[ArticleScore]:
        self.words_seen.append(words)
        return self.scores

    async def replace_all(self, articles: list[ParsedArticle]) -> None:
        return None


def score(strong_words: int, trigram: float) -> ArticleScore:
    return ArticleScore(
        slug="a",
        title="A",
        trigram_score=trigram,
        fts_score=0.0,
        strong_words=strong_words,
    )


@pytest.mark.parametrize(
    ("strong_words", "trigram", "accepted"),
    [
        (0, 0.2, False),
        (2, 0.3, False),
        (3, 0.3, True),
        (0, 0.6, True),
        (2, 0.6, True),
    ],
)
async def test_an_article_needs_a_high_score_or_three_strong_words(
    strong_words: int, trigram: float, accepted: bool
) -> None:
    repository = FixedScores([score(strong_words, trigram)])

    matches = await KbService(repository, min_score=0.4).search("експорт звіту")

    assert bool(matches) is accepted


async def test_the_words_passed_to_the_database_are_capped() -> None:
    repository = FixedScores([score(0, 0.0)])
    query = " ".join(f"слово{number}" for number in range(5000))

    await KbService(repository, min_score=0.4).search(query)

    assert len(repository.words_seen[0]) == MAX_WORDS


async def test_searching_an_empty_knowledge_base_finds_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        matches = await service(session).search("Не можу експортувати звіт у PDF")

    assert matches == []


@pytest.mark.parametrize(
    "query",
    ["x\u00b2 \u00bd \u0663\u0663\u0663 \uff41\uff42\uff43", "\u0301\u0301\u0301 ﷺ"],
)
async def test_unusual_unicode_does_not_break_the_search(
    loaded_kb: None, session_factory: async_sessionmaker[AsyncSession], query: str
) -> None:
    async with session_factory() as session:
        matches = await service(session).search(query)

    assert matches == []


async def test_the_repository_returns_raw_rows_and_the_service_maps_them(
    loaded_kb: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = await KbRepositoryImpl(session).score_articles(["pdf", "звіт"], 0.5)

    assert len(rows) == 8
    assert not any(isinstance(row, ArticleScore) for row in rows)
    assert {"slug", "title", "trigram_score", "fts_score", "strong_words"} <= set(
        rows[0]._fields
    )


async def test_the_service_turns_raw_rows_into_matches() -> None:
    row = SimpleNamespace(
        slug="a", title="A", trigram_score=0.9, fts_score=0.0, strong_words=0
    )

    matches = await KbService(FixedScores([row]), min_score=0.1).search("звіт pdf")

    assert [match.slug for match in matches] == ["a"]
