# Culinara — Project state (safe for public repo)

Last updated: 2026-04-16

This is the shareable snapshot of project progress and decisions.
Sensitive values (API keys, tokens, PATs) are NEVER in this file —
they live in Supabase edge function secrets and local `.env` files only.

See `CLAUDE.md` at repo root for Claude-specific instructions.
Personal session memory lives in `~/.claude/projects/.../memory/MEMORY.md` (local machine only).

---

## Product

**CulinaraOS** (brand) — Restaurant operations intelligence platform.

- **Legal entity (planned, not yet incorporated):** `Culinara Inc.` (Quebec: `Culinara inc.`)
- **Brand / product:** `CulinaraOS` — always write with capital O + capital S. Never "Culinara OS" or "Culinaraos".
- **Live:** `www.culinaraos.com`
- **Repo:** github.com/gevasjr-ctrl/culinara (branch `main`)
- **Hosting:** Vercel (`culinara-app`) auto-deploys on push to `main`
- **Backend:** Supabase project `qexjxndommlfqzngxqym` (Canada Central)

## Restaurants

| ID | Name | Status |
|---|---|---|
| `botte` | Bottē Restaurant (St-Lazare QC — sourdough pizza) | Live customer, analysis period Jan 1 – Apr 13, 2026 |
| `arthurs` | Arthur's Nosh Bar (Saint-Henri, Montréal) | Onboarding prospect, 65% setup |

## Invoice email pipeline — COMPLETE ✅

End-to-end verified 2026-04-16: sent a real Amaro water invoice PDF via curl → Claude correctly extracted supplier, invoice #, date, total, and 3 line items.

**Architecture:**
```
Supplier sends email
  → MX: invoices.culinaraos.com → Postmark
  → Postmark POSTs to Supabase edge fn (postmark-inbound)
    - verifies ?token query param
    - resolves restaurant via restaurants.invoice_email or id slug
    - inserts invoices row (status=received)
    - uploads attachments to Storage: invoices/<restaurant_id>/<invoice_id>/<file>
    - fire-and-forget triggers extract-invoice (EdgeRuntime.waitUntil)
  → extract-invoice:
    - downloads PDFs from storage
    - sends to Claude API with structured-JSON prompt
    - writes supplier_name, invoice_number, invoice_date, total_amount,
      currency, line_items[], items_summary back to invoices row
    - sets status=extracted
```

**External setup:**
- **Domain:** culinaraos.com (Namecheap, default nameservers)
- **Root email:** thomas@culinaraos.com via Microsoft 365
- **Invoice subdomain:** invoices.culinaraos.com → MX to `inbound.postmarkapp.com` (priority 10)
- **Inbox pattern:** `<restaurant_id>@invoices.culinaraos.com` (e.g. `botte@…`, `arthurs@…`)
- **Postmark server:** "Culinaraos Invoices" (test mode, approval requested 2026-04-16)

**Secrets (stored in Supabase edge function secrets, NEVER in repo):**
- `POSTMARK_WEBHOOK_TOKEN` — query-param auth for the inbound webhook
- `ANTHROPIC_API_KEY` — must be created in Default Workspace of the funded Anthropic org. Workspace-scoped keys with spending limits will silently fail with "credit balance too low" even if the org has credits.

## Database

Key tables in `public` schema (all RLS-enabled, all have auth policies):

- `restaurants` — `id` is TEXT (slug like "botte"); has `invoice_email`, `pos_connected`, `qbo_connected`, `onboarding_pct`
- `user_restaurants` — maps `user_id` (uuid) → `restaurant_id` (text)
- `profiles`, `user_profiles`
- `menu_items`, `ingredients`, `recipe_items`, `suppliers`, `staff_members`
- `ai_insights`
- `invoices` — extended 2026-04-16 with: `source`, `from_email`, `from_name`, `subject`, `message_id` (unique per restaurant), `received_at`, `body_text`, `body_html`, `attachments` (jsonb), `total_amount`, `currency`, `line_items` (jsonb), `extraction_error`, `updated_at`

**Storage:**
- Bucket `invoices` (private) — folder layout `<restaurant_id>/<invoice_id>/<file>`

## Security posture

- ✅ RLS enabled on all 11 public tables
- ✅ Every table has at least one auth policy
- ✅ Storage buckets private (invoices)
- ✅ Webhook token-authenticated (verified 401 on wrong token)
- ✅ `.env` and `.claude/` in `.gitignore`
- ✅ No secrets ever committed to git
- ✅ Supabase anon key in client is safe (RLS gates everything)

## Remaining work to ship to real customers

Ordered by priority:

1. **Wire Invoices UI to real DB** (~1-2 hrs) — section currently shows hardcoded demo data
2. **Onboarding flow** (~half day) — self-serve signup / configure invoice email / connect POS
3. **Migrate `BASE_MENU_ITEMS` → Supabase** (~half day) — menu data currently hardcoded in JS for Bottē only
4. **Reconcile extracted invoices with suppliers / ingredients** (~1 day) — link `line_items` to `ingredients` and `suppliers` tables so food cost auto-updates
5. **Lightspeed POS OAuth** (~1 day) — auto-sync sales data
6. **QuickBooks Online OAuth** (~1 day) — auto-sync accounting
7. **Login footer slogan** — user decides the final wording (currently blank, see `CLAUDE.md` decisions section)
8. **Incorporate `Culinara Inc.` legally** — REQ (Quebec) or federal CBCA. Also: open business bank account, set up accounting, register for GST/QST if applicable. Consult a Quebec small-business lawyer (or use Ownr / LegalZoom Canada).
9. **Register trademark** for `CulinaraOS` with CIPO (Canadian Intellectual Property Office) — protects the brand from competitors using the same name.

## Design system

- Dark mode only
- Font: Inter + Space Grotesk (display)
- Colors: bg `#171B26`, card `#1F2433`, sidebar `#111520`
- Accents: blue `#4F8EF7`, green `#34C97A`, red `#F05252`, amber `#F5A623`, purple `#A78BFA`
