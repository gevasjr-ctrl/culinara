"""
Miles Teller — Culinara's Operations & Kitchen Agent
Prep planning, inventory, ordering, suppliers, invoices, delivery schedules.
Equal peer. Runs the kitchen brain.
"""

import json
from shared import (
    get_client, load_all_data, load_memory, load_prompt,
    run_agent, save_report, today_str, day_of_week, estimate_cost,
)

AGENT_NAME = "miles_teller"
REPORT_FILE = "miles_teller_report.md"
PROMPT_FILE = "miles_teller_system.md"


def build_user_message(data: dict, memory: dict, margin_report: str = "") -> str:
    """Build the user message with all relevant data for the Prep agent."""
    prep_recipes = data["prep_recipes"]
    prep_items = data["prep_items"]
    inventory = data["inventory"]
    order_data = data["order_data"]
    invoices = data["invoices"]
    yields = data["yield_items"]
    menu = data["menu_items"]

    # Compute inventory status
    inv_status = []
    for item in inventory:
        par = item.get("par", 0)
        on_hand = item.get("onHand", 0)
        ratio = on_hand / par if par > 0 else 1.0
        status = "CRITICAL" if ratio <= 0.35 else "LOW" if ratio < 1.0 else "OK"
        inv_status.append({**item, "ratio": round(ratio, 2), "status": status})

    critical_items = [i for i in inv_status if i["status"] == "CRITICAL"]
    low_items = [i for i in inv_status if i["status"] == "LOW"]

    # Pending invoices
    pending_invoices = [i for i in invoices if i.get("status") in ("review", "pending")]

    # High urgency prep items
    high_urgency = [r for r in prep_recipes if r.get("urgency") == "high"]

    # Expected covers based on day of week
    dow = day_of_week()
    # Weekend bump: Fri/Sat ~20% more, Sunday ~10% less
    base_covers = 39
    dow_multipliers = {
        "Monday": 0.85, "Tuesday": 0.90, "Wednesday": 0.95,
        "Thursday": 1.00, "Friday": 1.20, "Saturday": 1.25, "Sunday": 0.90,
    }
    expected_covers = round(base_covers * dow_multipliers.get(dow, 1.0))

    msg = f"""# Prep Analysis Run — {today_str()} ({dow})

## Expected Covers Today: ~{expected_covers}
Base avg: {base_covers}/day · {dow} multiplier: {dow_multipliers.get(dow, 1.0)}x

## Prep Recipes ({len(prep_recipes)} items)
{json.dumps(prep_recipes, indent=2, default=str)}

## Detailed Prep Instructions ({len(prep_items)} recipes)
{json.dumps(prep_items, indent=2, default=str)}

## Inventory Status ({len(inv_status)} items)
{json.dumps(inv_status, indent=2, default=str)}

### CRITICAL Items ({len(critical_items)}):
{json.dumps(critical_items, indent=2, default=str)}

### LOW Items ({len(low_items)}):
{json.dumps(low_items, indent=2, default=str)}

## Supplier Order Data ({len(order_data)} suppliers)
{json.dumps(order_data, indent=2, default=str)}

## Pending Invoices ({len(pending_invoices)} to review)
{json.dumps(pending_invoices, indent=2, default=str)}

## All Invoices ({len(invoices)} total)
{json.dumps(invoices, indent=2, default=str)}

## Yield Data ({len(yields)} ingredients)
{json.dumps(yields, indent=2, default=str)}

## Menu Items (for cross-reference)
{json.dumps(menu, indent=2, default=str)}

## Knowledge Base
{json.dumps(memory.get("knowledge_base", {}), indent=2, default=str)}

## Prep Accuracy History
{json.dumps(list(memory.get("prep_accuracy", []) or [])[-7:], indent=2, default=str)}

## Supplier Intelligence
{json.dumps(memory.get("supplier_intel", {}), indent=2, default=str)}

## Previous Predictions to Verify
{json.dumps(memory.get("predictions", {}).get("prep", []), indent=2, default=str)}

## Margin Agent Findings (from today's run)
{margin_report if margin_report else "No margin report available yet."}

Analyze all data above. Produce your Prep Report following your system prompt format.
Focus on what's actionable for today's service. Reference past learnings from memory.
"""
    return msg


def run(client=None, model="claude-haiku-4-5-20251001", margin_report: str = "") -> dict:
    """Run the Prep agent. Returns dict with report text and usage."""
    if client is None:
        client = get_client()

    system_prompt = load_prompt(PROMPT_FILE)
    data = load_all_data()

    memory = {
        "knowledge_base": load_memory("knowledge_base.json"),
        "prep_accuracy": load_memory("prep_accuracy.json"),
        "supplier_intel": load_memory("supplier_intel.json"),
        "predictions": load_memory("predictions_log.json"),
    }

    user_message = build_user_message(data, memory, margin_report)

    print(f"  Running Miles Teller ({model})...")
    report_text, usage = run_agent(
        client=client,
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        max_tokens=4096,
    )

    path = save_report(REPORT_FILE, report_text)
    cost = estimate_cost(usage)

    print(f"  Miles Teller report saved: {path}")
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
