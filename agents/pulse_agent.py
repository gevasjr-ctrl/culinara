"""
Pulse Agent — Culinara's Daily Intelligence AI
Synthesizes all findings, detects anomalies, manages the knowledge base.
"""

import json
import re
from shared import (
    get_client, load_all_data, load_memory, save_memory, load_prompt,
    run_agent, save_report, append_to_log, today_str, day_of_week,
    now_str, is_sunday, estimate_cost,
)

AGENT_NAME = "pulse"
REPORT_FILE = "daily_briefing.md"
PROMPT_FILE = "pulse_system.md"


def build_user_message(
    data: dict, memory: dict,
    margin_report: str, prep_report: str,
) -> str:
    """Build the user message with all data + agent reports for Pulse."""
    menu = data["menu_items"]
    inventory = data["inventory"]
    invoices = data["invoices"]

    # Key metrics
    total_revenue = sum(i.get("rev", 0) for i in menu)
    total_food_cost = sum(i.get("foodCost", 0) for i in menu)
    overall_fc_pct = (total_food_cost / total_revenue * 100) if total_revenue else 0
    total_units = sum(i.get("units", 0) for i in menu)

    # Inventory health
    critical = sum(1 for i in inventory if i.get("par", 0) > 0 and i.get("onHand", 0) / i["par"] <= 0.35)
    low = sum(1 for i in inventory if i.get("par", 0) > 0 and 0.35 < i.get("onHand", 0) / i["par"] < 1.0)

    # Invoice status
    pending = sum(1 for i in invoices if i.get("status") in ("review", "pending"))
    matched = sum(1 for i in invoices if i.get("status") == "matched")

    sunday_flag = "YES — include Weekly Review section" if is_sunday() else "No"

    msg = f"""# Pulse Intelligence Run — {today_str()} ({day_of_week()})
## Sunday Weekly Review: {sunday_flag}

## Key Metrics
- Total Revenue: ${total_revenue:,.0f} (49-day period)
- Total Food Cost: ${total_food_cost:,.0f}
- Food Cost %: {overall_fc_pct:.1f}% (target: 25.0%)
- Daily Revenue: ${total_revenue / 49:,.0f}/day
- Total Units Sold: {total_units}
- Avg Covers/Day: ~{total_units / 49:.0f}
- Behind Target: ${total_food_cost - total_revenue * 0.25:,.0f}

## Inventory Health
- Critical items: {critical}
- Low items: {low}
- OK items: {len(inventory) - critical - low}

## Invoice Status
- Pending review: {pending}
- Matched to QBO: {matched}

## Margin Agent Report
{margin_report}

## Prep Agent Report
{prep_report}

## Full Knowledge Base
{json.dumps(memory.get("knowledge_base", {}), indent=2, default=str)}

## Cost History (last 14 days)
{json.dumps(list(memory.get("cost_history", []) or [])[-14:], indent=2, default=str)}

## Menu Performance Trends
{json.dumps(memory.get("menu_performance", {}), indent=2, default=str)}

## Supplier Intelligence
{json.dumps(memory.get("supplier_intel", {}), indent=2, default=str)}

## Agent Log (last 7 entries)
{json.dumps(list(memory.get("agent_log", []) or [])[-7:], indent=2, default=str)}

## All Predictions to Verify
{json.dumps(memory.get("predictions", {}), indent=2, default=str)}

Synthesize everything above into your Daily Briefing following your system prompt format.
Include the JSON knowledge base update block at the end.
{"Include the Weekly Review section — it's Sunday." if is_sunday() else ""}
"""
    return msg


