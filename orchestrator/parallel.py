"""
Parallel Execution — fan-out/fan-in for EXTRACT agent.

When DISCOVER produces multiple sources, EXTRACT can process them in parallel
instead of sequentially.  This is like executing trades simultaneously instead
of one by one — latency is alpha.

Uses asyncio with thread pool (since run_agent is synchronous I/O-bound).
Budget is checked before each parallel extraction call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import Any

from domain.contracts import SourceCard, Extraction, ExtractOutput
from domain.model import CostBudget, TokenUsage

logger = logging.getLogger(__name__)

# Minimum sources to trigger fan-out (below this, sequential is fine)
FAN_OUT_THRESHOLD = 3


async def fan_out_extract(
    sources: list[SourceCard],
    run_agent_fn,
    max_concurrent: int = 5,
    cost_budget: CostBudget | None = None,
    cumulative_cost: float = 0.0,
    pipeline_context: str = "",
    schema_instruction: str = "",
    output_dir=None,
    max_output_tokens: int | None = None,
) -> tuple[ExtractOutput, str, list[TokenUsage]]:
    """Execute EXTRACT in parallel for each source, respecting cost budget.

    Args:
        sources: SourceCards from DISCOVER output.
        run_agent_fn: The run_agent function (synchronous).
        max_concurrent: Max concurrent extractions (semaphore limit).
        cost_budget: Budget to check before each call.
        cumulative_cost: Current cumulative cost entering this step.
        pipeline_context: Context prefix for the EXTRACT prompt.
        schema_instruction: Schema instruction to append to prompt.
        output_dir: Directory for saving individual extract outputs.
        max_output_tokens: Per-agent output token cap.

    Returns:
        Tuple of (merged ExtractOutput, merged raw response text, list of TokenUsage).
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    cost_lock = asyncio.Lock()
    running_cost = cumulative_cost
    token_usages: list[TokenUsage] = []
    results: list[tuple[str, int]] = []  # (raw_response, source_index)

    start_time = time.monotonic()

    async def extract_one(source: SourceCard, idx: int) -> tuple[str, int] | None:
        nonlocal running_cost

        async with semaphore:
            # Check budget before each call
            if cost_budget:
                async with cost_lock:
                    status = cost_budget.check(running_cost)
                    if status == "exceeded":
                        logger.warning(
                            "Budget exceeded before extract[%d] (%s): $%.2f / $%.2f",
                            idx, source.title, running_cost, cost_budget.max_total_usd,
                        )
                        return None

            # Build per-source input
            source_json = json.dumps(asdict(source), ensure_ascii=False, indent=2)
            agent_input = (
                f"{pipeline_context}\n\n"
                f"**Fuente a extraer ({idx + 1}/{len(sources)}):**\n\n"
                f"```json\n{source_json}\n```"
            )
            if schema_instruction:
                agent_input += schema_instruction

            # Run in thread pool (run_agent is sync)
            from .agent_runner import run_agent, last_metrics

            output_path = None
            if output_dir:
                output_path = output_dir / f"extract_source_{idx:02d}.md"

            response = await asyncio.to_thread(
                run_agent,
                "extract",
                agent_input,
                output_path=output_path,
                interactive=False,
                save=False,
                verbose=False,
                max_output_tokens=max_output_tokens,
            )

            # Capture metrics (best-effort — may be overwritten by concurrent calls)
            if last_metrics and last_metrics.token_usage:
                async with cost_lock:
                    running_cost += last_metrics.token_usage.cost_usd
                    token_usages.append(last_metrics.token_usage)

            return (response, idx)

    # Launch all extractions
    tasks = [extract_one(source, i) for i, source in enumerate(sources)]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect successful results
    successful_responses: list[tuple[str, int]] = []
    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            logger.warning("Extract[%d] failed: %s", i, result)
        elif result is None:
            logger.warning("Extract[%d] skipped (budget exceeded)", i)
        else:
            successful_responses.append(result)

    elapsed = time.monotonic() - start_time

    if not successful_responses:
        logger.error("All parallel extractions failed")
        return ExtractOutput(), "", token_usages

    # Sort by original index for deterministic merge
    successful_responses.sort(key=lambda x: x[1])

    # Parse each response into ExtractOutput and merge
    extract_outputs: list[ExtractOutput] = []
    raw_texts: list[str] = []

    for response_text, idx in successful_responses:
        raw_texts.append(f"### Source {idx + 1}\n{response_text}")
        try:
            from .contract_parser import _extract_json
            raw_json = _extract_json(response_text)
            if raw_json:
                eo = ExtractOutput.from_json(raw_json)
                extract_outputs.append(eo)
            else:
                logger.warning("Extract[%d]: no JSON found in response", idx)
        except Exception as e:
            logger.warning("Extract[%d]: failed to parse: %s", idx, e)

    merged = merge_extractions(extract_outputs)
    merged_text = "\n\n---\n\n".join(raw_texts)

    # Log timing
    estimated_sequential = elapsed * len(sources) / max(len(successful_responses), 1)
    logger.info(
        "Fan-out EXTRACT: %d sources, %.1fs parallel (est. %.1fs sequential)",
        len(sources), elapsed, estimated_sequential,
    )
    print(
        f"  Layer 1: EXTRACT paralelo ({len(successful_responses)}/{len(sources)} fuentes, "
        f"{elapsed:.1f}s) vs secuencial estimado ({estimated_sequential:.1f}s)"
    )

    return merged, merged_text, token_usages


def merge_extractions(results: list[ExtractOutput]) -> ExtractOutput:
    """Merge multiple ExtractOutputs into one — deterministic, no LLM.

    - Concatenate all extractions
    - Deduplicate identical claims
    - Sort by confidence descending
    - Merge gaps_identified (deduplicated)
    """
    all_extractions: list[Extraction] = []
    all_gaps: list[str] = []
    seen_claims: set[str] = set()

    for eo in results:
        for ext in eo.extractions:
            # Deduplicate claims within each extraction
            unique_claims = []
            for claim in ext.claims:
                normalized = claim.strip().lower()
                if normalized not in seen_claims:
                    seen_claims.add(normalized)
                    unique_claims.append(claim)

            # Keep extraction if it has unique content
            if unique_claims or ext.data_points or ext.quotes:
                deduped = Extraction(
                    source_ref=ext.source_ref,
                    claims=unique_claims,
                    data_points=ext.data_points,
                    quotes=ext.quotes,
                    confidence=ext.confidence,
                )
                all_extractions.append(deduped)

        for gap in eo.gaps_identified:
            if gap not in all_gaps:
                all_gaps.append(gap)

    # Sort by confidence descending
    all_extractions.sort(key=lambda e: e.confidence, reverse=True)

    return ExtractOutput(
        extractions=all_extractions,
        gaps_identified=all_gaps,
    )
