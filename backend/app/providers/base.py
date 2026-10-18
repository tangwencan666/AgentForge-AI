from dataclasses import dataclass
from typing import Protocol, Callable, Awaitable


@dataclass
class ModelReply:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    first_token_ms: int | None
    latency_ms: int
    http_status: int | None = None
    sse_complete: bool = False
    usage_details: dict | None = None


class ProviderFailure(Exception):
    def __init__(self, code, retryable=False, status=None):
        self.code, self.retryable, self.status = code, retryable, status
        super().__init__(code)  # Never includes supplier body, URL or credential.


class ProviderAdapter(Protocol):
    async def complete(self, config: dict, messages: list[dict], credential: str,
                       delta: Callable[[str], Awaitable[None]], *, dispatch=None) -> ModelReply: ...
