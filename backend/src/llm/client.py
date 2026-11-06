from abc import ABC, abstractmethod

from llm.schemas import LLMRequest, LLMResult


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResult:
        raise NotImplementedError()
