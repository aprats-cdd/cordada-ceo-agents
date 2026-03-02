"""
Agent Runner — Execute individual agents via the Claude API.

Each agent runs in its own API call with isolated context.
The agent's markdown prompt becomes the system message.
The user's input becomes the first user message.

Programmatic usage:
    from orchestrator.agent_runner import run_agent
    output = run_agent("discover", "deuda privada LatAm")

CLI usage:
    python -m orchestrator.agent_runner --agent discover --input "deuda privada LatAm"
"""

import argparse
import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic

from domain.model import TokenUsage

from .config import (
    ANTHROPIC_API_KEY,
    AGENTS,
    OUTPUTS_DIR,
    CONTEXT_ENABLED,
    get_model,
    get_agent_prompt,
)
from .tools import get_tools_for_agent, has_custom_tools, execute_tool

logger = logging.getLogger(__name__)

# Default max tokens for agent responses
MAX_TOKENS = 16_384

# Retry configuration for transient API errors
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2  # seconds


# ---------------------------------------------------------------------------
# RunMetrics — observability for every agent invocation (Fix #7)
# ---------------------------------------------------------------------------

@dataclass
class RunMetrics:
    """Metrics collected during a single agent run."""
    agent: str = ""
    model: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    tool_rounds: int = 0
    proxy_calls: int = 0
    token_usage: TokenUsage | None = None  # Aggregated after run

    def __str__(self) -> str:
        cost_str = f", ${self.token_usage.cost_usd:.4f}" if self.token_usage else ""
        return (
            f"[{self.agent}] {self.model} — "
            f"{self.latency_ms}ms, "
            f"{self.input_tokens}+{self.output_tokens} tokens{cost_str}, "
            f"{self.tool_calls} tool calls ({self.tool_rounds} rounds)"
        )


# Module-level metrics for the last run (inspectable by callers)
last_metrics: RunMetrics = RunMetrics()


# ---------------------------------------------------------------------------
# Thread-safe lazy singleton for Anthropic client (Fix #11)
# ---------------------------------------------------------------------------

_client: anthropic.Anthropic | None = None
_client_lock = threading.Lock()


