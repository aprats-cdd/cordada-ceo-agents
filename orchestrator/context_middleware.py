"""
CONTEXT Middleware — intercept agent questions in interactive mode,
search internal sources (Drive, Gmail, Slack), and suggest answers.

Uses the same tool executors from ``tools.py`` so the proxy fallback
(Claude with MCP) is always available — even without direct API
credentials configured.

Flow:
    1. Agent produces a response containing questions for the user.
    2. ``suggest_answers()`` extracts the questions, searches all
       sources via the existing tool executors, and returns a
       formatted suggestion block.
    3. The user confirms, corrects, or answers manually.
    4. ``compile_confirmed_answers()`` turns the confirmed suggestions
       into a plain-text reply for the agent.
"""

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SourceHit:
    """A single search result from an internal source."""
    answer: str
    source_type: str        # "Drive", "Gmail", "Slack"
    source_name: str        # document title, email subject, channel name…
    date: str               # ISO date or human-readable
    confidence: str         # "Alta", "Media", "Baja"


@dataclass
class QuestionSuggestion:
    """Suggestions found for one question."""
    question: str
    hits: list[SourceHit] = field(default_factory=list)


@dataclass
class ContextResult:
    """Full result of a CONTEXT middleware pass."""
    suggestions: list[QuestionSuggestion] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Question extraction
# ---------------------------------------------------------------------------

_QUESTION_RE = re.compile(
    r"""
    (?:                          # optional leading numbering / bullet
        ^\s*(?:\d+[.)]\s*|[-*]\s*)
    )?
    (.+?\?)                      # capture up to the question mark
    """,
    re.MULTILINE | re.VERBOSE,
)


def extract_questions(text: str) -> list[str]:
    """Extract question-like sentences from agent output.

    Heuristic — intentionally over-extracts (better to suggest too
    much than too little).
    """
    questions: list[str] = []
    seen: set[str] = set()
    for m in _QUESTION_RE.finditer(text):
        q = m.group(1).strip()
        # Skip very short or duplicate questions
        if len(q) < 10 or q.lower() in seen:
            continue
        seen.add(q.lower())
        questions.append(q)
    return questions


# ---------------------------------------------------------------------------
# Source search helpers — delegate to tools.py executors
# ---------------------------------------------------------------------------

def _keywords_from_question(question: str) -> str:
    """Extract keywords from a question for API search queries.

    Strips common Spanish interrogative words and short noise words.
    """
    stopwords = {
        "cuál", "cual", "cuáles", "cuales", "qué", "que", "quién",
        "quien", "quiénes", "quienes", "cómo", "como", "dónde",
        "donde", "cuándo", "cuando", "cuánto", "cuanto", "cuántos",
        "cuantos", "por", "para", "del", "los", "las", "una", "uno",
        "unos", "unas", "con", "sin", "sobre", "entre", "pero",
        "hay", "tiene", "son", "está", "están", "ser", "fue",
        "desde", "hasta", "más", "menos", "este", "esta", "estos",
        "estas", "ese", "esa", "esos", "esas", "aquel", "aquella",
        "el", "la", "de", "en", "es", "al", "lo", "se", "su",
        "nos", "les", "te", "me", "le", "ya", "si", "no",
    }
    tokens = re.findall(r"\w+", question.lower())
    keywords = [t for t in tokens if t not in stopwords and len(t) > 2]
    return " ".join(keywords)


