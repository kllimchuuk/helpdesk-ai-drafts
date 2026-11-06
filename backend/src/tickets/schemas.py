from pydantic import BaseModel


class StatsResponse(BaseModel):
    counts: dict[str, int]
    total: int
