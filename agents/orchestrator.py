#!/usr/bin/env python3
"""
Culinara AI Agent Orchestrator
Runs all 3 agents in sequence: Margin → Prep → Pulse
Each agent builds on the previous agent's findings.

Usage:
    python3 orchestrator.py              # Daily run (Haiku)
    python3 orchestrator.py --deep       # Deep analysis (Sonnet)
    python3 orchestrator.py --test       # Dry run to verify setup
"""

import argparse
import sys
import os
import time
from datetime import datetime

# Ensure agents/ is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared import (
    get_client, today_str, now_str, day_of_week, is_sunday,
    append_to_log, save_memory, load_memory, get_today_report_dir,
    DATA_DIR,
)


def verify_setup() -> bool:
    """Verify all prerequisites are in place."""
    errors = []

    # Check data files exist
    required_data = [
        "menu_items.json", "prep_items.json", "prep_recipes.json",
        "order_data.json", "invoices.json", "yield_items.json",
        "sale_weights.json", "inventory.json",
    ]
    for f in required_data:
        if not (DATA_DIR / f).exists():
            errors.append(f"Missing data file: data/{f} — run extract_data.py first")

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        errors.append("ANTHROPIC_API_KEY not set — add it to culinara/.env")

    if errors:
        print("Setup verification FAILED:")
        for e in errors:
            print(f"  - {e}")
        return False

    print("Setup verified OK")
    return True


def run_orchestrator(model: str = "claude-haiku-4-5-20251001", test: bool = False):
    """Run the full agent pipeline."""
    start_time = time.time()

    print("=" * 60)
    print(f"  Culinara AI Agent Team — {today_str()} ({day_of_week()})")
    print(f"  Model: {model}" + (" [SUNDAY DEEP REVIEW]" if is_sunday() else ""))
    print("=" * 60)
    print()

    # Verify setup
    if not verify_setup():
        sys.exit(1)

    if test:
        print("\n--test flag: Setup OK. Exiting without running agents.")
        return

    # Initialize client once (shared across agents)
    client = get_client()
    total_cost = 0.0
    total_tokens = {"input": 0, "output": 0}

    # ── Jon Snow — Money & Margins ──────────────────────────────────────
    print("\n[1/3] JON SNOW — Money & Margins")
    print("-" * 40)
    import jon_snow
    snow_result = jon_snow.run(client=client, model=model)
    total_cost += snow_result["cost"]
    total_tokens["input"] += snow_result["usage"]["input_tokens"]
    total_tokens["output"] += snow_result["usage"]["output_tokens"]

    # ── Miles Teller — Operations & Kitchen ──────────────────────────────
    print("\n[2/3] MILES TELLER — Operations & Kitchen")
    print("-" * 40)
    import miles_teller
    teller_result = miles_teller.run(
        client=client, model=model,
        margin_report=snow_result["report"],
    )
    total_cost += teller_result["cost"]
    total_tokens["input"] += teller_result["usage"]["input_tokens"]
    total_tokens["output"] += teller_result["usage"]["output_tokens"]

    # ── Mac Miller — Intelligence & Vision ───────────────────────────────
    print("\n[3/3] MAC MILLER — Intelligence & Vision")
    print("-" * 40)
    import mac_miller
    miller_result = mac_miller.run(
        client=client, model=model,
        margin_report=snow_result["report"],
        prep_report=teller_result["report"],
    )
    total_cost += miller_result["cost"]
    total_tokens["input"] += miller_result["usage"]["input_tokens"]
    total_tokens["output"] += miller_result["usage"]["output_tokens"]

    # ── Summary ──────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    report_dir = get_today_report_dir()

    print("\n" + "=" * 60)
    print("  RUN COMPLETE")
    print("=" * 60)
    print(f"  Date:     {today_str()} ({day_of_week()})")
    print(f"  Reports:  {report_dir}/")
    print(f"  Time:     {elapsed:.1f}s")
    print(f"  Tokens:   {total_tokens['input']:,} in / {total_tokens['output']:,} out")
    print(f"  Cost:     ${total_cost:.4f}")
    print()
    print(f"  Read your daily briefing:")
    print(f"    {miller_result['path']}")
    print()

    # Log the run
    append_to_log("agent_log.json", {
        "date": now_str(),
        "agent": "orchestrator",
        "model": model,
        "elapsed_seconds": round(elapsed, 1),
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "reports": {
            "margin": snow_result["path"],
            "prep": teller_result["path"],
            "pulse": miller_result["path"],
        },
    })

    # Track cumulative costs
    cost_tracker = load_memory("cost_tracker.json")
    if not isinstance(cost_tracker, dict):
        cost_tracker = {"total_cost": 0, "total_runs": 0, "runs": []}
    cost_tracker["total_cost"] = round(cost_tracker.get("total_cost", 0) + total_cost, 6)
    cost_tracker["total_runs"] = cost_tracker.get("total_runs", 0) + 1
    if "runs" not in cost_tracker:
        cost_tracker["runs"] = []
    cost_tracker["runs"].append({
        "date": today_str(),
        "cost": round(total_cost, 6),
        "tokens": total_tokens,
    })
    # Keep last 90 runs
    cost_tracker["runs"] = cost_tracker["runs"][-90:]
    save_memory("cost_tracker.json", cost_tracker)

    return {
        "margin": snow_result,
        "prep": teller_result,
        "pulse": miller_result,
        "total_cost": total_cost,
        "elapsed": elapsed,
    }


def main():
    parser = argparse.ArgumentParser(description="Culinara AI Agent Orchestrator")
    parser.add_argument(
        "--deep", action="store_true",
        help="Use Sonnet for deeper analysis (costs more, better insights)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Verify setup without running agents",
    )
    args = parser.parse_args()

    model = "claude-4-sonnet-20250514" if args.deep else "claude-haiku-4-5-20251001"
    run_orchestrator(model=model, test=args.test)


if __name__ == "__main__":
    main()