def _parse_tool_result(raw: str) -> dict:
    """Parse a JSON tool result string, returning {} on failure."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _search_drive(query: str) -> list[SourceHit]:
    """Search Google Drive via tools.py executor (with proxy fallback)."""
    from .tools import execute_tool

    raw = execute_tool("search_google_drive", {"query": query, "max_results": 5})
    data = _parse_tool_result(raw)

    if "error" in data:
        logger.warning("Drive search error: %s", data["error"])
        return []

    hits: list[SourceHit] = []
    for doc in data.get("results", []):
        hits.append(SourceHit(
            answer=doc.get("name", ""),
            source_type="Drive",
            source_name=doc.get("name", ""),
            date=doc.get("modified", "")[:10],
            confidence="Media",
        ))
    return hits


def _search_gmail(query: str) -> list[SourceHit]:
    """Search Gmail via tools.py executor (with proxy fallback)."""
    from .tools import execute_tool

    raw = execute_tool("search_gmail", {"query": query, "max_results": 5})
    data = _parse_tool_result(raw)

    if "error" in data:
        logger.warning("Gmail search error: %s", data["error"])
        return []

    hits: list[SourceHit] = []
    for email in data.get("results", []):
        hits.append(SourceHit(
            answer=email.get("snippet", ""),
            source_type="Gmail",
            source_name=f"{email.get('subject', '')} (de {email.get('from', '')})",
            date=email.get("date", ""),
            confidence="Media",
        ))
    return hits


def _search_slack(query: str) -> list[SourceHit]:
    """Search Slack via tools.py executor (with proxy fallback)."""
    from .tools import execute_tool

    raw = execute_tool("search_slack", {"query": query, "max_results": 5})
    data = _parse_tool_result(raw)

    if "error" in data:
        logger.warning("Slack search error: %s", data["error"])
        return []

    hits: list[SourceHit] = []
    for msg in data.get("results", []):
        hits.append(SourceHit(
            answer=(msg.get("text") or "")[:300],
            source_type="Slack",
            source_name=f"#{msg.get('channel', '')} (@{msg.get('user', '')})",
            date=msg.get("timestamp", ""),
            confidence="Baja",
        ))
    return hits


def _assign_confidence(hits: list[SourceHit]) -> None:
    """Upgrade confidence when multiple sources agree or source is formal."""
    for h in hits:
        if h.source_type == "Drive":
            h.confidence = "Alta"
        elif h.source_type == "Gmail":
            h.confidence = "Media"
    # Multiple source types confirming → bump
    source_types = {h.source_type for h in hits}
    if len(source_types) > 1:
        for h in hits:
            if h.confidence == "Media":
                h.confidence = "Alta"


def _search_all_sources(question: str) -> list[SourceHit]:
    """Search Drive, Gmail, and Slack for a question."""
    keywords = _keywords_from_question(question)
    if not keywords:
        return []

    hits: list[SourceHit] = []
    hits.extend(_search_drive(keywords))
    hits.extend(_search_gmail(keywords))
    hits.extend(_search_slack(keywords))
    _assign_confidence(hits)
    return hits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def suggest_answers(assistant_text: str) -> ContextResult | None:
    """Analyse an agent's response, search internal sources, return suggestions.

    Args:
        assistant_text: The raw text output from the agent.

    Returns:
        A ``ContextResult`` with suggestions and unanswered questions,
        or ``None`` if the agent text contained no questions.
    """
    questions = extract_questions(assistant_text)
    if not questions:
        return None

    suggestions: list[QuestionSuggestion] = []
    unanswered: list[str] = []

    for q in questions:
        hits = _search_all_sources(q)
        if hits:
            suggestions.append(QuestionSuggestion(question=q, hits=hits))
        else:
            unanswered.append(q)

    if not suggestions:
        return None

    return ContextResult(suggestions=suggestions, unanswered=unanswered)


def format_suggestions(result: ContextResult) -> str:
    """Format a ``ContextResult`` into the user-facing display string."""
    lines: list[str] = []
    lines.append("\n  CONTEXT encontro respuestas sugeridas:\n")

    for qs in result.suggestions:
        lines.append(f"  **{qs.question}**")
        # Show best hit (first) prominently; others as additional sources
        for i, hit in enumerate(qs.hits):
            prefix = "  -> Sugerencia" if i == 0 else "     Tambien"
            lines.append(f"  {prefix}: {hit.answer}")
            lines.append(f"     Fuente: {hit.source_type} - {hit.source_name}")
            lines.append(f"     Fecha: {hit.date}")
            lines.append(f"     Confianza: {hit.confidence}")
        lines.append("")

    if result.unanswered:
        lines.append("  No encontre respuesta para:")
        for q in result.unanswered:
            lines.append(f"  - {q}")
        lines.append("")

    lines.append("  Opciones:")
    lines.append("    1. Confirmar todas las sugerencias")
    lines.append("    2. Corregir una sugerencia")
    lines.append("    3. Responder manualmente")

    return "\n".join(lines)


def compile_confirmed_answers(result: ContextResult) -> str:
    """Turn confirmed suggestions into a plain-text reply for the agent."""
    parts: list[str] = []
    for qs in result.suggestions:
        best = qs.hits[0]
        parts.append(f"{qs.question}\n-> {best.answer}")
    return "\n\n".join(parts)
