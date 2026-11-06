from core.exceptions import AppException, NotFoundError


class KbArticleNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__(
            code="kb_article_not_found",
            message="Knowledge-base article not found.",
        )


class ArticleFileError(AppException):
    def __init__(self, code: str, message: str, source: str) -> None:
        super().__init__(
            code=code, message=f"{source}: {message}", payload={"source": source}
        )


class ArticleContainsNulError(ArticleFileError):
    def __init__(self, source: str) -> None:
        super().__init__(
            "article_contains_nul", "NUL characters are not allowed", source
        )


class ArticleNotUtf8Error(ArticleFileError):
    def __init__(self, source: str) -> None:
        super().__init__("article_not_utf8", "the file is not valid UTF-8", source)


class ArticleFrontMatterMissingError(ArticleFileError):
    def __init__(self, source: str) -> None:
        super().__init__(
            "article_front_matter_missing",
            "the file must start with front matter",
            source,
        )


class ArticleFrontMatterUnclosedError(ArticleFileError):
    def __init__(self, source: str) -> None:
        super().__init__(
            "article_front_matter_unclosed", "the front matter is not closed", source
        )


class ArticleFrontMatterLineError(ArticleFileError):
    def __init__(self, source: str, line: str) -> None:
        super().__init__(
            "article_front_matter_line",
            f"unexpected front matter line {line!r}",
            source,
        )


class ArticleFrontMatterDuplicateKeyError(ArticleFileError):
    def __init__(self, source: str, key: str) -> None:
        super().__init__(
            "article_front_matter_duplicate_key", f"{key!r} is given twice", source
        )


class ArticleSlugInvalidError(ArticleFileError):
    def __init__(self, source: str, slug: str) -> None:
        super().__init__(
            "article_slug_invalid",
            f"slug {slug!r} must be lowercase words joined by hyphens",
            source,
        )


class ArticleTitleInvalidError(ArticleFileError):
    def __init__(self, source: str, max_length: int) -> None:
        super().__init__(
            "article_title_invalid",
            f"the title must be 1-{max_length} characters",
            source,
        )


class ArticleBodyEmptyError(ArticleFileError):
    def __init__(self, source: str) -> None:
        super().__init__("article_body_empty", "the article has no text", source)


class ArticleFileNameMismatchError(ArticleFileError):
    def __init__(self, source: str, slug: str) -> None:
        super().__init__(
            "article_file_name_mismatch", f"the file name must be {slug}.md", source
        )


class ArticleDirectoryEmptyError(ArticleFileError):
    def __init__(self, directory: str) -> None:
        super().__init__("article_directory_empty", "no articles found", directory)
