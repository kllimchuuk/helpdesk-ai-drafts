from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


class WebhookPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=255)
    ticket_id: str = Field(min_length=1, max_length=255)
    customer_email: str = Field(min_length=3, max_length=320, pattern=EMAIL_PATTERN)
    message: str = Field(min_length=1, max_length=20_000)
    reply_url: AnyHttpUrl

    @field_validator("event_id", "ticket_id", "customer_email", "message")
    @classmethod
    def reject_nul_characters(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value


class WebhookResponse(BaseModel):
    status: Literal["accepted", "duplicate"]