def process_knowledge_update(report_text: str, current_kb: dict) -> dict:
    """Extract and apply knowledge base updates from Pulse's report."""
    # Find the JSON block
    pattern = r'```json-knowledge-update\s*\n(.*?)\n```'
    match = re.search(pattern, report_text, re.DOTALL)
    if not match:
        return current_kb

    try:
        updates = json.loads(match.group(1))
    except json.JSONDecodeError:
        print("  Warning: Could not parse knowledge update JSON")
        return current_kb

    # Initialize KB structure if needed
    if not isinstance(current_kb, dict):
        current_kb = {}
    if "hypotheses" not in current_kb:
        current_kb["hypotheses"] = []
    if "patterns" not in current_kb:
        current_kb["patterns"] = []
    if "rules" not in current_kb:
        current_kb["rules"] = []
    if "prediction_accuracy" not in current_kb:
        current_kb["prediction_accuracy"] = {"margin": [], "prep": []}

    # Apply new entries
    for entry in updates.get("new_entries", []):
        entry["added"] = today_str()
        current_kb["hypotheses"].append(entry)

    # Apply promotions (hypothesis → pattern)
    for promo in updates.get("promotions", []):
        finding = promo.get("finding", "")
        # Remove from hypotheses
        current_kb["hypotheses"] = [
            h for h in current_kb["hypotheses"]
            if h.get("finding") != finding
        ]
        current_kb["patterns"].append({
            "finding": finding,
            "evidence_count": promo.get("evidence_count", 3),
            "promoted": today_str(),
        })

    # Apply graduations (pattern → rule)
    for grad in updates.get("graduations", []):
        finding = grad.get("finding", "")
        current_kb["patterns"] = [
            p for p in current_kb["patterns"]
            if p.get("finding") != finding
        ]
        current_kb["rules"].append({
            "finding": finding,
            "weeks_validated": grad.get("weeks_validated", 2),
            "graduated": today_str(),
        })

    # Prune stale entries
    for prune in updates.get("prune", []):
        finding = prune.get("finding", "")
        current_kb["hypotheses"] = [
            h for h in current_kb["hypotheses"]
            if h.get("finding") != finding
        ]

    # Update prediction accuracy
    pred_acc = updates.get("prediction_accuracy", {})
    if pred_acc:
        current_kb["prediction_accuracy"]["margin"].append({
            "date": today_str(), **pred_acc.get("margin", {})
        })
        current_kb["prediction_accuracy"]["prep"].append({
            "date": today_str(), **pred_acc.get("prep", {})
        })
        # Keep last 30 entries
        for key in ("margin", "prep"):
            current_kb["prediction_accuracy"][key] = \
                current_kb["prediction_accuracy"][key][-30:]

    return current_kb


def run(
    client=None, model="claude-haiku-4-5-20251001",
    margin_report: str = "", prep_report: str = "",
) -> dict:
    """Run the Pulse agent. Returns dict with report text and usage."""
    if client is None:
        client = get_client()

    system_prompt = load_prompt(PROMPT_FILE)
    data = load_all_data()

    memory = {
        "knowledge_base": load_memory("knowledge_base.json"),
        "cost_history": load_memory("cost_history.json"),
        "menu_performance": load_memory("menu_performance.json"),
        "supplier_intel": load_memory("supplier_intel.json"),
        "agent_log": load_memory("agent_log.json"),
        "predictions": load_memory("predictions_log.json"),
    }

    user_message = build_user_message(data, memory, margin_report, prep_report)

    # Use Sonnet for Sunday deep reviews, Haiku for daily
    run_model = "claude-4-sonnet-20250514" if is_sunday() else model

    print(f"  Running Pulse agent ({run_model}){'  [WEEKLY REVIEW]' if is_sunday() else ''}...")
    report_text, usage = run_agent(
        client=client,
        system_prompt=system_prompt,
        user_message=user_message,
        model=run_model,
        max_tokens=6144 if is_sunday() else 4096,
    )

    # Save the briefing
    path = save_report(REPORT_FILE, report_text)
    cost = estimate_cost(usage)

    # Process knowledge base updates
    current_kb = memory["knowledge_base"]
    updated_kb = process_knowledge_update(report_text, current_kb)
    save_memory("knowledge_base.json", updated_kb)

    # Update cost history
    menu = data["menu_items"]
    total_revenue = sum(i.get("rev", 0) for i in menu)
    total_food_cost = sum(i.get("foodCost", 0) for i in menu)
    cost_history = memory.get("cost_history", [])
    if not isinstance(cost_history, list):
        cost_history = []
    cost_history.append({
        "date": today_str(),
        "fc_pct": round(total_food_cost / total_revenue * 100, 1) if total_revenue else 0,
        "revenue": total_revenue,
        "food_cost": total_food_cost,
    })
    save_memory("cost_history.json", cost_history[-90:])

    # Log this run
    append_to_log("agent_log.json", {
        "date": now_str(),
        "agent": "pulse",
        "model": run_model,
        "tokens": usage,
        "cost": cost,
        "kb_entries": {
            "hypotheses": len(updated_kb.get("hypotheses", [])),
            "patterns": len(updated_kb.get("patterns", [])),
            "rules": len(updated_kb.get("rules", [])),
        },
    })

    print(f"  Daily briefing saved: {path}")
    print(f"  Tokens: {usage['input_tokens']} in / {usage['output_tokens']} out · ${cost:.4f}")
    print(f"  Knowledge base: {len(updated_kb.get('hypotheses', []))} hypotheses, "
          f"{len(updated_kb.get('patterns', []))} patterns, "
          f"{len(updated_kb.get('rules', []))} rules")

    return {
        "report": report_text,
        "path": str(path),
        "usage": usage,
        "cost": cost,
    }


if __name__ == "__main__":
    result = run()
    print("\n" + result["report"])
