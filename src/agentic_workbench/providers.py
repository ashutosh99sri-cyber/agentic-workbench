"""Provider contracts; durable state and tool execution are supplied by the host."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable

from .errors import WorkbenchError
from .models import Usage, validate


class BudgetLedger(Protocol):
    def reserve(self, maximum: int) -> None: ...


class IntentSink(Protocol):
    def intent(self, kind: str, metadata: dict[str, Any]) -> str: ...

    def receipt(self, intent_id: str, metadata: dict[str, Any]) -> None: ...

    def unknown(self, intent_id: str) -> None: ...


class ToolExecutor(Protocol):
    @property
    def schemas(self) -> list[dict[str, Any]]: ...

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ProviderRejected(WorkbenchError):
    """An adapter's explicit known rejection; uncertain attempts must never use this."""

    def __init__(self, message: str, *, code: str = "PROVIDER_REJECTED") -> None:
        if code not in {"PROVIDER_REJECTED", "PROVIDER_RATE_LIMIT"}:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid known provider rejection")
        super().__init__(code, message)


@dataclass(frozen=True)
class ProviderResult:
    analysis: dict[str, Any]
    usage: Usage

    def __post_init__(self) -> None:
        validate("ModelAnalysis", self.analysis)
        validate("Usage", asdict(self.usage))


@dataclass(frozen=True)
class EmbeddingResult:
    provider: str
    model: str
    chunk_hashes: tuple[str, ...]
    vectors: tuple[tuple[float, ...], ...]
    usage: Usage


@runtime_checkable
class Provider(Protocol):
    def analyze(
        self,
        request: str,
        context: dict[str, Any],
        *,
        executor: ToolExecutor,
        budget: BudgetLedger,
        intents: IntentSink,
    ) -> ProviderResult: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(
        self,
        texts: list[str],
        *,
        chunk_hashes: list[str],
        dimensions: int,
        source_grant: bool,
        budget: BudgetLedger,
        intents: IntentSink,
    ) -> EmbeddingResult: ...


class ProviderRegistry:
    """Only explicit registrations from trusted host code create providers."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, name: str, provider: Provider) -> None:
        if (
            not name
            or name == "none"
            or name in self._providers
            or not isinstance(provider, Provider)
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid or duplicate provider registration")
        self._providers[name] = provider

    def get(self, name: str) -> Provider:
        if name == "none":
            raise WorkbenchError(
                "INTEGRATION_UNAVAILABLE", "LLM mode requires a configured provider"
            )
        if name not in self._providers:
            raise WorkbenchError(
                "INTEGRATION_UNAVAILABLE", "Provider is not registered by the host"
            )
        return self._providers[name]
