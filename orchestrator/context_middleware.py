"""
CONTEXT Middleware — intercept agent questions in interactive mode,
search internal sources (Drive, Gmail, Slack), and suggest answers.

Flow:
    1. Agent produces a response containing questions for the user.
    2. ``suggest_answers()`` extracts the questions, searches all
       configured sources, and returns a formatted suggestion block.
    3. The user confirms, corrects, or answers manually.
    4. ``compile_confirmed_answers()`` turns the confirmed suggestions
       into a plain-text reply for the agent.
"""

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
    source_type: str        # "Drive", "Gmail", "Slack", "Calendar"
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
# Source search helpers
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


def _search_drive(query: str) -> list[SourceHit]:
    """Search Google Drive and return SourceHit list."""
    from .google_client import search_drive, is_google_configured

    if not is_google_configured():
        return []

    hits: list[SourceHit] = []
    for doc in search_drive(query):
        hits.append(SourceHit(
            answer=doc["snippet"] or doc["title"],
            source_type="Drive",
            source_name=doc["title"],
            date=doc["date"],
            confidence="Media",
        ))
    return hits


def _search_gmail(query: str) -> list[SourceHit]:
    """Search Gmail and return SourceHit list."""
    from .google_client import search_gmail, is_google_configured

    if not is_google_configured():
        return []

    hits: list[SourceHit] = []
    for email in search_gmail(query):
        hits.append(SourceHit(
            answer=email["snippet"],
            source_type="Gmail",
            source_name=f"{email['subject']} (de {email['from']})",
            date=email["date"],
            confidence="Media",
        ))
    return hits


def _search_slack(query: str) -> list[SourceHit]:
    """Search Slack messages and return SourceHit list."""
    from .slack_client import search_slack, is_slack_configured

    if not is_slack_configured():
        return []

    hits: list[SourceHit] = []
    for msg in search_slack(query):
        hits.append(SourceHit(
            answer=msg["text"],
            source_type="Slack",
            source_name=f"#{msg['channel']} (@{msg['user']})",
            date=msg["date"],
            confidence="Baja",
        ))
    return hits


def _assign_confidence(hits: list[SourceHit]) -> None:
    """Upgrade confidence when multiple sources agree or source is formal."""
    # Drive documents are treated as more authoritative
    for h in hits:
        if h.source_type == "Drive":
            h.confidence = "Alta"
        elif h.source_type == "Gmail":
            h.confidence = "Media"
        # If we have hits from more than one source type, bump to Alta
    source_types = {h.source_type for h in hits}
    if len(source_types) > 1:
        for h in hits:
            if h.confidence == "Media":
                h.confidence = "Alta"


def _search_all_sources(question: str, sources: set[str]) -> list[SourceHit]:
    """Search all configured sources for a question."""
    keywords = _keywords_from_question(question)
    if not keywords:
        return []

    hits: list[SourceHit] = []

    if "drive" in sources:
        hits.extend(_search_drive(keywords))
    if "gmail" in sources:
        hits.extend(_search_gmail(keywords))
    if "slack" in sources:
        hits.extend(_search_slack(keywords))

    _assign_confidence(hits)
    return hits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_availability(sources: set[str]) -> tuple[bool, str]:
    """Check if at least one source is properly configured.

    Returns:
        (available, warning_message)
    """
    from .google_client import is_google_configured
    from .slack_client import is_slack_configured

    available_sources: list[str] = []
    missing: list[str] = []

    if "drive" in sources or "gmail" in sources:
        if is_google_configured():
            if "drive" in sources:
                available_sources.append("Drive")
            if "gmail" in sources:
                available_sources.append("Gmail")
        else:
            missing.append("Google (GOOGLE_CREDENTIALS_PATH + GOOGLE_DELEGATE_EMAIL)")

    if "slack" in sources:
        if is_slack_configured():
            available_sources.append("Slack")
        else:
            missing.append("Slack (SLACK_BOT_TOKEN)")

    if not available_sources:
        warning = (
            "  CONTEXT middleware habilitado pero las APIs no estan configuradas.\n"
            "    Para configurar: edita .env con "
            + " y ".join(missing)
            + "\n    Continuando sin CONTEXT..."
        )
        return False, warning

    if missing:
        warning = (
            "  CONTEXT: fuentes activas: "
            + ", ".join(available_sources)
            + ". No configuradas: "
            + ", ".join(missing)
        )
        return True, warning

    return True, ""


def suggest_answers(
    assistant_text: str,
    sources: set[str] | None = None,
) -> ContextResult | None:
    """Analyse an agent's response, search internal sources, return suggestions.

    Args:
        assistant_text: The raw text output from the agent.
        sources: Which sources to search (default: {"drive", "gmail", "slack"}).

    Returns:
        A ``ContextResult`` with suggestions and unanswered questions,
        or ``None`` if the agent text contained no questions.
    """
    sources = sources or {"drive", "gmail", "slack"}

    questions = extract_questions(assistant_text)
    if not questions:
        return None

    suggestions: list[QuestionSuggestion] = []
    unanswered: list[str] = []

    for q in questions:
        hits = _search_all_sources(q, sources)
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
