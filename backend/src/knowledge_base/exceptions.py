from core.exceptions import NotFoundError


class KbArticleNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__(
            code="kb_article_not_found",
            message="Knowledge-base article not found.",
        )


class ArticleFileError(ValueError):
    pass
