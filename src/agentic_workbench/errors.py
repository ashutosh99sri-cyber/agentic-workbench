"""Stable errors; messages must not include untrusted bodies or credentials."""


class WorkbenchError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{code}: {message}")

    @property
    def exit_code(self) -> int:
        if self.code in {"CONFIG_ERROR", "VALIDATION_ERROR"}:
            return 2
        if self.code in {
            "POLICY_DENIED",
            "APPROVAL_REQUIRED",
            "STALE_APPROVAL",
            "STALE",
            "CONFLICT",
        }:
            return 3
        if self.code in {"SANDBOX_UNAVAILABLE", "INTEGRATION_UNAVAILABLE"}:
            return 4
        return 1

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
