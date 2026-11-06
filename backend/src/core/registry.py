from core.base_model import Base
from knowledge_base.models import KbArticle
from tickets.models import TicketEvent

__all__ = ["Base", "KbArticle", "TicketEvent"]

metadata = Base.metadata
