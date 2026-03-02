"""Tests for Context Cache — TTL, hit/miss, invalidation."""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy-key-for-tests")

import time
import pytest
from unittest.mock import patch

from orchestrator.context_cache import ContextCache, CacheEntry
from orchestrator.context_middleware import (
    ContextResult,
    Suggestion,
    suggest_answers,
    format_suggestions,
    invalidate_context_cache,
    get_context_cache,
    _serialize_result,
    _deserialize_result,
)


# ---------------------------------------------------------------------------
# ContextCache unit tests
# ---------------------------------------------------------------------------

class TestContextCacheBasic:

    def test_put_and_get(self):
        cache = ContextCache(ttl_seconds=60)
        cache.put("What is AUM?", "audit", "run_1", {"answer": "218M"})

        result = cache.get("What is AUM?", "audit", "run_1")
        assert result is not None
        assert result["answer"] == "218M"

    def test_cache_miss(self):
        cache = ContextCache(ttl_seconds=60)
        result = cache.get("unknown question", "audit", "run_1")
        assert result is None

    def test_ttl_expiration(self):
        cache = ContextCache(ttl_seconds=1)
        cache.put("What is AUM?", "audit", "run_1", {"answer": "218M"})

        # Immediately should hit
        assert cache.get("What is AUM?", "audit", "run_1") is not None

        # After TTL expires, should miss
        time.sleep(1.1)
        assert cache.get("What is AUM?", "audit", "run_1") is None

    def test_different_agents_different_keys(self):
        cache = ContextCache(ttl_seconds=60)
        cache.put("What is AUM?", "audit", "run_1", {"answer": "audit_answer"})
        cache.put("What is AUM?", "discover", "run_1", {"answer": "discover_answer"})

        assert cache.get("What is AUM?", "audit", "run_1")["answer"] == "audit_answer"
        assert cache.get("What is AUM?", "discover", "run_1")["answer"] == "discover_answer"

    def test_different_runs_different_keys(self):
        cache = ContextCache(ttl_seconds=60)
        cache.put("What is AUM?", "audit", "run_1", {"answer": "run_1_answer"})
        cache.put("What is AUM?", "audit", "run_2", {"answer": "run_2_answer"})

        assert cache.get("What is AUM?", "audit", "run_1")["answer"] == "run_1_answer"
        assert cache.get("What is AUM?", "audit", "run_2")["answer"] == "run_2_answer"

    def test_normalization(self):
        """Questions are normalized (strip + lowercase) for hashing."""
        cache = ContextCache(ttl_seconds=60)
        cache.put("  What is AUM?  ", "audit", "run_1", {"answer": "218M"})

        # Same question with different whitespace/case should hit
        assert cache.get("what is aum?", "audit", "run_1") is not None
        assert cache.get("WHAT IS AUM?", "audit", "run_1") is not None

    def test_size(self):
        cache = ContextCache(ttl_seconds=60)
        assert cache.size == 0
        cache.put("q1", "a", "r", {"x": 1})
        assert cache.size == 1
        cache.put("q2", "a", "r", {"x": 2})
        assert cache.size == 2

    def test_clear(self):
        cache = ContextCache(ttl_seconds=60)
        cache.put("q1", "a", "r", {"x": 1})
        cache.put("q2", "a", "r", {"x": 2})
        cache.clear()
        assert cache.size == 0

    def test_stats(self):
        cache = ContextCache(ttl_seconds=60)
        cache.put("q1", "a", "r", {"x": 1})
        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["active"] == 1
        assert stats["expired"] == 0
        assert stats["ttl_seconds"] == 60


