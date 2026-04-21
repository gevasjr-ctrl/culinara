# Culinara — Project instructions for Claude

This file is auto-loaded by Claude Code every session. Always read it first.

## Working agreement (non-negotiable)

1. **Commit early, commit often.** After every meaningful change, run:
   ```
   git add -A && git commit -m "<what changed>"
   ```
   Don't wait for the user to ask. Uncommitted work is lost work.
2. **Push at end of session.** Before closing a chat, push to `origin/main`.
3. **Never guess user wording.** If you don't know an exact slogan / copy / brand phrase, ASK — don't make up something and overwrite the file.
4. **Save decisions verbatim.** When the user picks wording, a slogan, a color, a phrase, record it in this file (see "Decisions" section below) AND commit.
5. **Save progress frequently.** User's chats sometimes die from API errors. Assume every response might be the last.

## Product

**Culinara / CulinaraOS** — Restaurant operations intelligence platform.
Single static HTML/CSS/JS app (`index.html`) deployed to Vercel via GitHub. Supabase backend (auth, DB, storage, edge functions).

## Stack & deploy

- **Repo:** github.com/gevasjr-ctrl/culinara (branch `main`)
- **Hosting:** Vercel project `culinara-app` — auto-deploys `main` → `www.culinaraos.com`
- **Supabase project:** ref `qexjxndommlfqzngxqym` (Canada Central) — name "culinara"
- **Dev server:** `.claude/launch.json` → `preview_start("culinara")` on port 3100
- **Node:** v20.20.2 via nvm

## Credentials / tokens (used by CLI / edge fns)

Tokens live in `~/.claude/projects/-Users-thomasgevas-Desktop/memory/MEMORY.md` — always read that file at session start for the latest values. Never paste secrets into chat messages.

## Email / invoice pipeline (current)

- Domain: `culinaraos.com` (Namecheap, default nameservers)
- Microsoft 365: `thomas@culinaraos.com` mailbox on root domain
- Postmark server: "Culinaraos Invoices" (18932737) — test mode, approval requested
- Invoice inbox pattern: `<restaurant_id>@invoices.culinaraos.com`
  - e.g. `botte@invoices.culinaraos.com`, `arthurs@invoices.culinaraos.com`
  - MX for `invoices.culinaraos.com` → `inbound.postmarkapp.com` priority 10 (Namecheap)
- Webhook: `https://qexjxndommlfqzngxqym.supabase.co/functions/v1/postmark-inbound?token=<POSTMARK_WEBHOOK_TOKEN>`
- Flow: Postmark inbound → edge fn `postmark-inbound` → `invoices` row + storage upload → edge fn `extract-invoice` (Claude API) fills structured fields.

## Database

Key tables (public schema, Supabase):
- `restaurants` — `id` is TEXT (slug like "botte"), has `invoice_email`
- `user_restaurants` — maps `user_id` (uuid) → `restaurant_id` (text)
- `profiles`, `user_profiles` — user data
- `invoices` — extended with source, from_email, message_id (unique per restaurant), attachments(jsonb), line_items(jsonb), total_amount, currency, received_at, body_text, body_html, extraction_error, updated_at
- `menu_items`, `ingredients`, `recipe_items`, `suppliers`, `staff_members`, `ai_insights`
- Storage bucket `invoices` (private) — folder layout `<restaurant_id>/<invoice_id>/<file>`

## Restaurants

- **Bottē** (`id="botte"`) — active live customer. Sourdough pizza, St-Lazare QC.
  - Current period Jan 1 – Apr 13, 2026 (103 days).
- **Arthur's Nosh Bar** (`id="arthurs"`) — onboarding prospect, 65% setup. Saint-Henri, Montréal.

## Design tokens

- Mode: dark only
- Font: Inter + Space Grotesk (display)
- Colors: bg `#171B26`, card `#1F2433`, sidebar `#111520`
- Accents: blue `#4F8EF7`, green `#34C97A`, red `#F05252`, amber `#F5A623`, purple `#A78BFA`

## Decisions (user wording — DO NOT paraphrase)

<!--
  When the user picks exact wording (slogan, copy, brand phrase, etc.), append it
  here with date. Treat these as immutable unless the user asks to change them.
  Commit immediately after adding.
-->

- **Login footer slogan:** BLANK — user is deciding the final wording. DO NOT put placeholder text in the footer. Leave empty until user gives exact words.
- **Naming (locked 2026-04-20):**
  - **Legal entity (planned):** `Culinara Inc.` (Quebec: `Culinara inc.`) — NOT YET INCORPORATED
  - **Brand / product name (customer-facing):** `CulinaraOS` (capital O, capital S)
  - **Domain:** `culinaraos.com`
  - **Email address style:** `<restaurant-slug>@invoices.culinaraos.com`
  - Rationale: Legal entity is short and flexible (like "Stripe Inc." operating as "Stripe"). Brand can evolve; entity stays stable.
  - In UI / marketing: always write `CulinaraOS`. Never write "Culinara OS" (with a space) or "Culinaraos" (lowercase os).

## Anti-patterns (seen in past sessions — avoid)

- Overwriting copy/slogans with best-guess alternatives. Always ask.
- Making local edits without committing. Always commit.
- Telling the user to do operational setup (CLI login, DNS, API config) we could do via API. Try API first.
- Assuming memory is complete. It's a reference, not the source of truth — verify against git/DB.
