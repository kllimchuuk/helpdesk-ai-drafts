from typing import Annotated

from fastapi import APIRouter, Depends

from knowledge_base.schemas import ArticleResponse
from knowledge_base.service import KbService, get_kb_service

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.get("/{slug}", response_model=ArticleResponse)
async def get_article(
    slug: str,
    service: Annotated[KbService, Depends(get_kb_service)],
) -> ArticleResponse:
    return ArticleResponse.model_validate(await service.get_article(slug))
