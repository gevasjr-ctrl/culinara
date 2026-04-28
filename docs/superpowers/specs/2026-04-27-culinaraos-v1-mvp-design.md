# CulinaraOS v1 MVP — Design Spec

**Date:** 2026-04-27
**Owner:** Thomas Gevas (gevasjr@gmail.com)
**Status:** Draft for review
**Live target:** www.culinaraos.com (existing Vercel + Supabase + Postmark stack)

---

## 1. Executive Summary

v1 of CulinaraOS is a **single-feature product** marketed and onboarded around one promise:

> *"Know your food cost yesterday — every morning, automatically — without spreadsheets, without waiting for month-end, without a recipe master."*

Everything currently shipped in `index.html` (auth, restaurants, invoice email pipeline, manual upload, CSV importer, onboarding shell, design system) is **kept and reused**. v1 is a focused build on top — not a rewrite.

**Reference customers:** Bottē (live) and Arthur's Nosh Bar (onboarding, full feature parity with Bottē — *not* the lean v1 wizard). New customers acquired post-Arthur's via word-of-mouth get the lean wizard and a focused sidebar (feature-flag gated).

**Estimated build:** ~3-4 weeks for the new code, plus a 1-2 day cleanup pass to split `index.html` into modules.

---

## 2. Goals + Non-Goals

### Goals (v1)
- Surface a defensible daily food cost % to the manager every morning, derived from real invoice + sales data.
- Get a brand-new restaurant from signup to a useful FC% in under 24 hours, with zero recipes or supplier setup required up front.
- Reuse 100% of the existing infrastructure (Postmark, Supabase, Vercel, CSV importer, design system).
- Build the data model in a way that recipes, theoretical FC, POS APIs, and per-line classification can be layered in without schema rewrites.
- Ship a focused experience that converts trials and gives Bottē/Arthur's a clean reference product to point peers at.

### Non-Goals (deferred to v1.1+)
- POS API integrations (Lightspeed, Square, Toast, Cluster) — Lightspeed already in motion for v1.1.
- Per-line invoice classification via Claude — supplier-level only in v1.
- Recipe master / theoretical food cost variance — v1.2.
- Order Guide, Prep Board, Yield Control, Inventory features — v2.
- Menu engineering insights — v1.3 (depends on recipes + per-item POS data).
- Staff scheduling / labor cost — v2.
- Social, AI Insights, Reports modules — v2.
- QuickBooks Online sync — v2.
- Outbound email alerts — v1.1 (gated on Postmark approval).
- Marketing site / paid acquisition — assumed N/A (founder-led sales).

---

## 3. Customers + Use Cases

### Buyer profiles (covered from day 1)
- **Independent owner-operators** — 1-3 locations, $1-5M revenue. Owner wears every hat. Examples: Bottē, Arthur's. Buying signal: *"I'm losing margin and don't know where."* Target price: $79-199/mo per location.
- **Small chef-driven groups** — 3-10 locations. Buyer is Ops Director or Group Chef. Wants consolidated reporting. Target price: $200-400/mo per location.

### Primary use case (the "morning ritual")
1. Manager opens app between 8-10am.
2. Sees yesterday's closed FC% above the fold.
3. If above target: drift banner shows top driver supplier(s).
4. Drills into Food Cost → Daily tab → variance breakdown → individual invoice if needed.
5. Acts on the leak before service starts.

Total time investment: 60-90 seconds/day for green days, 3-5 minutes for drift days.

