"""Bounded external API transport; commands reuse the approved Runner backend."""

from __future__ import annotations

import multiprocessing
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .errors import WorkbenchError
from .models import canonical_json, strict_json
from .policy import WorkspacePolicy
from .secrets import SecretRedactor
from .tool_registry import ToolRegistry, ToolSpec


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise WorkbenchError("POLICY_DENIED", "API tool redirects are prohibited")


def _http_result(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float,
    opener: Any = None,
    limit: int = 12_000,
) -> dict[str, Any]:
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(  # noqa: S310 - parent validates fixed HTTPS destination
        url, data=body, headers=headers, method="POST"
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise WorkbenchError("POLICY_DENIED", "API destination changed")
            payload = response.read(limit + 1)
            if len(payload) > limit:
                raise WorkbenchError("LIMIT_EXCEEDED", "API response exceeds its byte limit")
            result = strict_json(payload.decode("utf-8"), max_bytes=limit)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise WorkbenchError("OUTCOME_UNKNOWN", "API transport outcome is unknown") from None
    except UnicodeError:
        raise WorkbenchError("VALIDATION_ERROR", "API result is not UTF-8 JSON") from None
    if not isinstance(result, dict):
        raise WorkbenchError("VALIDATION_ERROR", "API result requires a JSON object")
    return result


def _http_request(
    connection: Any, url: str, headers: dict[str, str], body: bytes, timeout: float, limit: int
) -> None:
    # This transport imports only installed host code; credentials travel through IPC, not argv.
    os.environ.clear()
    try:
        result = _http_result(url, headers, body, timeout, limit=limit)
        secret = headers.get("Authorization", "").removeprefix("Bearer ")
        payload = {"ok": True, "data": SecretRedactor((secret,)).clean(result, keys=False)}
    except WorkbenchError as error:
        payload = {"ok": False, "error": error.to_dict()}
    except BaseException:
        payload = {
            "ok": False,
            "error": {
                "code": "OUTCOME_UNKNOWN",
                "message": "API worker stopped",
                "retryable": False,
            },
        }
    try:
        connection.send_bytes(canonical_json(payload).encode())
    finally:
        connection.close()


class JSONAPI:
    """Host-fixed HTTPS POST destination with no ambient proxies or redirects."""

    def __init__(
        self,
        policy: WorkspacePolicy,
        url: str,
        *,
        credential: Callable[[], str] | None = None,
        opener: Any = None,
    ) -> None:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
            or parsed.port not in (None, 443)
        ):
            raise WorkbenchError("CONFIG_ERROR", "API tools require a fixed verified HTTPS URL")
        self.policy, self.url, self.host = policy, url, parsed.hostname
        self.credential = credential
        # A supplied opener is a trusted host transport and owns its operation deadline.
        self.opener = opener

    def request(
        self, arguments: dict[str, Any], *, timeout: float, limit: int = 12_000
    ) -> dict[str, Any]:
        self.policy.check_network(self.host)
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid API deadline")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        secret = ""
        if self.credential is not None:
            secret = self.credential()
            if not isinstance(secret, str) or not secret or any(c in secret for c in "\r\n"):
                raise WorkbenchError("CONFIG_ERROR", "Invalid API credential resolver result")
            headers["Authorization"] = "Bearer " + secret
        body = canonical_json(arguments).encode()
        if len(body) > 1_048_576:
            raise WorkbenchError("LIMIT_EXCEEDED", "API input exceeds its byte limit")
        if (
            secret and SecretRedactor((secret,)).contains_secret(body.decode())
        ) or self.policy.redactor.contains_secret(body.decode()):
            raise WorkbenchError("POLICY_DENIED", "API request body cannot contain credentials")
        if self.opener is not None:
            result = _http_result(self.url, headers, body, timeout, self.opener, limit)
        else:
            started = time.monotonic()
            context = multiprocessing.get_context("spawn")
            received, sent = context.Pipe(duplex=False)
            process = context.Process(
                target=_http_request,
                args=(sent, self.url, headers, body, timeout, limit),
                daemon=True,
            )
            try:
                process.start()
                sent.close()
                if not received.poll(max(0, timeout - (time.monotonic() - started))):
                    raise WorkbenchError("OUTCOME_UNKNOWN", "API total deadline elapsed")
                # Worker redaction can grow a response: each redacted character becomes the
                # 10-character "[REDACTED]" at most, plus JSON quoting.
                envelope_limit = 12 * limit + 64_000
                envelope = strict_json(
                    received.recv_bytes(envelope_limit).decode(), max_bytes=envelope_limit
                )
                if not envelope["ok"]:
                    raise WorkbenchError(envelope["error"]["code"], envelope["error"]["message"])
                result = envelope["data"]
            except (EOFError, OSError, UnicodeError):
                raise WorkbenchError(
                    "OUTCOME_UNKNOWN", "API worker has no validated receipt"
                ) from None
            finally:
                if process.pid is not None:
                    if process.is_alive():
                        process.kill()
                    process.join(timeout=5)
                    process.close()
                received.close()
                sent.close()
        # Only the credential is removed here: values keep their types, so the registry
        # validates the API's own result and then redacts credential-named keys.
        return SecretRedactor((secret,)).clean(result, keys=False)  # type: ignore[no-any-return]

    def register(self, registry: ToolRegistry, spec: ToolSpec) -> None:
        if (
            registry.policy.workspace_id != self.policy.workspace_id
            or spec.backend != "api"
            or spec.destination != self.host
        ):
            raise WorkbenchError("CONFIG_ERROR", "API binding destination or workspace differs")
        # Reads feed model context; effect receipts only need the registry's result bound.
        limit = 12_000 if spec.effect == "read" else 1_048_576
        registry.register(
            spec,
            lambda arguments, call: self.request(arguments, timeout=call.timeout, limit=limit),
            reviewer=lambda arguments: {"url": self.url, "method": "POST"},
        )
