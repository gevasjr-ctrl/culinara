"""
Jon Snow — Culinara's Money & Margins Agent
Food cost, pricing, menu engineering, waste, yield gaps, invoice costs.
Equal peer. Recommends — Thomas decides.
"""

import json
from shared import (
    get_client, load_all_data, load_memory, load_prompt,
    run_agent, save_report, today_str, day_of_week, estimate_cost,
)

AGENT_NAME = "jon_snow"
REPORT_FILE = "jon_snow_report.md"
PROMPT_FILE = "jon_snow_system.md"


def build_user_message(data: dict, memory: dict) -> str:
    """Build the user message with all relevant data for the Margin agent."""
    menu = data["menu_items"]
    yields = data["yield_items"]
    invoices = data["invoices"]
    inventory = data["inventory"]

    # Compute key metrics
    total_revenue = sum(i.get("rev", 0) for i in menu)
    total_food_cost = sum(i.get("foodCost", 0) for i in menu)
    overall_fc_pct = (total_food_cost / total_revenue * 100) if total_revenue else 0
    behind_target = total_food_cost - (total_revenue * 0.25)

    # Items with FC% > 25%
    high_fc_items = [
        i for i in menu
        if i.get("fc", 0) > 0.25 and i.get("cat") != "Beverages"
    ]
    high_fc_items.sort(key=lambda x: x.get("units", 0) * (x.get("fc", 0) - 0.25), reverse=True)

    # Engineering breakdown
    eng_counts = {}
    for i in menu:
        eng = i.get("eng", "unknown")
        eng_counts[eng] = eng_counts.get(eng, 0) + 1

    # Negative margin items
    neg_margin = [i for i in menu if i.get("gmUnit", 0) < 0]

    msg = f"""# Margin Analysis Run — {today_str()} ({day_of_week()})

## Current Period Data (Jan 25 – Mar 15, 2026 · 49 days)
- Total Revenue: ${total_revenue:,.0f}
- Total Food Cost: ${total_food_cost:,.0f}
- Overall Food Cost %: {overall_fc_pct:.1f}% (target: 25.0%)
- Behind Target: ${behind_target:,.0f}
- Daily shortfall: ${behind_target / 49:,.0f}/day

## Menu Items ({len(menu)} total)
{json.dumps(menu, indent=2, default=str)}

## Items with Food Cost > 25% Target ({len(high_fc_items)} items)
{json.dumps(high_fc_items, indent=2, default=str)}

## Negative Margin Items ({len(neg_margin)} items)
{json.dumps(neg_margin, indent=2, default=str)}

## Engineering Distribution
{json.dumps(eng_counts, indent=2)}

## Yield Data ({len(yields)} ingredients)
{json.dumps(yields, indent=2, default=str)}

## Recent Invoices ({len(invoices)} invoices)
{json.dumps(invoices, indent=2, default=str)}

## Current Inventory ({len(inventory)} items)
{json.dumps(inventory, indent=2, default=str)}

## Knowledge Base (Past Learnings)
{json.dumps(memory.get("knowledge_base", {}), indent=2, default=str)}

## Cost History (Past Snapshots)
{json.dumps(list(memory.get("cost_history", []))[-7:], indent=2, default=str)}

## Previous Predictions to Verify
{json.dumps(memory.get("predictions", {}).get("margin", []), indent=2, default=str)}

Analyze all data above. Produce your Margin Report following your system prompt format.
Focus on actionable insights ranked by dollar impact. Reference any past findings from memory.
"""
    return msg


def run(client=None, model="claude-haiku-4-5-20251001") -> dict:
    """Run the Margin agent. Returns dict with report text and usage."""
    if client is None:
        client = get_client()

    system_prompt = load_prompt(PROMPT_FILE)
    data = load_all_data()

    # Load relevant memory
    memory = {
        "knowledge_base": load_memory("knowledge_base.json"),
        "cost_history": load_memory("cost_history.json"),
        "predictions": load_memory("predictions_log.json"),
    }

    user_message = build_user_message(data, memory)

    print(f"  Running Jon Snow ({model})...")
    report_text, usage = run_agent(
        client=client,
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        max_tokens=4096,
    )

    # Save report
    path = save_report(REPORT_FILE, report_text)
    cost = estimate_cost(usage)

    print(f"  Jon Snow report saved: {path}")
    print(f"  Tokens: {usage['input_tokens']} in / {usage['output_tokens']} out · ${cost:.4f}")

    return {
        "report": report_text,
        "path": str(path),
        "usage": usage,
        "cost": cost,
    }


if __name__ == "__main__":
    result = run()
    print("\n" + result["report"])