def _get_client() -> anthropic.Anthropic:
    """Get or create the shared Anthropic client (thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-check locking
                _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _call_api_with_retry(
    client: anthropic.Anthropic,
    *,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
) -> anthropic.types.Message:
    """Call the Messages API with retry on transient errors."""
    for attempt in range(_MAX_RETRIES):
        try:
            kwargs: dict = dict(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            if tools:
                kwargs["tools"] = tools
            return client.messages.create(**kwargs)
        except anthropic.APIConnectionError as e:
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
            logger.warning("API connection error (attempt %d/%d), retrying in %ds: %s",
                           attempt + 1, _MAX_RETRIES, wait, e)
            time.sleep(wait)
        except anthropic.RateLimitError as e:
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
            logger.warning("Rate limited (attempt %d/%d), retrying in %ds: %s",
                           attempt + 1, _MAX_RETRIES, wait, e)
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            # 5xx errors are transient; 4xx (except 429) are not
            if e.status_code >= 500 and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning("API server error %d (attempt %d/%d), retrying in %ds",
                               e.status_code, attempt + 1, _MAX_RETRIES, wait)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Unreachable: retry loop exhausted")


def run_agent(
    agent_name: str,
    user_input: str,
    output_path: Path | None = None,
    interactive: bool = False,
    save: bool = True,
    verbose: bool = True,
    no_context: bool = False,
    max_output_tokens: int | None = None,
) -> str:
    """
    Run a single agent with the given input.

    Args:
        agent_name: Name of the agent (e.g., 'discover', 'compile')
        user_input: The user's input text
        output_path: Optional path to save the output
        interactive: If True, enable multi-turn conversation
        save: If True, auto-save output to disk (default: True)
        verbose: If True, print progress banners (default: True)
        no_context: If True, disable CONTEXT middleware even in interactive mode

    Returns:
        The agent's response text
    """
    global last_metrics
    metrics = RunMetrics(agent=agent_name, model=get_model(agent_name))
    start_time = time.monotonic()

    system_prompt = get_agent_prompt(agent_name)
    model = metrics.model
    client = _get_client()

    # Get tools for this agent (may be empty)
    tools = get_tools_for_agent(agent_name)

    if verbose:
        print(f"\n{'='*60}")
        print(f"  AGENT: {agent_name.upper()}")
        print(f"  MODEL: {model}")
        print(f"  LAYER: {AGENTS[agent_name]['layer']}")
        if tools:
            tool_names = [t.get("name", t.get("type", "?")) for t in tools]
            print(f"  TOOLS: {', '.join(tool_names)}")
        print(f"{'='*60}\n")

    if interactive:
        response = _run_interactive(
            client, model, system_prompt, user_input, agent_name, tools,
            no_context=no_context,
        )
    else:
        messages = [{"role": "user", "content": user_input}]

        message = _call_api_with_retry(
            client,
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
            tools=tools or None,
        )

        # Accumulate token counts from initial call
        metrics.input_tokens += getattr(message.usage, "input_tokens", 0)
        metrics.output_tokens += getattr(message.usage, "output_tokens", 0)

        # Tool execution loop: when the model requests tool use, execute
        # the tool and send the result back until we get a final response.
        response = _handle_tool_loop(
            client, model, system_prompt, messages, message, tools, agent_name, verbose,
            metrics=metrics,
        )

    metrics.latency_ms = int((time.monotonic() - start_time) * 1000)

    # Compute aggregate TokenUsage for cost governance
    metrics.token_usage = TokenUsage(
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        model=model,
        cost_usd=TokenUsage.from_api_response(
            {"usage": {"input_tokens": metrics.input_tokens, "output_tokens": metrics.output_tokens}},
            model,
        ).cost_usd,
    )

    last_metrics = metrics

    # Cost governor: truncate output if it exceeds the per-agent token cap
    if max_output_tokens and metrics.output_tokens > max_output_tokens:
        # Approximate char count from tokens (4 chars/token)
        max_chars = max_output_tokens * 4
        if len(response) > max_chars:
            response = response[:max_chars] + (
                "\n\n[OUTPUT TRUNCATED BY COST GOVERNOR — "
                f"exceeded {max_output_tokens} output tokens]"
            )
            if verbose:
                logger.warning(
                    "Agent '%s' output truncated: %d tokens > %d max",
                    agent_name, metrics.output_tokens, max_output_tokens,
                )

    if verbose:
        logger.info("Metrics: %s", metrics)

    # Save output
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(response, encoding="utf-8")
        if verbose:
            print(f"\n  Output saved to: {output_path}")
    elif save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        auto_path = OUTPUTS_DIR / f"{agent_name}_{timestamp}.md"
        auto_path.write_text(response, encoding="utf-8")
        if verbose:
            print(f"\n  Output saved to: {auto_path}")

    return response


def _extract_text(message: anthropic.types.Message) -> str:
    """Extract all text content blocks from a message, joined."""
    text_blocks = [b.text for b in message.content if hasattr(b, "text")]
    return "\n\n".join(text_blocks) if text_blocks else ""


def _handle_tool_loop(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    messages: list[dict],
    message: anthropic.types.Message,
    tools: list[dict],
    agent_name: str,
    verbose: bool,
    max_tool_rounds: int = 10,
    metrics: RunMetrics | None = None,
) -> str:
    """
    Handle the tool execution loop.

    When the API returns stop_reason="tool_use", execute the requested tools
    locally, send results back, and continue until "end_turn".

    Server tools (web_search) are handled by Anthropic server-side and don't
    enter this loop — they resolve within a single API call.
    """
    rounds = 0

    while message.stop_reason == "tool_use" and rounds < max_tool_rounds:
        rounds += 1

        # Collect all tool_use blocks from the response
        tool_uses = [b for b in message.content if b.type == "tool_use"]

        if verbose and tool_uses:
            names = [t.name for t in tool_uses]
            print(f"  Tools requested: {', '.join(names)}")

        # Execute each tool and collect results
        tool_results = []
        for tool_use in tool_uses:
            if verbose:
                print(f"    Executing: {tool_use.name}({tool_use.input})")

            result = execute_tool(tool_use.name, tool_use.input)

            if verbose:
                preview = result[:120] + "..." if len(result) > 120 else result
                print(f"    Result: {preview}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

            if metrics:
                metrics.tool_calls += 1

        # Send the assistant's response (with tool_use blocks) and our
        # tool_result messages back to the API to continue
        messages.append({"role": "assistant", "content": message.content})
        messages.append({"role": "user", "content": tool_results})

        message = _call_api_with_retry(
            client,
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
            tools=tools or None,
        )

        # Accumulate token counts from tool-loop iterations
        if metrics:
            metrics.input_tokens += getattr(message.usage, "input_tokens", 0)
            metrics.output_tokens += getattr(message.usage, "output_tokens", 0)

    if metrics:
        metrics.tool_rounds = rounds

    if rounds >= max_tool_rounds:
        logger.warning(
            "Agent '%s' hit max tool rounds (%d). Returning partial response.",
            agent_name, max_tool_rounds,
        )

    # Extract final text response
    text = _extract_text(message)
    if not text:
        raise RuntimeError(
            f"Agent '{agent_name}' returned no text content after {rounds} tool rounds. "
            f"Stop reason: {message.stop_reason}"
        )
    return text


def _run_interactive(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    initial_input: str,
    agent_name: str,
    tools: list[dict] | None = None,
    no_context: bool = False,
) -> str:
    """
    Run an agent in interactive mode (multi-turn conversation).
    The agent asks questions, you answer, it executes when ready.
    Tools are available during the conversation.

    CONTEXT middleware is active by default — it intercepts each agent
    question, searches Drive/Gmail/Slack, and offers suggested answers
    before prompting for manual input.  Pass *no_context=True* to disable.
    """
    messages = [{"role": "user", "content": initial_input}]
    all_responses: list[str] = []

    # --- CONTEXT middleware (active by default) ---
    # Uses the same tool executors as agents, so the proxy fallback
    # (Claude with MCP) is always available — no credentials required.
    use_context = not no_context and CONTEXT_ENABLED
    if no_context:
        pass
    elif not CONTEXT_ENABLED:
        print("\n  CONTEXT deshabilitado via CONTEXT_ENABLED=false en .env\n")

    print("  Interactive mode. Type your answers. Type 'done' to finish.\n")

    while True:
        message = _call_api_with_retry(
            client,
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
            tools=tools or None,
        )

        # Handle any tool calls before showing the response
        if message.stop_reason == "tool_use":
            assistant_text = _handle_tool_loop(
                client, model, system_prompt, messages, message,
                tools or [], agent_name, verbose=True,
            )
        else:
            assistant_text = _extract_text(message)

        all_responses.append(assistant_text)

        print(f"\n  {agent_name.upper()}:\n")
        print(assistant_text)

        if message.stop_reason == "end_turn":
            user_reply = _prompt_with_context(
                assistant_text,
                agent_name=agent_name,
                use_context=use_context,
            )
            if user_reply is None:  # user typed 'done'
                break
            if not user_reply:
                continue

            messages.append({"role": "assistant", "content": assistant_text})
            messages.append({"role": "user", "content": user_reply})

    # Return last response (the final deliverable)
    if len(all_responses) == 1:
        return all_responses[0]
    return all_responses[-1]


def _prompt_with_context(
    assistant_text: str,
    *,
    agent_name: str,
    use_context: bool,
) -> str | None:
    """Prompt the user, optionally showing CONTEXT suggestions first.

    Returns:
        The user's reply string, or ``None`` when the user types 'done'.
        An empty string means "skip" (no input).
    """
    if use_context:
        from .context_middleware import (
            suggest_answers,
            format_suggestions,
            compile_confirmed_answers,
        )

        result = suggest_answers(assistant_text, agent_name=agent_name)
        if result:
            print(format_suggestions(result))
            choice = input("\n  Tu eleccion (1/2/3): ").strip()
            if choice == "1":
                reply = compile_confirmed_answers(result)
                print(f"\n  -> Pasando respuestas confirmadas al agente...\n")
                return reply
            elif choice == "2":
                return input("  Correccion: ").strip()
            # choice == "3" or anything else → fall through to manual input

    user_reply = input("\n  Your response (or 'done' to finish): ").strip()
    if user_reply.lower() == "done":
        return None
    return user_reply


def main():
    parser = argparse.ArgumentParser(
        description="Run a cordada-ceo-agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m orchestrator.agent_runner --agent discover --input "deuda privada LatAm"
  python -m orchestrator.agent_runner --agent compile --input-file ./notes.md
  python -m orchestrator.agent_runner --agent audit --input-file ./draft.md -i

Available agents:
  discover    — Research and rank sources
  extract     — Pull key data from sources
  validate    — Verify accuracy and consistency
  compile     — Generate structured document
  audit       — Multi-expert panel review
  reflect     — Strategic stress-test
  decide      — Present options with trade-offs
  distribute  — Adapt deliverable to channel
  collect_iterate — Parse feedback and re-inject
  context         — Search internal sources to suggest answers
        """,
    )

    parser.add_argument(
        "--agent",
        required=True,
        choices=list(AGENTS.keys()),
        help="Which agent to run",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Direct text input for the agent",
    )
    parser.add_argument(
        "--input-file",
        type=str,
        help="Path to a file to use as input",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to save the output (default: outputs/<agent>_<timestamp>.md)",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run in interactive mode (multi-turn conversation)",
    )
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="Disable CONTEXT middleware (skip Drive/Gmail/Slack suggestions in interactive mode)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available agents",
    )

    args = parser.parse_args()

    if args.list:
        print("\nAvailable agents:\n")
        for name, info in sorted(AGENTS.items(), key=lambda x: x[1]["order"]):
            model_tag = "+" if name in {"audit", "reflect", "decide"} else " "
            print(f"  {model_tag} {info['order']:02d}. {name:<18} [{info['layer']:<10}] {info['description']}")
        print("\n+ = Uses premium model (Opus)")
        return

    # Resolve input
    if args.input_file:
        user_input = Path(args.input_file).read_text(encoding="utf-8")
    elif args.input:
        user_input = args.input
    elif args.interactive:
        user_input = "Estoy listo. Hazme las preguntas para comenzar."
    else:
        print("Error: Provide --input, --input-file, or use -i for interactive mode")
        sys.exit(1)

    # Resolve output path
    output_path = Path(args.output) if args.output else None

    # Run
    response = run_agent(
        agent_name=args.agent,
        user_input=user_input,
        output_path=output_path,
        interactive=args.interactive,
        no_context=args.no_context,
    )

    if not args.interactive:
        print(f"\n  {args.agent.upper()} response:\n")
        print(response)


if __name__ == "__main__":
    main()