### Secondary use cases
- Forwarding a new invoice to the assigned email and confirming it arrived.
- Tagging a new supplier as food/non-food when first seen.
- Uploading a sales CSV (or pasting yesterday's revenue if the POS export is offline).

---

## 4. Decisions Locked

| # | Decision | Rationale |
|---|---|---|
| 1 | **Hybrid food cost model** | Purchases-based on day 1 (works without recipes), recipes upgrade the view to theoretical + variance over time. Lets a brand-new customer see a number in 24 hrs while preserving Bottē's path to deeper insight. |
| 2 | **Multi-location capable from data model, no teardown** | Existing `user_restaurants` mapping already supports multi-location. Bottē + Arthur's keep all current pages; new customers see a focused sidebar via `feature_flags`. |
| 3 | **Headline = Yesterday's closed FC%; secondary = 7-day rolling; tertiary = today running** | Yesterday is settled and actionable. 7-day smooths invoice-delivery lumpiness. Today-running is informational only. |
| 4 | **Sales ingestion: CSV upload + email forward; no POS API in v1** | Reuses existing CSV importer (auto-delimiter, FR/EN headers). Adds a content-routing branch to the existing Postmark webhook. Zero new infrastructure. |
| 5 | **Food Cost page layout: tabbed (Daily / By Item / By Supplier)** | Daily tab is the new default for daily-watch use. Existing item-level table moves to "By Item" tab unchanged. By Supplier is a new view. Tab structure scales for v1.1+ additions. |
| 6 | **Per-supplier food/non-food classification (Claude line-level deferred to v1.1)** | One tap on first appearance, persists forever. ~95% accurate in practice. Avoids the support load of a per-line review queue. |
| 7 | **Lean 3-step signup wizard + persistent setup checklist (existing component)** | Reuses commit `b0b87e3`'s onboarding panel. Account live in <5 min. Deeper setup (suppliers, recipes, POS connection) gets nudged via the existing checklist as customer matures. |
| 8 | **Single inbox per restaurant for both invoices and sales** | `<slug>@invoices.culinaraos.com` handles both. Webhook routes by attachment type, not by `to:` field. No new DNS, no new Postmark rule, single address for the manager to memorize. |
| 9 | **In-app drift alerts only for v1** | Outbound email is unreliable (Postmark approval pending + delivery flakiness). In-app red banner is unmissable and doesn't depend on email infra. v1.1 adds Postmark email summary as a fallback. |
| 10 | **`index.html` cleanup pass included in v1** | Split inline CSS/JS/data into `styles.css`, per-section `js/` modules, `js/data.js`, `js/api.js`. Still vanilla — no framework, no build step, no npm. Adds 1-2 days; pays back the moment we touch any section twice. |

---

## 5. Architecture

### 5.1 Data flow

```
[Supplier email]            [Sales CSV email]            [Manual upload]
       |                          |                           |
       v                          v                           v
       +-------------- Postmark inbound webhook --------------+
                                  |
                  (route by attachment content-type)
                          |                  |
                          v                  v
            [extract-invoice]       [process-sales-csv]
            (Claude API,                  (NEW)
             existing)
                          |                  |
                          v                  v
                  +---------+         +-------------+
                  |invoices |         |sales_daily  |
                  |+is_fc   |         |    (NEW)    |
                  +----+----+         +------+------+
                       |                     |
                       +----------+----------+
                                  |
                                  v
                       [daily_food_cost view]
                              (NEW)
                                  |
                +-----------------+-----------------+
                |                                   |
                v                                   v
         [pg_cron 03:00]                  [Frontend (index.html)
       writes fc_daily_close                Food Cost section]
       + alert if drift                    Daily / By Item / By Supplier tabs
                |
                v
         [in-app banner
          on next login]
```

### 5.2 Database schema delta

**Total v1 changes:** 3 column additions + 2 new tables + 1 new view.

```sql
-- Existing tables: surgical additions
ALTER TABLE invoices ADD COLUMN is_food_cost boolean;
ALTER TABLE suppliers ADD COLUMN default_food_cost boolean;
ALTER TABLE restaurants ADD COLUMN fc_target_pct numeric DEFAULT 25;
ALTER TABLE restaurants ADD COLUMN feature_flags jsonb DEFAULT '{"tier":"full"}';

-- Triggers:
--   1. On invoices INSERT: is_food_cost := suppliers.default_food_cost (joined on supplier_id)
--   2. On suppliers UPDATE of default_food_cost: backfill is_food_cost on all
--      historical invoices for that supplier (so reclassification recomputes FC%)
-- Per-invoice manual override: NOT in v1. Supplier-level only.
-- Per-line classification (Claude flag per line_item): NOT in v1 — deferred to v1.1.

-- New table
CREATE TABLE sales_daily (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  restaurant_id text REFERENCES restaurants(id),
  date date NOT NULL,
  revenue_total numeric NOT NULL,
  cover_count integer,
  source text,            -- 'csv-upload' | 'csv-email' | 'manual'
  source_file_id text,
  created_at timestamptz DEFAULT now(),
  UNIQUE (restaurant_id, date)
);

-- New table for closed/locked daily snapshots
CREATE TABLE fc_daily_close (
  restaurant_id text REFERENCES restaurants(id),
  date date NOT NULL,
  fc_pct numeric,
  food_purchases numeric,
  revenue numeric,
  variance_vs_target numeric,
  variance_drivers jsonb,    -- {top_suppliers: [...], categories: [...]}
  closed_at timestamptz DEFAULT now(),
  acknowledged_at timestamptz,
  PRIMARY KEY (restaurant_id, date)
);

-- New view (illustrative — final SQL written during implementation; this captures
-- the shape and the columns the frontend reads)
CREATE VIEW daily_food_cost AS
WITH days AS (
  SELECT DISTINCT date FROM sales_daily
  UNION
  SELECT DISTINCT received_at::date FROM invoices
),
daily AS (
  SELECT
    r.id AS restaurant_id,
    d.date,
    COALESCE(
      SUM(i.total_amount) FILTER (WHERE i.is_food_cost = true),
      0
    ) AS food_purchases,
    COALESCE(s.revenue_total, 0) AS revenue
  FROM restaurants r
  CROSS JOIN days d
  LEFT JOIN invoices i
    ON i.restaurant_id = r.id AND i.received_at::date = d.date
  LEFT JOIN sales_daily s
    ON s.restaurant_id = r.id AND s.date = d.date
  GROUP BY r.id, d.date, s.revenue_total
)
SELECT
  restaurant_id,
  date,
  food_purchases,
  revenue,
  CASE WHEN revenue > 0
    THEN ROUND(food_purchases / revenue * 100, 2)
    ELSE NULL
  END AS fc_pct,
  -- 7-day rolling avg
  AVG(
    CASE WHEN revenue > 0 THEN food_purchases / revenue * 100 ELSE NULL END
  ) OVER (
    PARTITION BY restaurant_id
    ORDER BY date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) AS fc_pct_7d
FROM daily;
```

**RLS:** every new table inherits the multi-restaurant pattern already in use (`restaurant_id` filter via `user_restaurants` mapping).

### 5.3 Code surfaces

| Component | Status | Location |
|---|---|---|
| Postmark inbound webhook | **modified** — add attachment-type routing branch | `supabase/functions/postmark-inbound/index.ts` |
| `extract-invoice` edge fn | **unchanged** | `supabase/functions/extract-invoice/index.ts` |
| `process-sales-csv` edge fn | **NEW** — parses CSV (auto-delimiter, FR/EN), writes `sales_daily` row per date with `revenue_total` (required) + `cover_count` (optional). Per-item sales lines are stored on the existing menu/sales tables that already accept Lightspeed exports — no new per-item plumbing in v1. | `supabase/functions/process-sales-csv/index.ts` |
| `daily-fc-close` cron edge fn | **NEW** | `supabase/functions/daily-fc-close/index.ts` |
| `index.html` Food Cost section | **modified** — wrap existing table in tabs, add Daily + By Supplier | `index.html` (or split to `js/foodcost.js` after cleanup) |
| Onboarding wizard | **modified** — new lean 3-step flow | `js/onboarding.js` (after cleanup) |
| Supplier classification modal | **NEW** | `js/suppliers.js` (after cleanup) |
| Drift banner component | **NEW** | `js/alerts.js` (after cleanup) |
| Sales CSV upload UI | **NEW** (in-app) | `js/sales.js` (after cleanup) |
| CSV importer logic | **reused** — extracted to module during cleanup | `js/csv.js` (after cleanup) |

### 5.4 Cleanup pass (included in v1)

`index.html` is currently 7,955 lines (single file, vanilla JS, all inline). v1 adds ~600-1,000 more. Before the line count gets unmanageable, we split:

```
index.html                  → shell, sidebar, routing, top-level layout
styles.css                  → all CSS extracted
js/api.js                   → Supabase client + per-table query helpers
js/data.js                  → static demo data (BASE_MENU_ITEMS etc.)
js/auth.js                  → login, restaurant selector
js/foodcost.js              → Food Cost section (tabbed)
js/invoices.js              → invoices list + manual upload
js/suppliers.js             → supplier list + classification modal
js/onboarding.js            → wizard + persistent checklist
js/sales.js                 → sales CSV upload UI
js/alerts.js                → drift banner + acknowledgment logic
js/csv.js                   → shared CSV parser (auto-delimiter, FR/EN)
```

Loaded via `<script>` tags in `index.html`. **Still vanilla** — no framework, no bundler, no npm. Just better organized.

### 5.5 Domain + deploy (no changes)

- **Domain:** `culinaraos.com` (Namecheap, default nameservers) — unchanged.
- **Hosting:** Vercel project `culinara-app`, auto-deploys `main` → `www.culinaraos.com` — unchanged.
- **Backend:** Supabase project `qexjxndommlfqzngxqym` (Canada Central) — unchanged.
- **Mail-in:** `*@invoices.culinaraos.com` → Postmark → existing webhook URL — unchanged. (No new subdomain.)
- **Mail-out:** Not required for v1.

---

## 6. UX Flows

(See `.superpowers/brainstorm/6721-1777307757/content/design-section-3-ux-flows.html` for visual diagrams.)

### Flow 1 — New customer signup (lean wizard, ~5 min)
1. Land on culinaraos.com → click "Start free trial."
2. Email + password + restaurant name (e.g. "Joe's Pizza"). Submit.
3. App generates slug `joes`, creates restaurant + maps user. Provisions inbox `joes@invoices.culinaraos.com`. Sets `feature_flags.tier = 'lean'`.
4. **Step 1/3:** Set FC target % (default 25). Skippable.
5. **Step 2/3:** Show assigned invoice email + copy button. Skippable.
6. **Step 3/3:** Upload sales CSV OR paste yesterday's revenue. Skippable.
7. Land on Dashboard with empty Daily FC + persistent setup checklist.

### Flow 2 — Morning ritual
1. Manager opens app at 9am.
2. Dashboard hero: yesterday's FC% (red if drift), 7-day mini-chart, drift banner if applicable.
3. Tap FC number → Food Cost → Daily tab.
4. See variance breakdown + supplier impact.
5. Drill into specific invoice if needed.
6. Acknowledge banner (clears for the day).

### Flow 3 — First-time supplier classification
1. Invoice arrives from a never-before-seen supplier (e.g. flower vendor "Cinq Fleurs Floraux").
2. `extract-invoice` creates row in `suppliers` with `default_food_cost = null`.
3. `daily_food_cost` view excludes invoices with null classification.
4. Red dot appears on Suppliers + Invoices nav.
5. Manager taps red dot → modal: "New supplier: Cinq Fleurs. Food vendor? [Yes / No / Skip]."
6. Tap No → all invoices from supplier flagged `is_food_cost = false` via trigger. Daily FC recomputes.

### Flow 4 — Sales CSV by email
1. Manager exports yesterday's sales CSV from POS.
2. Forwards (or sends fresh) to `<slug>@invoices.culinaraos.com`.
3. Postmark → webhook → routing branch detects `.csv` with sales-shaped columns → `process-sales-csv`.
4. Reuses existing CSV parser. Writes `sales_daily` row.
5. `daily_food_cost` view auto-recomputes. Frontend updates on next load (or via Supabase real-time if open).

### Flow 5 — Drift alert (in-app)
1. 03:00 local cron per restaurant: snapshots yesterday into `fc_daily_close` (immutable closed-day record).
2. Computed at write-time: `variance_vs_target = fc_pct - fc_target_pct`. The "alert" is purely derived — there is no separate `alerts` table. Any `fc_daily_close` row with `|variance_vs_target| > 3pp` and `acknowledged_at IS NULL` qualifies as an unread alert.
3. Manager opens app → frontend queries `fc_daily_close WHERE acknowledged_at IS NULL AND |variance_vs_target| > 3` → red banner shown across top with the most recent unacknowledged drift.
4. Tap "View" → routes to Daily tab pre-scrolled to variance breakdown.
5. Tap "Acknowledge" → updates `fc_daily_close.acknowledged_at = now()`. Banner clears.

---

## 7. Wireframes

(See `.superpowers/brainstorm/6721-1777307757/content/design-section-4-wireframes.html` for high-fidelity mocks.)

### Wireframe 1 — Food Cost → Daily tab
- Sidebar: focused for lean tier (Dashboard, Food Cost, Invoices, Suppliers, Settings).
- Drift banner across top if applicable.
- Tab bar: Daily (active) / By Item / By Supplier.
- Hero row (3 cards): Yesterday's FC% (large, red/amber/green by status), 7-day rolling % + bar chart with target line, Today running % + invoice count.
- Variance card: "Why did yesterday miss target?" — top drivers (purchases up by category, sales delta).
- Supplier impact + Today's invoices feed (2-column).

### Wireframe 2 — Onboarding wizard
- 3 cards in sequence. Each step skippable. Each step has a contextual help line.
- After finish → Dashboard with empty-state + setup checklist (existing component).

### Wireframe 3 — Supplier classification modal
- Supplier name + address.
- Latest invoice line items preview.
- Three buttons: Skip / No (non-food) / Yes (food).
- Reclassification later updates all historical invoices via trigger.

### Wireframe 4 — Drift alert banner (3 states)
- **Red:** yesterday over target by >3pp.
- **Amber:** 7-day average drifting >3pp above target.
- **Green:** yesterday well under target (auto-dismisses after 24 hrs).
- Each has "View" + "Dismiss" actions.

---

## 8. Build Sequence (suggested)

To be refined into a full implementation plan via the writing-plans skill. Rough ordering:

1. **Cleanup pass** (1-2 days): split `index.html` into modules. Verify deploy still green. Commit.
2. **Schema migration** (half day): add columns + new tables + view. Migration file in `supabase/migrations/`. Test on Bottē + Arthur's data.
3. **Postmark webhook routing branch** (half day): detect attachment type, route to `process-sales-csv` for CSVs.
4. **`process-sales-csv` edge fn** (1 day): reuses CSV parser; writes `sales_daily`.
5. **In-app sales upload UI** (half day): manual CSV upload + paste-revenue input.
6. **Supplier classification: trigger + modal + nav red dot** (1 day): trigger on `invoices` insert, modal UI, red-dot nudge.
7. **Daily Food Cost view + Daily tab UI** (2 days): the marquee. Hero + 7-day chart + variance + supplier impact + today's invoices.
8. **By Supplier tab** (1 day): aggregations from `invoices` grouped by `supplier_id`.
9. **`pg_cron` daily close + drift banner UI** (1 day): cron writes immutable `fc_daily_close` row per restaurant per day, derived "drift" flag, in-app banner with acknowledge action.
10. **Lean signup wizard + feature flag system** (1-2 days): new wizard for lean tier; feature flag gates sidebar + sections.
11. **Onboarding setup checklist** (half day): leverage existing component; add v1 tasks.
12. **End-to-end testing on Arthur's** (half day): real data, real flow, fix what breaks.
13. **Pricing page + signup CTA on culinaraos.com landing** (1 day): convert visitors to trials.

**Total:** ~3-4 weeks of focused work.

---

## 9. Success Metrics

### Activation (per new customer)
- **Time to first FC%:** target < 24 hrs from signup.
- **Time to first supplier classified:** target < 7 days.
- **Setup checklist % complete after week 1:** target ≥ 60%.

### Retention
- **DAU/MAU on Food Cost page** for paying customers: target > 40% (daily-use product test).
- **% of mornings the GM opens the app:** target > 60% by week 4.

### Revenue
- **Trial → paid conversion:** target > 20% at month 1.
- **MRR per location** in line with $79-199 (independents) / $200-400 (groups).

### Product quality
- **% of invoices with confident food/non-food classification within 24 hrs of arrival:** target > 90%.
- **Drift banner false-positive rate:** target < 10%.

---

## 10. Open Risks + Issues

### Open issues to resolve before launch
- **Postmark outbound delivery problem.** User reports delivery is flaky despite test passing. Needs investigation (DKIM/SPF, domain reputation, sender approval status) — not blocking v1 because alerts are in-app, but blocks v1.1 email summary.
- **Postmark approval status.** Requested 2026-04-16. If still pending at v1 launch, may need a fallback transactional sender (Resend) for v1.1.

### Risks
- **Supplier classification gaps.** A skipped supplier silently excludes invoices from FC% — could cause "why is my number low?" support tickets. Mitigation: dashboard widget showing count of unclassified suppliers; nag if > 0 for > 7 days.
- **Sales CSV format drift.** A POS changes export columns and we miss the auto-detect → silent ingestion failure. Mitigation: log all rejected rows + email user with sample if > 10 rows fail. (v1.1 polish.)
- **Single-day FC% volatility in purchases-only mode.** Bulk delivery days look catastrophic. Mitigation: 7-day rolling is the trend metric; daily is informational only. UX language reinforces this.

### Decisions deferred to v1.1+
- Pricing model finalized (current proposal: $79-199/mo independent, $200-400/mo group — needs validation).
- Per-line invoice classification (Claude already runs; the UX is the lift).
- POS API integration order (Lightspeed first, then Square/Toast/Cluster).
- Recipe master schema (will inform theoretical FC view in v1.2).

---

## 11. References

- Project state: `PROJECT_STATE.md`
- Working agreement: `CLAUDE.md`
- Existing index.html (~7,955 lines): root of repo
- Visual mocks (this brainstorm session):
  - Welcome: `.superpowers/brainstorm/6721-1777307757/content/welcome.html`
  - Layout options: `.superpowers/brainstorm/6721-1777307757/content/foodcost-layouts.html`
  - Scope summary: `.superpowers/brainstorm/6721-1777307757/content/design-section-1-scope.html`
  - Architecture: `.superpowers/brainstorm/6721-1777307757/content/design-section-2-architecture.html`
  - UX flows: `.superpowers/brainstorm/6721-1777307757/content/design-section-3-ux-flows.html`
  - Wireframes: `.superpowers/brainstorm/6721-1777307757/content/design-section-4-wireframes.html`
- Recent commits relevant to v1 surface:
  - `0f70b02` — CSV import Cluster fixes
  - `841b01c` — CSV auto-detect delimiter + FR headers
  - `4ca2879` — Invoices UI wired to Supabase
  - `ee9f412` — Manual invoice upload
  - `f137704` — Postmark inbound webhook + extraction worker
  - `b0b87e3` — Onboarding checklist
  - `5efa21b` — Weekly CSV reminder
