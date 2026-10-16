"""Conservative secret filtering; unknown credentials cannot be detected perfectly."""

from __future__ import annotations

import os
import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from typing import Any

from .errors import WorkbenchError

_PATTERNS = (
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{15,}"),
    # A truncated copy: the header and its base64 lines without an END marker.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:\r?\n[A-Za-z0-9+/=]{16,})+"),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@[^\s/]+"),
    # JSON Web Tokens ("eyJ" is base64 for '{"') and bearer credentials in headers or logs.
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bBearer[ \t]+[A-Za-z0-9._~+/-]{16,}=*"),
)
# Complete private key blocks, matched by _private_keys.
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_WORDS = (
    r"api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|token|private[_-]?key"
    r"|secret[_-]?access[_-]?key|secret[_-]?key(?:[_-]?base)?"
)
_CAMEL_WORDS = r"(?:Api|API|Private|Secret|SecretAccess)Key(?:Base)?|Password|Secret|Token"
# One name rule for text and structured keys, anchored at the secret word: it starts a
# name, follows a separator, or (camelCase) follows a letter or digit. A one-character
# lookbehind replaces a prefix loop, so names of any length match in linear time. Accepted
# separators: `=`, `:`, Go `:=`, a typed declaration (`name: Type = value`) and a quoted
# subscript key (`config['SECRET_KEY'] = value`).
_NAME = re.compile(
    r"""(?i)(?P<word>(?:\b|(?<=[_-]))(?:""" + _WORDS + r""")"""
    r"""|(?<=[a-z0-9])(?-i:""" + _CAMEL_WORDS + r"""))\b["']?\]?"""
    r"""(?:[ \t]*:[ \t]*[A-Za-z_][\w.]*(?:\[[\w.,| \t\[\]]*\])?(?=[ \t]+=(?!=)))?"""
    r"""[ \t]*(?::=|[:=](?!=))[ \t]*"""
)
_QUOTED = re.compile(r"""(["'])((?:\\.|(?!\1)[^\\\r\n])+)\1""")
_BARE = re.compile(r"""[^\s"'`,;#{}\[\]()]+""")
_BARE_END = re.compile(r"""[ \t]*(?:[,;#}\]\r\n]|$)""")
_REFERENCE = re.compile(
    r"(?i)(?:[a-z_]\w*\.)+[a-z_]\w*|\$[a-z_]\w*|none|null|true|false"
    # Type annotations such as `database_password: str` name a type, not a value.
    r"|str|string|int|integer|float|number|bool|boolean|bytes|object|any|secret(?:str|bytes)"
)
# Variable expansions name a value held elsewhere: ${VAR}, ${{ expr }}, $VAR, {{ template }}.
_EXPANSION = re.compile(
    r"\$\{\{[^}]*\}\}|\$\{[A-Za-z_][A-Za-z0-9_]*(?::?[-=?+][^}]*)?\}|\$[A-Za-z_]\w*|\{\{[^}]*\}\}"
)
# A snake or screaming-snake compound ending in a secret word (ANTHROPIC_API_KEY,
# access_token) names a variable or setting; a credential is not written that way.
_COMPOUND = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+")
# The lookahead finds a space once, so long values are checked in linear time.
_SENTENCE = re.compile(r"(?=.*\s).*[.!?…]")
# A sentence under a name for a missing or failed credential (Devise's no_token,
# invalid_password) is a message; under any other name (SERVICE_PASSWORD) it may be a passphrase.
_MESSAGE_NAME = re.compile(
    r"(?is)(?:.*[^a-z0-9])?(?:no|invalid|missing|wrong|incorrect|expired|forgot)[_-](?:"
    + _WORDS
    + ")"
)
_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-.$")
# shortcut: other bare identifiers can be false positives; use syntax-aware parsing if needed.
_ENV_NAME = re.compile(r"(?:^|_)(?:API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|CREDENTIAL)(?:_|$)")
_SECRET_NAME = re.compile(r"(?is)(?:.*[^a-z0-9])?(?:" + _WORDS + ")")
# Structured keys only: headers and containers that carry credentials.
_SECRET_KEY = re.compile(
    r"(?is)(?:.*[^a-z0-9])?(?:authorization|cookies?|secret[_-]?string|secret[_-]?binary|secrets)"
)
# Not credentials: pagination cursors and model special tokens.
_NOT_SECRET = re.compile(
    r"(?is)(?:.*[^a-z0-9])?(?:(?:next[_-]?)?page|next|continuation|pagination|sync|resume"
    r"|cancel(?:lation)?|pad|eos|bos|sos|unk|mask|sep|cls)[_-]?token"
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _is_secret_name(name: str) -> bool:
    normalized = _CAMEL_BOUNDARY.sub("_", name)
    return (
        _SECRET_NAME.fullmatch(normalized) is not None and _NOT_SECRET.fullmatch(normalized) is None
    )


def _is_secret_key(name: str) -> bool:
    return _is_secret_name(name) or (
        _SECRET_KEY.fullmatch(_CAMEL_BOUNDARY.sub("_", name)) is not None
    )


def _merged(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _private_keys(text: str) -> list[tuple[int, int]]:
    """Spans from each BEGIN marker to the first END after it, as `BEGIN.*?END` matches.

    END markers are found once, so unterminated BEGIN markers never rescan the text, and a
    truncated copy before a complete block is covered whatever its line format.
    """
    ends = [match.span() for match in _PEM_END.finditer(text)]
    starts = [start for start, _ in ends]
    spans: list[tuple[int, int]] = []
    for match in _PEM_BEGIN.finditer(text):
        if spans and match.start() < spans[-1][1]:
            continue
        index = bisect_left(starts, match.end())
        if index == len(ends):
            break
        spans.append((match.start(), ends[index][1]))
    return spans


_MARKER = re.compile(r"\[REDACTED\]")


def _replacement(value: str) -> str:
    # One marker per non-empty line keeps line numbers and bounds growth at 10x.
    return "\n".join("[REDACTED]" if line else "" for line in value.split("\n"))


def _literal(name: str, value: str, quoted: bool) -> bool:
    """Whether an assignment's value is a credential literal rather than a reference."""
    if _EXPANSION.fullmatch(value) or (
        _COMPOUND.fullmatch(value) is not None and _is_secret_name(value)
    ):
        return False
    if quoted:
        message = _MESSAGE_NAME.fullmatch(_CAMEL_BOUNDARY.sub("_", name)) is not None
        return not (message and _SENTENCE.fullmatch(value) is not None)
    # `self.password = password` copies a variable into an attribute of the same name;
    # in configuration `password: password` is a literal, so only attribute targets count.
    copy = "." in name and value.lower() == name.rsplit(".", 1)[-1].lower()
    return _REFERENCE.fullmatch(value) is None and not copy


def _assignments(text: str) -> list[tuple[int, int, bool]]:
    """Value spans (start, end, is_literal) of named assignments, scanned left to right.

    A bare value always extends to the end of its maximal run, so runs are found once and
    shared: overlapping assignments never rescan the same text. A quoted value only advances
    the scan to its content, so a name inside an unbalanced quote is still examined.
    """
    found: list[tuple[int, int, bool]] = []
    runs: list[tuple[int, int]] | None = None
    starts: list[int] = []
    endings: dict[int, bool] = {}
    position = 0
    for match in _NAME.finditer(text):
        if match.start() < position:
            continue
        begin = match.start("word")
        while begin > 0 and text[begin - 1] in _NAME_CHARS:
            begin -= 1
        name = text[begin : match.end("word")]
        if not _is_secret_name(name.rsplit(".", 1)[-1].lstrip("$") or name):
            continue
        start = match.end()
        quoted = _QUOTED.match(text, start)
        if quoted is not None:
            literal = _literal(name, quoted.group(2), True)
            found.append((quoted.start(2), quoted.end(2), literal))
            position = quoted.start(2)
            continue
        if runs is None:
            runs = [run.span() for run in _BARE.finditer(text)]
            starts = [run[0] for run in runs]
        index = bisect_right(starts, start) - 1
        if index < 0 or runs[index][1] <= start:
            continue
        end = runs[index][1]
        if index not in endings:
            # Each run's ending (and any whitespace tail) is checked once, then shared.
            endings[index] = _BARE_END.match(text, end) is not None
        if not endings[index]:
            continue
        found.append((start, end, _literal(name, text[start:end], False)))
        position = end
    return found


class SecretRedactor:
    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values = tuple(sorted({value for value in values if value}, key=len, reverse=True))

    def _value_spans(self, text: str) -> list[tuple[int, int]]:
        """Every occurrence of every configured value, outside existing [REDACTED] markers.

        Spans of different values may overlap and are merged by the caller, so a shorter
        value cannot hide a longer one, and redacting twice changes nothing.
        """
        markers = [marker.span() for marker in _MARKER.finditer(text)]
        starts = [marker[0] for marker in markers]
        spans = []
        for value in self._values:
            start = text.find(value)
            while start != -1:
                end = start + len(value)
                index = bisect_right(starts, start) - 1
                if index < 0 or end > markers[index][1]:
                    spans.append((start, end))
                start = text.find(value, end)
        return spans

    @classmethod
    def from_environment(
        cls, names: Iterable[str] = (), environment: Mapping[str, str] | None = None
    ) -> SecretRedactor:
        env = os.environ if environment is None else environment
        selected = set(names) | {key for key in env if _ENV_NAME.search(key.upper())}
        return cls(env[key] for key in selected if key in env)

    def contains_secret(self, text: str) -> bool:
        return (
            bool(self._value_spans(text))
            or any(pattern.search(text) for pattern in _PATTERNS)
            or bool(_private_keys(text))
            or any(literal for _, _, literal in _assignments(text))
        )

    def redact(self, text: str) -> str:
        # Configured values, assignment values and token patterns are all found on the same
        # original text and merged, so no pass can erase what another needs (a name, or a PEM
        # BEGIN marker) and nothing is rescanned.
        spans = self._value_spans(text) + _private_keys(text)
        spans += [(start, end) for start, end, literal in _assignments(text) if literal]
        for pattern in _PATTERNS:
            spans += [match.span() for match in pattern.finditer(text)]
        parts, last = [], 0
        for start, end in _merged(spans):
            parts += [text[last:start], _replacement(text[start:end])]
            last = end
        return "".join(parts) + text[last:]

    def clean(self, value: Any, *, keys: bool = True) -> Any:
        """Redact strings and, with keys, every value under a credential-named key.

        keys=False keeps every value's type, for transports whose results the tool registry
        validates before it applies the key rule.
        """
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, (list, tuple)):
            return [self.clean(item, keys=keys) for item in value]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise WorkbenchError("VALIDATION_ERROR", "JSON objects require string keys")
                safe_key = self.redact(key)
                if safe_key in result:
                    raise WorkbenchError("VALIDATION_ERROR", "Redaction produced duplicate keys")
                # Booleans and None describe a credential; they never are one.
                secret = (
                    keys and _is_secret_key(key) and item is not None and not isinstance(item, bool)
                )
                result[safe_key] = "[REDACTED]" if secret else self.clean(item, keys=keys)
            return result
        return value
