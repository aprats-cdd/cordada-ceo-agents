"""
Context Cache — TTL-based cache for CONTEXT middleware results.

Avoids repeated API calls when the same question is asked within the same
pipeline run.  Like a Bloomberg terminal that doesn't recalculate the same
pricing twice in the same session.

Cache key: SHA-256 hash of (normalized_question, agent_name, run_id).
Invalidation: on gate passage, feedback iteration, or CEO override.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    """A single cached CONTEXT result."""
    result: dict         # serialized ContextResult
    timestamp: float
    calling_agent: str
    question_hash: str
    run_id: str = ""


class ContextCache:
    """In-memory TTL cache for CONTEXT middleware results.

    Args:
        ttl_seconds: Time-to-live in seconds (default: 1 hour).
    """

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self._store: dict[str, CacheEntry] = {}

    def _hash(self, question: str, agent: str, run_id: str) -> str:
        """Normalize and hash the question + context key."""
        normalized = question.strip().lower()
        return hashlib.sha256(
            f"{normalized}:{agent}:{run_id}".encode()
        ).hexdigest()[:16]

    def get(self, question: str, agent: str, run_id: str) -> dict | None:
        """Retrieve a cached result, or None if miss/expired."""
        h = self._hash(question, agent, run_id)
        entry = self._store.get(h)
        if entry and (time.time() - entry.timestamp) < self.ttl:
            return entry.result
        if entry:
            del self._store[h]  # expired
        return None

    def put(self, question: str, agent: str, run_id: str, result: dict) -> None:
        """Store a result in the cache."""
        h = self._hash(question, agent, run_id)
        self._store[h] = CacheEntry(
            result=result,
            timestamp=time.time(),
            calling_agent=agent,
            question_hash=h,
            run_id=run_id,
        )

    def invalidate_run(self, run_id: str) -> int:
        """Invalidate all cached entries for a given run.

        Called on gate passage, feedback iteration, or CEO override.
        Returns the number of entries removed.
        """
        to_delete = [
            k for k, v in self._store.items()
            if v.run_id == run_id
        ]
        for k in to_delete:
            del self._store[k]
        return len(to_delete)

    def clear(self) -> None:
        """Clear the entire cache."""
        self._store.clear()

    @property
    def size(self) -> int:
        """Number of entries currently in the cache."""
        return len(self._store)

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        now = time.time()
        active = sum(1 for e in self._store.values() if (now - e.timestamp) < self.ttl)
        expired = len(self._store) - active
        return {
            "total_entries": len(self._store),
            "active": active,
            "expired": expired,
            "ttl_seconds": self.ttl,
        }
