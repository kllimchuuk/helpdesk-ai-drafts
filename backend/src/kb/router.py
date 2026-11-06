from typing import Annotated

from fastapi import APIRouter, Depends

from kb.schemas import ArticleResponse
from kb.service import KbService, get_kb_service

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.get("/{slug}", response_model=ArticleResponse)
async def get_article(
    slug: str,
    service: Annotated[KbService, Depends(get_kb_service)],
) -> ArticleResponse:
    return ArticleResponse.model_validate(await service.get_article(slug))