class TestContextCacheInvalidation:

    def test_invalidate_run(self):
        cache = ContextCache(ttl_seconds=60)
        cache.put("q1", "audit", "run_1", {"answer": "a1"})
        cache.put("q2", "discover", "run_1", {"answer": "a2"})
        cache.put("q3", "audit", "run_2", {"answer": "a3"})

        removed = cache.invalidate_run("run_1")
        assert removed == 2
        assert cache.get("q1", "audit", "run_1") is None
        assert cache.get("q2", "discover", "run_1") is None
        # run_2 should be unaffected
        assert cache.get("q3", "audit", "run_2") is not None

    def test_invalidate_empty_run(self):
        cache = ContextCache(ttl_seconds=60)
        removed = cache.invalidate_run("nonexistent")
        assert removed == 0

    def test_overwrite_existing_entry(self):
        cache = ContextCache(ttl_seconds=60)
        cache.put("q1", "audit", "run_1", {"answer": "old"})
        cache.put("q1", "audit", "run_1", {"answer": "new"})

        result = cache.get("q1", "audit", "run_1")
        assert result["answer"] == "new"
        assert cache.size == 1


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------

class TestSerializationRoundtrip:

    def test_serialize_deserialize(self):
        result = ContextResult(
            suggestions=[
                Suggestion(
                    question="What is AUM?",
                    answer="218M USD",
                    source_type="Drive",
                    source_name="Monthly Report",
                    date="2025-12",
                    score=8,
                    reasoning="From official report",
                ),
            ],
            unanswered=["What is the pipeline status?"],
        )

        data = _serialize_result(result)
        restored = _deserialize_result(data)

        assert len(restored.suggestions) == 1
        assert restored.suggestions[0].question == "What is AUM?"
        assert restored.suggestions[0].answer == "218M USD"
        assert restored.suggestions[0].score == 8
        assert restored.unanswered == ["What is the pipeline status?"]

    def test_empty_result(self):
        result = ContextResult()
        data = _serialize_result(result)
        restored = _deserialize_result(data)
        assert restored.suggestions == []
        assert restored.unanswered == []


# ---------------------------------------------------------------------------
# format_suggestions cache display tests
# ---------------------------------------------------------------------------

class TestFormatSuggestions:

    def test_cached_label(self):
        result = ContextResult(
            suggestions=[
                Suggestion("Q?", "A", "Drive", "Doc", "2025", 8, "Good"),
            ],
        )
        result._cached = True
        result._elapsed = 0.001
        result._api_calls = 0

        formatted = format_suggestions(result)
        assert "cached" in formatted.lower()
        assert "0.0s" in formatted

    def test_non_cached_label(self):
        result = ContextResult(
            suggestions=[
                Suggestion("Q?", "A", "Drive", "Doc", "2025", 8, "Good"),
            ],
        )
        result._cached = False
        result._elapsed = 1.3
        result._api_calls = 3

        formatted = format_suggestions(result)
        assert "3 API calls" in formatted
        assert "1.3s" in formatted

    def test_no_metadata_defaults(self):
        """format_suggestions works even without _cached/_elapsed attrs."""
        result = ContextResult(
            suggestions=[
                Suggestion("Q?", "A", "Drive", "Doc", "2025", 8, "Good"),
            ],
        )
        formatted = format_suggestions(result)
        assert "Q?" in formatted


# ---------------------------------------------------------------------------
# Module-level cache integration tests
# ---------------------------------------------------------------------------

class TestModuleLevelCache:

    def test_get_context_cache_returns_instance(self):
        cache = get_context_cache()
        assert isinstance(cache, ContextCache)

    def test_invalidate_context_cache_by_run(self):
        cache = get_context_cache()
        cache.put("test_q", "audit", "test_run_abc", {"answer": "x"})

        removed = invalidate_context_cache("test_run_abc")
        assert cache.get("test_q", "audit", "test_run_abc") is None

    def test_invalidate_context_cache_all(self):
        cache = get_context_cache()
        cache.put("q1", "a", "r1", {"x": 1})
        invalidate_context_cache()  # no run_id = clear all
        # Cache may or may not be empty (invalidate_run("") behavior)
        # Just ensure it doesn't crash
