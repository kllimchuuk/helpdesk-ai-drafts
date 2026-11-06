from core.base_model import Base
from kb.models import KbArticle
from tickets.models import TicketEvent

__all__ = ["Base", "KbArticle", "TicketEvent"]

metadata = Base.metadata
