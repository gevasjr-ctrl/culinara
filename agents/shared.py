"""
Shared utilities for Culinara AI Agent Team.
Handles data loading, report saving, API client, memory management, and security.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, date
from pathlib import Path
from typing import Union

from anthropic import Anthropic
from dotenv import load_dotenv

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
MEMORY_DIR = BASE_DIR / "memory"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# ── Environment ──────────────────────────────────────────────────────────────

load_dotenv(BASE_DIR / ".env", override=True)


def get_client() -> Anthropic:
    """Create an Anthropic API client. Fails fast if key is missing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to culinara/.env"
        )
    return Anthropic(api_key=api_key)


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_json(filename: str) -> dict | list:
    """Load a JSON file from the data/ directory."""
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_data() -> dict:
    """Load all restaurant data files into a single dict."""
    data = {}
    files = {
        "menu_items": "menu_items.json",
        "prep_items": "prep_items.json",
        "prep_recipes": "prep_recipes.json",
        "order_data": "order_data.json",
        "invoices": "invoices.json",
        "yield_items": "yield_items.json",
        "sale_weights": "sale_weights.json",
        "inventory": "inventory.json",
    }
    for key, filename in files.items():
        try:
            data[key] = load_json(filename)
        except FileNotFoundError:
            print(f"  Warning: {filename} not found, skipping")
            data[key] = []
    return data


# ── Memory Management ────────────────────────────────────────────────────────

def _ensure_secure_dir(path: Path):
    """Create directory with owner-only permissions."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)  # 700


def load_memory(filename: str) -> dict | list:
    """Load a memory file. Returns empty dict if not found."""
    _ensure_secure_dir(MEMORY_DIR)
    path = MEMORY_DIR / filename
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(filename: str, data: dict | list):
    """Save a memory file with secure permissions."""
    _ensure_secure_dir(MEMORY_DIR)
    path = MEMORY_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600


def append_to_log(filename: str, entry: dict):
    """Append an entry to an append-only log file."""
    log = load_memory(filename)
    if not isinstance(log, list):
        log = []
    log.append(entry)
    # Keep last 90 days of entries max
    if len(log) > 90:
        log = log[-90:]
    save_memory(filename, log)


# ── Report Saving ────────────────────────────────────────────────────────────

def get_today_report_dir() -> Path:
    """Get/create today's report directory."""
    today = date.today().isoformat()
    report_dir = REPORTS_DIR / today
    _ensure_secure_dir(REPORTS_DIR)
    _ensure_secure_dir(report_dir)
    return report_dir


def save_report(filename: str, content: str) -> Path:
    """Save a report to today's report directory."""
    report_dir = get_today_report_dir()
    path = report_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600
    return path


# ── Prompt Loading ───────────────────────────────────────────────────────────

def load_prompt(filename: str) -> str:
    """Load a system prompt from the prompts/ directory."""
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ── Agent Runner ─────────────────────────────────────────────────────────────

def run_agent(
    client: Anthropic,
    system_prompt: str,
    user_message: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 4096,
) -> str:
    """Run a single agent call and return the text response."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    # Extract text from response
    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "model": model,
    }
    return "\n".join(text_parts), usage


# ── Cost Tracking ────────────────────────────────────────────────────────────

# Pricing per million tokens (as of 2025)
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-4-sonnet-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
}


def estimate_cost(usage: dict) -> float:
    """Estimate API cost from usage dict."""
    model = usage.get("model", "claude-haiku-4-5-20251001")
    prices = PRICING.get(model, PRICING["claude-haiku-4-5-20251001"])
    cost = (
        usage["input_tokens"] * prices["input"] / 1_000_000
        + usage["output_tokens"] * prices["output"] / 1_000_000
    )
    return round(cost, 6)


# ── Date Helpers ─────────────────────────────────────────────────────────────

def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def day_of_week() -> str:
    return datetime.now().strftime("%A")


def is_sunday() -> bool:
    return datetime.now().weekday() == 6
