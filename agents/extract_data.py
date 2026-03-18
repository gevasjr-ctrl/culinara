#!/usr/bin/env python3
"""
Extract JS data constants from index.html into standalone JSON files.
Run once, or re-run whenever index.html data changes.
"""

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(BASE_DIR, "index.html")
DATA_DIR = os.path.join(BASE_DIR, "data")

# Map: variable name in JS → output filename
EXTRACTIONS = {
    "BASE_MENU_ITEMS": "menu_items.json",
    "PREP_ITEMS": "prep_items.json",
    "PREP_RECIPES": "prep_recipes.json",
    "ORDER_DATA": "order_data.json",
    "INVOICES": "invoices.json",
    "YIELD_ITEMS": "yield_items.json",
    "SALE_WEIGHTS": "sale_weights.json",
    "INVENTORY": "inventory.json",
}


def clean_js_to_json(js_text: str) -> str:
    """Convert JS object/array literal to valid JSON.

    Handles tricky cases like apostrophes inside single-quoted strings
    (e.g., 'Smokin' Hot') by tokenizing properly.
    """
    text = js_text

    # Remove single-line JS comments (but not inside strings)
    # We'll handle this line-by-line to avoid breaking string contents
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # Simple heuristic: remove // comments not inside quotes
        result = []
        in_str = False
        str_ch = None
        i = 0
        while i < len(line):
            ch = line[i]
            if in_str:
                if ch == '\\':
                    result.append(ch)
                    if i + 1 < len(line):
                        result.append(line[i + 1])
                    i += 2
                    continue
                if ch == str_ch:
                    in_str = False
                result.append(ch)
            else:
                if ch in ('"', "'"):
                    in_str = True
                    str_ch = ch
                    result.append(ch)
                elif ch == '/' and i + 1 < len(line) and line[i + 1] == '/':
                    break  # rest of line is comment
                else:
                    result.append(ch)
            i += 1
        cleaned_lines.append(''.join(result))
    text = '\n'.join(cleaned_lines)

    # Remove multi-line comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    # Now convert single-quoted strings to double-quoted, properly handling
    # apostrophes inside strings (like "Smokin' Hot")
    # Strategy: tokenize by finding string boundaries using the colon/comma context
    output = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            # Already double-quoted string — pass through
            j = i + 1
            while j < len(text):
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            output.append(text[i:j + 1])
            i = j + 1
        elif ch == "'":
            # Single-quoted JS string — find the REAL end quote
            # The real end is the ' that is followed by a structural character
            # (comma, }, ], whitespace+key, etc.) not a letter
            j = i + 1
            while j < len(text):
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == "'":
                    # Check if this is the real end of the string
                    # Look at what follows: if it's a structural char, it's the end
                    rest = text[j + 1:].lstrip()
                    if not rest or rest[0] in (',', '}', ']', ')', ';', '\n'):
                        break
                    # Also end if next non-space is a key pattern like `word:`
                    # This handles multi-value lines like { name:'X', w:5 }
                    if rest[0] in (' ', '\t'):
                        rest = rest.lstrip()
                    # If after the quote we see }, ], comma, or end — it's real
                    # Otherwise it's an apostrophe inside the string
                j += 1
            content = text[i + 1:j]
            # Escape any double quotes inside, and convert apostrophes
            content = content.replace('"', '\\"')
            output.append('"' + content + '"')
            i = j + 1
        else:
            output.append(ch)
            i += 1

    text = ''.join(output)

    # Quote unquoted keys: { key: ... } → { "key": ... }
    text = re.sub(r'(?<=[{,\n])\s*([a-zA-Z_]\w*)\s*:', r' "\1":', text)

    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Handle special JS values
    text = text.replace('undefined', 'null')

    return text


def extract_array(html: str, var_name: str) -> list:
    """Extract a JS array/object literal assigned to var_name."""
    # Match: const/let/var VARNAME = [...]  or {...}
    pattern = rf'(?:const|let|var)\s+{re.escape(var_name)}\s*=\s*'
    match = re.search(pattern, html)
    if not match:
        print(f"  WARNING: Could not find '{var_name}' in HTML")
        return None

    start = match.end()
    opener = html[start]
    if opener not in ('[', '{'):
        print(f"  WARNING: '{var_name}' doesn't start with [ or {{, got '{opener}'")
        return None

    closer = ']' if opener == '[' else '}'

    # Track nesting to find the matching closer
    depth = 0
    i = start
    in_string = False
    string_char = None

    while i < len(html):
        ch = html[i]

        if in_string:
            if ch == '\\':
                i += 2
                continue
            if ch == string_char:
                in_string = False
        else:
            if ch in ('"', "'", '`'):
                in_string = True
                string_char = ch
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    break
        i += 1

    js_text = html[start:i + 1]
    json_text = clean_js_to_json(js_text)

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        # Save debug output
        debug_path = os.path.join(DATA_DIR, f"_debug_{var_name}.txt")
        with open(debug_path, 'w') as f:
            f.write(json_text)
        print(f"  ERROR parsing '{var_name}': {e}")
        print(f"  Debug output saved to {debug_path}")
        return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(HTML_PATH):
        print(f"ERROR: {HTML_PATH} not found")
        sys.exit(1)

    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        html = f.read()

    print(f"Read {len(html):,} bytes from index.html")
    print()

    success = 0
    for var_name, filename in EXTRACTIONS.items():
        print(f"Extracting {var_name}...")
        data = extract_array(html, var_name)
        if data is not None:
            out_path = os.path.join(DATA_DIR, filename)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            count = len(data) if isinstance(data, list) else len(data.keys())
            print(f"  → {filename} ({count} items)")
            success += 1
        else:
            print(f"  → FAILED")

    print(f"\nDone: {success}/{len(EXTRACTIONS)} files extracted to {DATA_DIR}/")

    if success < len(EXTRACTIONS):
        sys.exit(1)


if __name__ == "__main__":
    main()
