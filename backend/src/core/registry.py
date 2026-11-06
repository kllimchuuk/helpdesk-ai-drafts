from core.base_model import Base
from knowledge_base.models import KbArticle
from llm.models import LlmCall
from tickets.models import TicketEvent

__all__ = ["Base", "KbArticle", "LlmCall", "TicketEvent"]

metadata = Base.metadata
