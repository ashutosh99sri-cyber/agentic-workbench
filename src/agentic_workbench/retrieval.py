"""Deterministic lexical/vector retrieval and reciprocal rank fusion."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from .errors import WorkbenchError
from .models import Evidence, canonical_hash, text_hash


@dataclass(frozen=True)
class Chunk:
    evidence: Evidence
    text: str

    @cached_property
    def id(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"evidence": self.evidence.to_dict(), "text": self.text}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())


def lexical_search(chunks: list[Chunk], query: str, limit: int = 5) -> list[Chunk]:
    if (
        not isinstance(query, str)
        or len(query) > 4096
        or type(limit) is not int
        or not 1 <= limit <= 50
    ):
        raise WorkbenchError("VALIDATION_ERROR", "Invalid retrieval request")
    wanted = set(tokens(query))
    counts = [Counter(tokens(chunk.text)) for chunk in chunks]
    frequencies = Counter(token for count in counts for token in count)
    ranked: list[tuple[float, str, int, Chunk]] = []
    for chunk, count in zip(chunks, counts, strict=True):
        score = sum(
            (1 + math.log(count[t])) * math.log(1 + len(chunks) / frequencies[t])
            for t in wanted
            if count[t]
        )
        if score:
            ranked.append((-score, chunk.evidence.path, chunk.evidence.start_line, chunk))
    ranked.sort(key=lambda row: row[:3])
    return [row[3] for row in ranked[:limit]]


def combine_rankings(lexical: list[Chunk], vector: list[Chunk], limit: int = 5) -> list[Chunk]:
    """Fuse ranked candidates by identity using reciprocal ranks with fixed k=60.

    Ignore repeated identities before assigning each source's one-based ranks.
    Break score ties by path, start line and identity, without mutating inputs.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise WorkbenchError("VALIDATION_ERROR", "Invalid retrieval limit")
    candidates: dict[str, Chunk] = {}
    scores: dict[str, float] = {}
    for ranking in (lexical, vector):
        seen: set[str] = set()
        for chunk in ranking:
            identity = chunk.id
            if identity in seen:
                continue
            seen.add(identity)
            candidates.setdefault(identity, chunk)
            scores[identity] = scores.get(identity, 0.0) + 1 / (60 + len(seen))
    ranked = sorted(
        candidates,
        key=lambda identity: (
            -scores[identity],
            candidates[identity].evidence.path,
            candidates[identity].evidence.start_line,
            identity,
        ),
    )
    return [candidates[identity] for identity in ranked[:limit]]


class VectorIndex:
    def __init__(self, provider: str, model: str, dimensions: int) -> None:
        if not provider or not model or type(dimensions) is not int or not 1 <= dimensions <= 8192:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid vector metadata")
        self.provider, self.model, self.dimensions = provider, model, dimensions
        self.rows: dict[str, tuple[str, list[float]]] = {}

    def _vector(self, vector: list[float]) -> list[float]:
        if (
            not isinstance(vector, list)
            or len(vector) != self.dimensions
            or any(type(x) not in {int, float} or not math.isfinite(x) for x in vector)
            or not any(vector)
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid embedding vector")
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise WorkbenchError("VALIDATION_ERROR", "Embedding magnitude exceeds bounds")
        return [x / norm for x in vector]

    def add(self, chunk: Chunk, vector: list[float], chunk_hash: str) -> None:
        if chunk_hash != text_hash(chunk.text):
            raise WorkbenchError("STALE", "Embedding is bound to different source")
        self.rows[chunk.id] = (chunk_hash, self._vector(vector))

    def search(self, query: list[float], chunks: list[Chunk], limit: int = 5) -> list[Chunk]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid retrieval limit")
        normalized = self._vector(query)
        ranked = []
        for chunk in chunks:
            row = self.rows.get(chunk.id)
            if row and row[0] == text_hash(chunk.text):
                score = sum(a * b for a, b in zip(normalized, row[1], strict=True))
                ranked.append((-score, chunk.evidence.path, chunk.evidence.start_line, chunk))
        ranked.sort(key=lambda item: item[:3])
        return [item[3] for item in ranked[:limit]]
