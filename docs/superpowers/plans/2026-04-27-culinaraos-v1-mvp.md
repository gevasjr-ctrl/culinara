# CulinaraOS v1 MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a daily food cost product on www.culinaraos.com — invoice-in + sales-in → "yesterday closed at X% FC" rendered every morning, with supplier classification and drift alerts. v1 sells to independent restaurants via the lean wizard while keeping Bottē + Arthur's on full feature parity.

**Architecture:** Reuse the entire shipped stack (Supabase auth/DB/storage/edge fns, Postmark inbound webhook, vanilla HTML/JS/CSS, Vercel auto-deploy). Add 3 schema columns + 2 tables + 1 view + 2 edge fns + new JS modules loaded from existing `index.html`. Existing inline code stays untouched; new v1 code lives in `js/` modules from day one. (Full extraction of legacy inline code is deferred to a post-launch v1.0.5 cleanup plan.)

**Tech Stack:** Vanilla HTML/CSS/JS · Tailwind CDN · Chart.js · Supabase (Postgres, Auth, Storage, Edge Functions on Deno, RLS) · Postmark (inbound) · Vercel · pg_cron

**Spec:** `docs/superpowers/specs/2026-04-27-culinaraos-v1-mvp-design.md`

---

## File structure

### New files
```
supabase/migrations/20260427_v1_food_cost.sql            # schema delta
supabase/functions/process-sales-csv/index.ts            # sales CSV ingestion
supabase/functions/process-sales-csv/parser.ts           # CSV parser (testable)
supabase/functions/process-sales-csv/parser_test.ts      # parser unit tests
supabase/functions/daily-fc-close/index.ts               # cron-driven close
js/api.js                                                # Supabase client + query helpers (new code)
js/foodcost-daily.js                                     # Daily / By Supplier tabs
js/alerts.js                                             # drift banner + ack
js/suppliers-modal.js                                    # classification modal + red-dot logic
js/sales-upload.js                                       # in-app CSV upload UI
js/onboarding-wizard.js                                  # lean 3-step wizard
js/feature-flags.js                                      # sidebar gating
```

### Modified files
```
index.html                                               # add <script src="js/..."> tags, new modal/banner DOM
supabase/functions/postmark-inbound/index.ts             # attachment-type routing branch
supabase/migrations/                                     # NEW migration only — existing migration unchanged
```

### Untouched (reused as-is)
```
supabase/functions/extract-invoice/index.ts
supabase/functions/upload-invoice/index.ts
supabase/migrations/20260416_invoices.sql
All inline JS/CSS in index.html
```

---

## Conventions

- **Edge fn imports:** `import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'`
- **Edge fn auth:** `?token=<env var>` query param check at top of handler (pattern from `postmark-inbound`)
- **Migration safety:** Always `add column if not exists`, `create table if not exists`, `create or replace view`. Idempotent — safe to re-run.
- **Frontend modules:** Plain `<script src="js/x.js"></script>` tags in `index.html`. No bundler. Functions exposed on `window` if cross-module access needed; otherwise IIFE.
- **Commit messages:** Match existing style (e.g. `feat: …`, `fix: …`, `chore: …`). Lowercase. Single-line summary preferred.
- **Testing edge fns:** Deno's built-in test runner. Run with `deno test supabase/functions/<fn>/parser_test.ts --allow-all`.
- **Testing migrations:** Manual SQL verification queries documented per-task. Run via `supabase db remote commit` or psql against the project.
- **Testing frontend:** Manual browser testing against `localhost:3100` (existing dev server) with explicit expected behavior per task.
- **Deploy:** `supabase functions deploy <name>` for edge fns; `git push origin main` for everything else (Vercel auto-deploys).

---

## Task 1: Schema migration

**Files:**
- Create: `supabase/migrations/20260427_v1_food_cost.sql`

- [ ] **Step 1: Create the migration file with all v1 schema changes**

Write `supabase/migrations/20260427_v1_food_cost.sql`:

```sql
-- v1 MVP: daily food cost engine
-- Additive only. Idempotent. Safe to re-run.

------------------------------------------------------------
-- 1. Column additions to existing tables
------------------------------------------------------------
alter table public.invoices
  add column if not exists is_food_cost boolean;

alter table public.suppliers
  add column if not exists default_food_cost boolean;

alter table public.restaurants
  add column if not exists fc_target_pct numeric default 25,
  add column if not exists feature_flags jsonb default '{"tier":"full"}'::jsonb;

------------------------------------------------------------
-- 2. New table: sales_daily
------------------------------------------------------------
create table if not exists public.sales_daily (
  id uuid primary key default gen_random_uuid(),
  restaurant_id text not null references public.restaurants(id),
  date date not null,
  revenue_total numeric(12,2) not null,
  cover_count integer,
  source text not null,                      -- 'csv-upload' | 'csv-email' | 'manual'
  source_file_id text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (restaurant_id, date)
);

create index if not exists sales_daily_restaurant_date_idx
  on public.sales_daily (restaurant_id, date desc);

alter table public.sales_daily enable row level security;

drop policy if exists "select sales_daily for own restaurants" on public.sales_daily;
create policy "select sales_daily for own restaurants"
  on public.sales_daily for select
  using (
    restaurant_id in (
      select restaurant_id from public.user_restaurants where user_id = auth.uid()
    )
  );

drop policy if exists "service-role writes sales_daily" on public.sales_daily;
create policy "service-role writes sales_daily"
  on public.sales_daily for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

------------------------------------------------------------
-- 3. New table: fc_daily_close (immutable closed-day snapshots)
------------------------------------------------------------
create table if not exists public.fc_daily_close (
  restaurant_id text not null references public.restaurants(id),
  date date not null,
  fc_pct numeric(5,2),
  food_purchases numeric(12,2),
  revenue numeric(12,2),
  fc_target_pct numeric(5,2),
  variance_vs_target numeric(5,2),         -- fc_pct - fc_target_pct (signed)
  variance_drivers jsonb,                  -- {top_suppliers: [...], categories: [...]}
  closed_at timestamptz default now(),
  acknowledged_at timestamptz,
  primary key (restaurant_id, date)
);

create index if not exists fc_daily_close_unack_idx
  on public.fc_daily_close (restaurant_id, date desc)
  where acknowledged_at is null;

alter table public.fc_daily_close enable row level security;

drop policy if exists "select fc_daily_close for own restaurants" on public.fc_daily_close;
create policy "select fc_daily_close for own restaurants"
  on public.fc_daily_close for select
  using (
    restaurant_id in (
      select restaurant_id from public.user_restaurants where user_id = auth.uid()
    )
  );

drop policy if exists "update ack fc_daily_close for own restaurants" on public.fc_daily_close;
create policy "update ack fc_daily_close for own restaurants"
  on public.fc_daily_close for update
  using (
    restaurant_id in (
      select restaurant_id from public.user_restaurants where user_id = auth.uid()
    )
  )
  with check (
    restaurant_id in (
      select restaurant_id from public.user_restaurants where user_id = auth.uid()
    )
  );

drop policy if exists "service-role writes fc_daily_close" on public.fc_daily_close;
create policy "service-role writes fc_daily_close"
  on public.fc_daily_close for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

------------------------------------------------------------
-- 4. View: daily_food_cost (live aggregation, not materialized)
------------------------------------------------------------
create or replace view public.daily_food_cost as
with date_range as (
  select restaurant_id, date
  from public.sales_daily
  union
  select restaurant_id, received_at::date as date
  from public.invoices
  where received_at is not null
),
daily as (
  select
    dr.restaurant_id,
    dr.date,
    coalesce(
      (select sum(i.total_amount)
       from public.invoices i
       where i.restaurant_id = dr.restaurant_id
         and i.received_at::date = dr.date
         and i.is_food_cost = true),
      0
    ) as food_purchases,
    coalesce(
      (select s.revenue_total
       from public.sales_daily s
       where s.restaurant_id = dr.restaurant_id
         and s.date = dr.date),
      0
    ) as revenue
  from date_range dr
  group by dr.restaurant_id, dr.date
)
select
  restaurant_id,
  date,
  food_purchases,
  revenue,
  case when revenue > 0
    then round((food_purchases / revenue) * 100, 2)
    else null
  end as fc_pct,
  avg(case when revenue > 0 then (food_purchases / revenue) * 100 else null end)
    over (partition by restaurant_id order by date
          rows between 6 preceding and current row) as fc_pct_7d
from daily;

-- View RLS via security_invoker (so policies on underlying tables apply)
alter view public.daily_food_cost set (security_invoker = on);

------------------------------------------------------------
-- 5. Triggers
------------------------------------------------------------

-- 5a. On invoice insert: inherit is_food_cost from supplier
create or replace function public.invoices_inherit_food_cost()
returns trigger
language plpgsql
security definer
as $$
begin
  if new.is_food_cost is null and new.supplier_id is not null then
    select default_food_cost into new.is_food_cost
    from public.suppliers
    where id = new.supplier_id;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_invoices_inherit_food_cost on public.invoices;
create trigger trg_invoices_inherit_food_cost
  before insert on public.invoices
  for each row
  execute function public.invoices_inherit_food_cost();

-- 5b. On supplier reclassification: backfill all historical invoices
create or replace function public.suppliers_backfill_food_cost()
returns trigger
language plpgsql
security definer
as $$
begin
  if new.default_food_cost is distinct from old.default_food_cost then
    update public.invoices
    set is_food_cost = new.default_food_cost
    where supplier_id = new.id;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_suppliers_backfill_food_cost on public.suppliers;
create trigger trg_suppliers_backfill_food_cost
  after update of default_food_cost on public.suppliers
  for each row
  execute function public.suppliers_backfill_food_cost();
```

- [ ] **Step 2: Apply migration to Supabase**

Run via supabase CLI from repo root:

```bash
supabase db push
```

Expected: `Applying migration 20260427_v1_food_cost.sql` followed by `Finished supabase db push.`

If `supabase db push` is unavailable or fails, paste the SQL into the Supabase SQL Editor (Studio → SQL Editor) and run.

- [ ] **Step 3: Verify schema with smoke queries**

Run each query in Supabase SQL Editor; expected results in comments.

```sql
-- Verify columns added
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'invoices'
  and column_name = 'is_food_cost';
-- Expected: 1 row with is_food_cost / boolean

select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'restaurants'
  and column_name in ('fc_target_pct', 'feature_flags');
-- Expected: 2 rows

-- Verify tables exist
select count(*) from public.sales_daily;
-- Expected: 0 (empty)

select count(*) from public.fc_daily_close;
-- Expected: 0 (empty)

-- Verify view returns rows for Bottē (which has invoices)
select count(*) from public.daily_food_cost where restaurant_id = 'botte';
-- Expected: 1+ rows (Bottē has historical invoices)

-- Verify Bottē view shape
select date, food_purchases, revenue, fc_pct, fc_pct_7d
from public.daily_food_cost
where restaurant_id = 'botte'
order by date desc
limit 5;
-- Expected: 5 rows, fc_pct may be null where no sales_daily row yet
```

- [ ] **Step 4: Backfill Bottē + Arthur's feature flags**

Run in SQL Editor:

```sql
update public.restaurants
set feature_flags = '{"tier":"full"}'::jsonb
where id in ('botte', 'arthurs');
-- Expected: 2 rows updated
```

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260427_v1_food_cost.sql
git commit -m "feat: v1 schema — daily food cost view, sales_daily, fc_daily_close, classification triggers"
```

---

## Task 2: Modify postmark-inbound for attachment-type routing

**Files:**
- Modify: `supabase/functions/postmark-inbound/index.ts`

- [ ] **Step 1: Add CSV detection helper near top of file**

Insert immediately after the `normalizeEmail` function (around line 41):

```typescript
function looksLikeSalesCsv(att: PostmarkAttachment): boolean {
  const name = (att.Name ?? '').toLowerCase()
  const type = (att.ContentType ?? '').toLowerCase()
  if (!name.endsWith('.csv') && !type.includes('csv') && !type.includes('text/plain')) {
    return false
  }
  // Decode first ~2KB and look for sales-shaped column headers
  try {
    const sample = atob((att.Content ?? '').slice(0, 4000)).toLowerCase()
    const headerLine = sample.split('\n').slice(0, 3).join(' ')
    // Sales CSVs include at least one revenue-or-sales-shaped column
    const salesHints = [
      'revenue', 'sales', 'gross', 'net sales', 'total ttc', 'total ht',
      'item', 'menu item', 'plat', 'product', 'ventes',
    ]
    return salesHints.some((h) => headerLine.includes(h))
  } catch {
    return false
  }
}
```

- [ ] **Step 2: Add routing branch right after attachments are uploaded but before the extraction trigger**

Find the existing block:

```typescript
  if (attachmentRefs.length) {
    await supabase
      .from('invoices')
      .update({ attachments: attachmentRefs, status: 'pending_extraction' })
      .eq('id', invoice.id)

    // Fire-and-forget: trigger extraction worker.
    ...
```

Replace with:

```typescript
  // Detect if any attachment looks like a sales CSV.
  const salesAtts = (payload.Attachments ?? []).filter(looksLikeSalesCsv)
  const hasSalesCsv = salesAtts.length > 0

  if (attachmentRefs.length) {
    await supabase
      .from('invoices')
      .update({
        attachments: attachmentRefs,
        status: hasSalesCsv ? 'sales_csv_received' : 'pending_extraction',
      })
      .eq('id', invoice.id)

    const supabaseUrl = Deno.env.get('SUPABASE_URL')!
    const serviceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!

    // Branch: route to sales processor OR invoice extractor (or both if mixed)
    const triggers: Promise<unknown>[] = []

    if (hasSalesCsv) {
      triggers.push(
        fetch(`${supabaseUrl}/functions/v1/process-sales-csv`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${serviceKey}`,
          },
          body: JSON.stringify({ invoice_id: invoice.id }),
        }).catch((e) => console.error('process-sales-csv trigger failed', e))
      )
    }

    // If there are non-CSV attachments OR no CSV at all, also run invoice extraction
    const hasNonCsv = attachmentRefs.some(
      (a) => !a.name.toLowerCase().endsWith('.csv')
    )
    if (!hasSalesCsv || hasNonCsv) {
      triggers.push(
        fetch(`${supabaseUrl}/functions/v1/extract-invoice`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${serviceKey}`,
          },
          body: JSON.stringify({ invoice_id: invoice.id }),
        }).catch((e) => console.error('extract-invoice trigger failed', e))
      )
    }

    try {
      // @ts-ignore — EdgeRuntime is available in Supabase edge functions
      if (typeof EdgeRuntime !== 'undefined' && EdgeRuntime.waitUntil) {
        // @ts-ignore
        for (const t of triggers) EdgeRuntime.waitUntil(t)
      }
    } catch (e) {
      console.error('failed to schedule downstream', e)
    }
  }
```

- [ ] **Step 3: Deploy**

```bash
supabase functions deploy postmark-inbound
```

Expected: `Deployed Function postmark-inbound on project qexjxndommlfqzngxqym.`

- [ ] **Step 4: Smoke-test routing branch with curl**

Send a fake Postmark POST that includes a sales-shaped CSV attachment (no PDF). The base64 below decodes to `Date,Revenue\n2026-04-26,1234.56`.

```bash
TOKEN=$(grep POSTMARK_WEBHOOK_TOKEN ~/.claude/projects/-Users-thomasgevas-Desktop-culinara/memory/MEMORY.md | head -1 | awk '{print $NF}')
# Or: get from Supabase dashboard → Edge Function Secrets

curl -X POST "https://qexjxndommlfqzngxqym.supabase.co/functions/v1/postmark-inbound?token=$TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "FromFull": {"Email": "test@bottepizza.ca", "Name": "Test"},
    "ToFull": [{"Email": "botte@invoices.culinaraos.com"}],
    "Subject": "Test sales CSV",
    "MessageID": "test-routing-1",
    "Date": "2026-04-27T09:00:00Z",
    "Attachments": [{
      "Name": "sales.csv",
      "ContentType": "text/csv",
      "Content": "RGF0ZSxSZXZlbnVlCjIwMjYtMDQtMjYsMTIzNC41Ng==",
      "ContentLength": 30
    }]
  }'
```

Expected: HTTP 200 with `{"ok":true,...}`. Then in Supabase SQL Editor:

```sql
select status from public.invoices where message_id = 'test-routing-1';
-- Expected: 1 row with status = 'sales_csv_received'
```

- [ ] **Step 5: Cleanup test row + commit**

```sql
delete from public.invoices where message_id = 'test-routing-1';
```

```bash
git add supabase/functions/postmark-inbound/index.ts
git commit -m "feat(postmark-inbound): route sales-shaped CSVs to process-sales-csv"
```

---

## Task 3: process-sales-csv parser (TDD'd module)

**Files:**
- Create: `supabase/functions/process-sales-csv/parser.ts`
- Create: `supabase/functions/process-sales-csv/parser_test.ts`

- [ ] **Step 1: Write the failing tests first**

Create `supabase/functions/process-sales-csv/parser_test.ts`:

```typescript
import { assertEquals } from 'https://deno.land/std@0.224.0/assert/mod.ts'
import { parseSalesCsv } from './parser.ts'

Deno.test('parseSalesCsv — basic comma-delimited single day', () => {
  const csv = 'Date,Revenue\n2026-04-26,1234.56'
  const result = parseSalesCsv(csv)
  assertEquals(result.rows, [
    { date: '2026-04-26', revenue_total: 1234.56, cover_count: null },
  ])
  assertEquals(result.delimiter, ',')
})

Deno.test('parseSalesCsv — semicolon delimiter (FR locale)', () => {
  const csv = 'Date;Revenue\n2026-04-26;1234,56'
  const result = parseSalesCsv(csv)
  assertEquals(result.rows[0].revenue_total, 1234.56)
  assertEquals(result.delimiter, ';')
})

Deno.test('parseSalesCsv — tab delimiter', () => {
  const csv = 'Date\tRevenue\n2026-04-26\t1234.56'
  const result = parseSalesCsv(csv)
  assertEquals(result.delimiter, '\t')
})

Deno.test('parseSalesCsv — French headers', () => {
  const csv = 'Date,Ventes,Couverts\n2026-04-26,1234.56,42'
  const result = parseSalesCsv(csv)
  assertEquals(result.rows[0].revenue_total, 1234.56)
  assertEquals(result.rows[0].cover_count, 42)
})

Deno.test('parseSalesCsv — Cluster sep= directive', () => {
  const csv = 'sep=;\nDate;Revenue\n2026-04-26;1234.56'
  const result = parseSalesCsv(csv)
  assertEquals(result.delimiter, ';')
  assertEquals(result.rows[0].revenue_total, 1234.56)
})

Deno.test('parseSalesCsv — comma thousands separators', () => {
  const csv = 'Date,Revenue\n2026-04-26,"1,234.56"'
  const result = parseSalesCsv(csv)
  assertEquals(result.rows[0].revenue_total, 1234.56)
})

Deno.test('parseSalesCsv — multiple days aggregated', () => {
  const csv = 'Date,Revenue\n2026-04-25,500\n2026-04-26,750\n2026-04-25,200'
  const result = parseSalesCsv(csv)
  // Same-date rows summed
  const apr25 = result.rows.find((r) => r.date === '2026-04-25')
  assertEquals(apr25?.revenue_total, 700)
})

Deno.test('parseSalesCsv — rejects unrecognized headers', () => {
  const csv = 'Foo,Bar\n1,2'
  const result = parseSalesCsv(csv)
  assertEquals(result.rows.length, 0)
  assertEquals(result.error, 'no_recognized_columns')
})

Deno.test('parseSalesCsv — returns parse errors per row without dropping good rows', () => {
  const csv = 'Date,Revenue\n2026-04-26,1234.56\nbroken,row\n2026-04-27,500'
  const result = parseSalesCsv(csv)
  assertEquals(result.rows.length, 2)
  assertEquals(result.skipped, 1)
})
```

- [ ] **Step 2: Run tests — expect them all to fail (parser doesn't exist)**

```bash
cd supabase/functions/process-sales-csv
deno test parser_test.ts --allow-all
```

Expected: All 9 tests fail with `Cannot find module './parser.ts'` or similar.

- [ ] **Step 3: Implement the parser**

Create `supabase/functions/process-sales-csv/parser.ts`:

```typescript
export interface SalesRow {
  date: string                 // YYYY-MM-DD
  revenue_total: number
  cover_count: number | null
}

export interface ParseResult {
  rows: SalesRow[]
  delimiter: string
  skipped: number
  error?: string
}

const REVENUE_HEADERS = [
  'revenue', 'sales', 'gross', 'net sales', 'total ttc', 'total ht',
  'ventes', 'chiffre d\'affaires', 'ca',
]
const DATE_HEADERS = ['date', 'jour', 'day']
const COVER_HEADERS = ['covers', 'cover_count', 'guests', 'couverts', 'pax']

function detectDelimiter(line: string): string {
  const candidates = [',', ';', '\t', '|']
  let best = ','
  let bestCount = 0
  for (const c of candidates) {
    const n = line.split(c).length - 1
    if (n > bestCount) {
      best = c
      bestCount = n
    }
  }
  return best
}

function stripSepDirective(text: string): { text: string; forced?: string } {
  const m = /^sep=(.)\s*\r?\n/i.exec(text)
  if (m) {
    return { text: text.slice(m[0].length), forced: m[1] }
  }
  return { text }
}

function normalizeNumber(raw: string): number {
  if (!raw) return NaN
  let s = raw.trim().replace(/^"|"$/g, '')
  // FR-locale comma decimal: "1234,56" → "1234.56" if no period
  if (s.includes(',') && !s.includes('.')) {
    s = s.replace(/,/g, '.')
  } else {
    // Remove comma thousands separators: "1,234.56" → "1234.56"
    s = s.replace(/,/g, '')
  }
  return parseFloat(s)
}

function findColIdx(headers: string[], candidates: string[]): number {
  const lower = headers.map((h) => h.trim().toLowerCase())
  for (let i = 0; i < lower.length; i++) {
    for (const cand of candidates) {
      if (lower[i] === cand || lower[i].includes(cand)) {
        return i
      }
    }
  }
  return -1
}

// Minimal CSV row splitter that handles quoted fields with delimiters inside
function splitCsvLine(line: string, delim: string): string[] {
  const out: string[] = []
  let buf = ''
  let inQuote = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (ch === '"') {
      inQuote = !inQuote
      continue
    }
    if (ch === delim && !inQuote) {
      out.push(buf)
      buf = ''
    } else {
      buf += ch
    }
  }
  out.push(buf)
  return out
}

export function parseSalesCsv(text: string): ParseResult {
  const stripped = stripSepDirective(text)
  const lines = stripped.text.split(/\r?\n/).filter((l) => l.trim() !== '')
  if (lines.length < 2) {
    return { rows: [], delimiter: ',', skipped: 0, error: 'too_few_lines' }
  }

  const delimiter = stripped.forced ?? detectDelimiter(lines[0])
  const headers = splitCsvLine(lines[0], delimiter)
  const dateIdx = findColIdx(headers, DATE_HEADERS)
  const revIdx = findColIdx(headers, REVENUE_HEADERS)
  const coverIdx = findColIdx(headers, COVER_HEADERS)

  if (dateIdx === -1 || revIdx === -1) {
    return { rows: [], delimiter, skipped: 0, error: 'no_recognized_columns' }
  }

  const byDate = new Map<string, { revenue: number; covers: number | null }>()
  let skipped = 0

  for (let i = 1; i < lines.length; i++) {
    const cells = splitCsvLine(lines[i], delimiter)
    const dateRaw = cells[dateIdx]?.trim() ?? ''
    const revRaw = cells[revIdx]?.trim() ?? ''
    if (!dateRaw || !revRaw) {
      skipped++
      continue
    }
    // Accept YYYY-MM-DD only for v1 (POS exports usually output ISO)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateRaw)) {
      skipped++
      continue
    }
    const rev = normalizeNumber(revRaw)
    if (isNaN(rev)) {
      skipped++
      continue
    }
    const covers = coverIdx >= 0 ? parseInt(cells[coverIdx]?.trim() ?? '', 10) : NaN
    const existing = byDate.get(dateRaw)
    if (existing) {
      existing.revenue += rev
      if (!isNaN(covers)) existing.covers = (existing.covers ?? 0) + covers
    } else {
      byDate.set(dateRaw, {
        revenue: rev,
        covers: !isNaN(covers) ? covers : null,
      })
    }
  }

  const rows: SalesRow[] = Array.from(byDate.entries())
    .map(([date, v]) => ({
      date,
      revenue_total: Math.round(v.revenue * 100) / 100,
      cover_count: v.covers,
    }))
    .sort((a, b) => (a.date < b.date ? -1 : 1))

  return { rows, delimiter, skipped }
}
```

- [ ] **Step 4: Run tests — expect all to pass**

```bash
cd supabase/functions/process-sales-csv
deno test parser_test.ts --allow-all
```

Expected: `9 passed | 0 failed`

- [ ] **Step 5: Commit**

```bash
git add supabase/functions/process-sales-csv/parser.ts supabase/functions/process-sales-csv/parser_test.ts
git commit -m "feat(process-sales-csv): TDD'd CSV parser with FR/EN headers, multi-delimiter, sep= directive"
```

---

## Task 4: process-sales-csv edge function handler

**Files:**
- Create: `supabase/functions/process-sales-csv/index.ts`

- [ ] **Step 1: Implement the handler**

Create `supabase/functions/process-sales-csv/index.ts`:

```typescript
// Supabase Edge Function: process-sales-csv
// Triggered by postmark-inbound when an email arrives with a sales-shaped CSV.
// Downloads the CSV from Storage, parses it, and writes sales_daily rows.
//
// Endpoint: https://qexjxndommlfqzngxqym.supabase.co/functions/v1/process-sales-csv
// Auth: requires service-role bearer token (called only by other edge fns / cron)

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { parseSalesCsv } from './parser.ts'

const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
)

interface InvoiceRow {
  id: string
  restaurant_id: string
  attachments: Array<{ path: string; name: string; type: string; size: number }>
}

Deno.serve(async (req) => {
  if (req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 })
  }
  const authHeader = req.headers.get('authorization') ?? ''
  if (!authHeader.startsWith('Bearer ')) {
    return new Response('Unauthorized', { status: 401 })
  }

  let body: { invoice_id: string }
  try {
    body = await req.json()
  } catch {
    return new Response('Invalid JSON', { status: 400 })
  }
  if (!body.invoice_id) {
    return new Response('invoice_id required', { status: 400 })
  }

  // Load invoice + attachments
  const { data: inv, error: invErr } = await supabase
    .from('invoices')
    .select('id, restaurant_id, attachments')
    .eq('id', body.invoice_id)
    .single<InvoiceRow>()

  if (invErr || !inv) {
    console.error('invoice not found', body.invoice_id, invErr)
    return new Response(JSON.stringify({ error: 'invoice_not_found' }), { status: 404 })
  }

  const csvAtts = (inv.attachments ?? []).filter((a) =>
    a.name.toLowerCase().endsWith('.csv') || a.type.toLowerCase().includes('csv')
  )

  if (csvAtts.length === 0) {
    console.warn('no csv attachments on invoice', inv.id)
    return new Response(JSON.stringify({ ok: true, processed: 0, reason: 'no_csv' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  const totals = { rows_inserted: 0, rows_updated: 0, files_processed: 0, files_failed: 0 }

  for (const att of csvAtts) {
    try {
      const { data: file, error: dlErr } = await supabase.storage
        .from('invoices')
        .download(att.path)
      if (dlErr || !file) {
        console.error('download failed', att.path, dlErr)
        totals.files_failed++
        continue
      }
      const text = await file.text()
      const parsed = parseSalesCsv(text)
      if (parsed.error) {
        console.warn('parse error', att.path, parsed.error)
        totals.files_failed++
        continue
      }

      // Upsert each (restaurant_id, date) row
      for (const row of parsed.rows) {
        const { error: upErr } = await supabase
          .from('sales_daily')
          .upsert(
            {
              restaurant_id: inv.restaurant_id,
              date: row.date,
              revenue_total: row.revenue_total,
              cover_count: row.cover_count,
              source: 'csv-email',
              source_file_id: inv.id,
              updated_at: new Date().toISOString(),
            },
            { onConflict: 'restaurant_id,date' }
          )
        if (upErr) {
          console.error('upsert failed', row, upErr)
        } else {
          totals.rows_inserted++
        }
      }
      totals.files_processed++
    } catch (e) {
      console.error('attachment processing exception', att.path, e)
      totals.files_failed++
    }
  }

  // Mark the invoice as processed (use status 'sales_csv_processed' to distinguish from invoice extraction)
  await supabase
    .from('invoices')
    .update({ status: 'sales_csv_processed', updated_at: new Date().toISOString() })
    .eq('id', inv.id)

  return new Response(JSON.stringify({ ok: true, ...totals }), {
    headers: { 'Content-Type': 'application/json' },
  })
})
```

- [ ] **Step 2: Deploy**

```bash
supabase functions deploy process-sales-csv
```

Expected: `Deployed Function process-sales-csv on project qexjxndommlfqzngxqym.`

- [ ] **Step 3: End-to-end smoke test**

Send a real-shaped CSV through the Postmark webhook (reusing curl from Task 2 step 4). After the call returns, check both invoices and sales_daily:

```sql
select status from public.invoices where message_id = 'test-routing-2';
-- Expected: status = 'sales_csv_processed'

select * from public.sales_daily where restaurant_id = 'botte' and source = 'csv-email';
-- Expected: at least 1 row with date 2026-04-26 and revenue_total 1234.56
```

- [ ] **Step 4: Cleanup test data + commit**

```sql
delete from public.sales_daily where source = 'csv-email' and source_file_id in (
  select id from public.invoices where message_id = 'test-routing-2'
);
delete from public.invoices where message_id = 'test-routing-2';
```

```bash
git add supabase/functions/process-sales-csv/index.ts
git commit -m "feat: process-sales-csv edge fn — ingests sales CSVs from Postmark inbound into sales_daily"
```

---

## Task 5: daily-fc-close cron edge function

**Files:**
- Create: `supabase/functions/daily-fc-close/index.ts`

- [ ] **Step 1: Implement the handler**

Create `supabase/functions/daily-fc-close/index.ts`:

```typescript
// Supabase Edge Function: daily-fc-close
// Invoked by pg_cron at 03:00 local each day. For each restaurant with data
// for "yesterday", snapshots the row from daily_food_cost into fc_daily_close
// and computes variance_drivers (top suppliers by yesterday's purchase impact).
//
// Endpoint: https://qexjxndommlfqzngxqym.supabase.co/functions/v1/daily-fc-close
// Auth: ?token=<DAILY_FC_CLOSE_TOKEN> query param

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const EXPECTED_TOKEN = Deno.env.get('DAILY_FC_CLOSE_TOKEN') ?? ''

const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
)

function yesterdayISO(): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

Deno.serve(async (req) => {
  const url = new URL(req.url)
  const token = url.searchParams.get('token') ?? ''
  if (!EXPECTED_TOKEN || token !== EXPECTED_TOKEN) {
    return new Response('Unauthorized', { status: 401 })
  }

  // Allow optional ?date=YYYY-MM-DD override for backfill / testing
  const targetDate = url.searchParams.get('date') ?? yesterdayISO()

  // Fetch all daily_food_cost rows for the target date
  const { data: rows, error: rowsErr } = await supabase
    .from('daily_food_cost')
    .select('restaurant_id, date, food_purchases, revenue, fc_pct, fc_pct_7d')
    .eq('date', targetDate)

  if (rowsErr) {
    console.error('fetch daily_food_cost failed', rowsErr)
    return new Response(JSON.stringify({ error: 'fetch_failed', detail: rowsErr.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // Fetch fc_target_pct per restaurant in one go
  const restaurantIds = (rows ?? []).map((r) => r.restaurant_id)
  const { data: rests } = await supabase
    .from('restaurants')
    .select('id, fc_target_pct')
    .in('id', restaurantIds)
  const targets = new Map((rests ?? []).map((r) => [r.id, r.fc_target_pct ?? 25]))

  let closed = 0
  for (const row of rows ?? []) {
    const target = Number(targets.get(row.restaurant_id) ?? 25)
    const fcPct = row.fc_pct == null ? null : Number(row.fc_pct)
    const variance = fcPct == null ? null : Math.round((fcPct - target) * 100) / 100

    // Compute variance_drivers: top 3 suppliers by purchase impact for the day
    const { data: supplierAgg } = await supabase
      .from('invoices')
      .select('supplier_name, total_amount')
      .eq('restaurant_id', row.restaurant_id)
      .eq('is_food_cost', true)
      .gte('received_at', `${targetDate}T00:00:00Z`)
      .lt('received_at', `${targetDate}T23:59:59Z`)

    const sumBy = new Map<string, number>()
    for (const inv of supplierAgg ?? []) {
      const name = inv.supplier_name ?? 'Unknown'
      sumBy.set(name, (sumBy.get(name) ?? 0) + Number(inv.total_amount ?? 0))
    }
    const topSuppliers = Array.from(sumBy.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([name, total]) => ({ name, total: Math.round(total * 100) / 100 }))

    const { error: upErr } = await supabase
      .from('fc_daily_close')
      .upsert(
        {
          restaurant_id: row.restaurant_id,
          date: row.date,
          fc_pct: fcPct,
          food_purchases: Number(row.food_purchases ?? 0),
          revenue: Number(row.revenue ?? 0),
          fc_target_pct: target,
          variance_vs_target: variance,
          variance_drivers: { top_suppliers: topSuppliers },
          closed_at: new Date().toISOString(),
        },
        { onConflict: 'restaurant_id,date' }
      )
    if (upErr) {
      console.error('close upsert failed', row.restaurant_id, upErr)
    } else {
      closed++
    }
  }

  return new Response(JSON.stringify({ ok: true, date: targetDate, closed }), {
    headers: { 'Content-Type': 'application/json' },
  })
})
```

- [ ] **Step 2: Set the secret**

```bash
# Generate a random token
openssl rand -hex 32
# Copy the output, then:
supabase secrets set DAILY_FC_CLOSE_TOKEN=<paste_value>
```

Save the token in `~/.claude/projects/-Users-thomasgevas-Desktop-culinara/memory/MEMORY.md` (NOT in repo).

- [ ] **Step 3: Deploy**

```bash
supabase functions deploy daily-fc-close
```

- [ ] **Step 4: Smoke-test by manually invoking for a backfill date**

Pick a date Bottē has invoice data for (e.g. 2026-04-13):

```bash
TOKEN=<the token from step 2>
curl -X POST "https://qexjxndommlfqzngxqym.supabase.co/functions/v1/daily-fc-close?token=$TOKEN&date=2026-04-13"
```

Expected: `{"ok":true,"date":"2026-04-13","closed":N}` where N >= 1.

```sql
select * from public.fc_daily_close where date = '2026-04-13';
-- Expected: row with fc_pct, variance_vs_target, variance_drivers JSON
```

- [ ] **Step 5: Schedule via pg_cron**

In Supabase SQL Editor:

```sql
-- Enable pg_cron if not already
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Schedule daily run at 07:00 UTC (= 03:00 EDT)
-- pg_cron stores schedules in cron.job; idempotent unschedule/reschedule
do $$
declare
  job_id bigint;
begin
  select jobid into job_id from cron.job where jobname = 'daily-fc-close';
  if found then
    perform cron.unschedule(job_id);
  end if;
end $$;

select cron.schedule(
  'daily-fc-close',
  '0 7 * * *',  -- every day at 07:00 UTC
  $$
  select net.http_post(
    url := 'https://qexjxndommlfqzngxqym.supabase.co/functions/v1/daily-fc-close?token=' || current_setting('app.daily_fc_close_token'),
    body := '{}'::jsonb,
    timeout_milliseconds := 60000
  );
  $$
);
```

Then set the GUC for the token (so SQL doesn't have a literal secret):

```sql
-- Run as a privileged user (Supabase role: service_role / postgres)
alter database postgres set app.daily_fc_close_token = '<paste_token_here>';
```

- [ ] **Step 6: Commit**

```bash
git add supabase/functions/daily-fc-close/index.ts
git commit -m "feat: daily-fc-close edge fn + pg_cron schedule for 03:00 EDT close"
```

---

## Task 6: Add tab structure to Food Cost section

**Files:**
- Modify: `index.html` — Food Cost section

- [ ] **Step 1: Locate Food Cost section in index.html**

Run:
```bash
grep -n 'SECTION: FOOD COST\|fc_title\|fc-subtitle' /Users/thomasgevas/Desktop/culinara/index.html | head -5
```

Note the line numbers. The section header is around line 985; the table starts around line 1038.

- [ ] **Step 2: Wrap existing item-table content in a new tab structure**

Find the Food Cost section's main container (the `<div>` that contains the section title, tip box, and item-level table — should look approximately like):

```html
<!-- ===== SECTION: FOOD COST ===== -->
<section data-section="profitability" ...>
  <div>
    <div class="section-title" data-i18n="fc_title">Food Cost by Item</div>
    <div id="fc-subtitle" class="section-sub">Bottē Restaurant · Jan 1 – Apr 13, 2026</div>
  </div>
  ... tip box ...
  <table>... item-level table ...</table>
  ...
</section>
```

Insert the tab bar **immediately after the section title block** and wrap the existing tip + table + summary content in a `<div id="fc-tab-by-item">`. Add empty containers for the other two tabs:

```html
<!-- Tab bar (NEW) -->
<div class="fc-tab-bar" style="display:flex;gap:4px;border-bottom:1px solid var(--border);padding:0 0 8px 0;margin:14px 0 18px 0;">
  <button class="fc-tab fc-tab-active" data-tab="daily" onclick="window.foodcostShowTab('daily')">Daily</button>
  <button class="fc-tab" data-tab="by-item" onclick="window.foodcostShowTab('by-item')">By Item</button>
  <button class="fc-tab" data-tab="by-supplier" onclick="window.foodcostShowTab('by-supplier')">By Supplier</button>
</div>

<!-- Tab: Daily (NEW — populated by js/foodcost-daily.js) -->
<div id="fc-tab-daily" class="fc-tab-panel"></div>

<!-- Tab: By Item (existing content moved here) -->
<div id="fc-tab-by-item" class="fc-tab-panel" style="display:none;">
  <!-- existing tip box, item table, totals — unchanged -->
</div>

<!-- Tab: By Supplier (NEW — populated by js/foodcost-daily.js) -->
<div id="fc-tab-by-supplier" class="fc-tab-panel" style="display:none;"></div>
```

Move the existing tip box, item table, and totals INTO the `<div id="fc-tab-by-item">` container. The Daily and By Supplier panels start empty — they're populated by `foodcost-daily.js` in later tasks.

- [ ] **Step 3: Add tab styling to existing inline `<style>` block**

In the inline `<style>` block at the top of `index.html` (around line 13-358), append before `</style>`:

```css
.fc-tab {
  background: transparent;
  border: 1px solid transparent;
  color: var(--muted);
  padding: 7px 16px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  font-family: 'Inter', sans-serif;
}
.fc-tab:hover { color: var(--text); }
.fc-tab-active {
  background: var(--card);
  color: var(--text);
  border-color: var(--border);
  border-bottom-color: var(--card);
  margin-bottom: -1px;
}
```

- [ ] **Step 4: Add the tab-switch function via a new script tag**

Add a `<script src="js/foodcost-tabs.js"></script>` tag just before the closing `</body>` (after any existing module scripts).

Create `js/foodcost-tabs.js`:

```javascript
// Tab switcher for Food Cost section.
// Exposed on window so inline onclick handlers can call it.
window.foodcostShowTab = function (tab) {
  const tabs = ['daily', 'by-item', 'by-supplier']
  for (const t of tabs) {
    const btn = document.querySelector(`.fc-tab[data-tab="${t}"]`)
    const panel = document.getElementById(`fc-tab-${t}`)
    if (btn) btn.classList.toggle('fc-tab-active', t === tab)
    if (panel) panel.style.display = t === tab ? '' : 'none'
  }
  // Notify listeners (e.g. lazy-load daily data)
  document.dispatchEvent(new CustomEvent('foodcost:tab-change', { detail: { tab } }))
}
```

- [ ] **Step 5: Manual verification in browser**

Start the dev server (or whatever the project uses):

```bash
python3 serve.py  # or open index.html via the existing preview_start
```

Open `http://localhost:3100`. Navigate to Food Cost section. Verify:

- Tab bar appears with "Daily | By Item | By Supplier"
- "Daily" is active by default and panel below it is empty
- Click "By Item" → existing item-level table appears (unchanged from current)
- Click "By Supplier" → empty panel
- Click back to "Daily" → empty again

- [ ] **Step 6: Commit**

```bash
git add index.html js/foodcost-tabs.js
git commit -m "feat(foodcost): add Daily / By Item / By Supplier tab structure"
```

---

## Task 7: Daily tab — hero + 7-day chart + today running

**Files:**
- Create: `js/api.js`
- Create: `js/foodcost-daily.js`
- Modify: `index.html` (add `<script>` tags)

- [ ] **Step 1: Create `js/api.js` with the Supabase client wrapper**

Create `js/api.js`:

```javascript
// Centralized Supabase data access for the v1 feature surfaces.
// Existing inline JS still uses its own client — that's fine; we don't refactor it.
;(function () {
  const SUPABASE_URL = 'https://qexjxndommlfqzngxqym.supabase.co'
  const SUPABASE_ANON_KEY = window.__SUPABASE_ANON_KEY__ // already injected by existing code

  if (!SUPABASE_ANON_KEY) {
    console.warn('Supabase anon key not yet injected — api.js will retry on first call')
  }

  function getClient() {
    if (window.__culinaraSupabase__) return window.__culinaraSupabase__
    if (typeof supabase === 'undefined' || !supabase.createClient) {
      throw new Error('supabase-js not loaded')
    }
    window.__culinaraSupabase__ = supabase.createClient(
      SUPABASE_URL,
      SUPABASE_ANON_KEY || window.__SUPABASE_ANON_KEY__
    )
    return window.__culinaraSupabase__
  }

  async function getCurrentRestaurantId() {
    // Reuses existing global if present (set by restaurant selector)
    if (window.currentRestaurantId) return window.currentRestaurantId
    const sb = getClient()
    const { data: { user } } = await sb.auth.getUser()
    if (!user) throw new Error('not_signed_in')
    const { data, error } = await sb
      .from('user_restaurants')
      .select('restaurant_id')
      .eq('user_id', user.id)
      .limit(1)
      .maybeSingle()
    if (error) throw error
    return data?.restaurant_id ?? null
  }

  // ----- Daily food cost queries -----

  async function fetchDailyFoodCost(restaurantId, lookbackDays = 14) {
    const sb = getClient()
    const since = new Date()
    since.setUTCDate(since.getUTCDate() - lookbackDays)
    const sinceISO = since.toISOString().slice(0, 10)
    const { data, error } = await sb
      .from('daily_food_cost')
      .select('date, food_purchases, revenue, fc_pct, fc_pct_7d')
      .eq('restaurant_id', restaurantId)
      .gte('date', sinceISO)
      .order('date', { ascending: false })
    if (error) throw error
    return data ?? []
  }

  async function fetchClosedDay(restaurantId, date) {
    const sb = getClient()
    const { data, error } = await sb
      .from('fc_daily_close')
      .select('*')
      .eq('restaurant_id', restaurantId)
      .eq('date', date)
      .maybeSingle()
    if (error) throw error
    return data
  }

  async function fetchTodayInvoices(restaurantId) {
    const sb = getClient()
    const today = new Date().toISOString().slice(0, 10)
    const { data, error } = await sb
      .from('invoices')
      .select('id, supplier_name, total_amount, received_at, is_food_cost')
      .eq('restaurant_id', restaurantId)
      .gte('received_at', `${today}T00:00:00Z`)
      .order('received_at', { ascending: false })
    if (error) throw error
    return data ?? []
  }

  async function fetchUnacknowledgedAlert(restaurantId) {
    const sb = getClient()
    const { data, error } = await sb
      .from('fc_daily_close')
      .select('*')
      .eq('restaurant_id', restaurantId)
      .is('acknowledged_at', null)
      .order('date', { ascending: false })
      .limit(1)
      .maybeSingle()
    if (error) throw error
    if (!data) return null
    const variance = data.variance_vs_target ?? 0
    if (Math.abs(variance) <= 3) return null
    return data
  }

  async function acknowledgeAlert(restaurantId, date) {
    const sb = getClient()
    const { error } = await sb
      .from('fc_daily_close')
      .update({ acknowledged_at: new Date().toISOString() })
      .eq('restaurant_id', restaurantId)
      .eq('date', date)
    if (error) throw error
  }

  window.culinaraApi = {
    getClient,
    getCurrentRestaurantId,
    fetchDailyFoodCost,
    fetchClosedDay,
    fetchTodayInvoices,
    fetchUnacknowledgedAlert,
    acknowledgeAlert,
  }
})()
```

- [ ] **Step 2: Create `js/foodcost-daily.js` — render the Daily tab top half**

Create `js/foodcost-daily.js`:

```javascript
// Daily tab content: hero (yesterday) + 7-day rolling chart + today running.
// Render runs once on page load AND whenever foodcost:tab-change fires for "daily".
;(function () {
  const $ = (id) => document.getElementById(id)
  const fmtPct = (v) => (v == null ? '—' : `${Number(v).toFixed(1)}%`)
  const fmtMoney = (v) => `$${Math.round(Number(v ?? 0)).toLocaleString()}`
  const fmtDate = (iso) => {
    if (!iso) return ''
    const d = new Date(iso + 'T00:00:00Z')
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  }

  function colorFor(fcPct, target) {
    if (fcPct == null) return 'var(--muted)'
    const drift = fcPct - target
    if (drift > 3) return '#F05252'
    if (drift > 0) return '#F5A623'
    return '#34C97A'
  }

  function renderHero(panel, yesterday, target) {
    const fc = yesterday?.fc_pct
    const drift = fc != null ? Math.round((fc - target) * 100) / 100 : null
    const dollarsOver = yesterday && drift != null && yesterday.revenue
      ? Math.round((drift / 100) * yesterday.revenue)
      : null
    return `
      <div class="card" style="padding:18px;">
        <div style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">
          Yesterday — ${yesterday ? fmtDate(yesterday.date) : '—'}
        </div>
        <div style="font-size:44px;font-weight:800;letter-spacing:-0.02em;color:${colorFor(fc, target)};margin-top:6px;line-height:1;">
          ${fmtPct(fc)}
        </div>
        <div style="font-size:12px;color:${colorFor(fc, target)};margin-top:8px;">
          ${drift == null ? 'No data' :
            drift > 0 ? `↑ ${drift.toFixed(1)}pp vs target · ${dollarsOver ? '$' + Math.abs(dollarsOver).toLocaleString() + ' over' : ''}` :
            drift < 0 ? `↓ ${Math.abs(drift).toFixed(1)}pp under target` :
            'On target'}
        </div>
        <div style="font-size:11px;color:var(--muted);margin-top:4px;">Closed at 03:00 EDT</div>
      </div>
    `
  }

  function renderSevenDay(panel, rows, target) {
    const last7 = rows.slice(0, 7).reverse()
    const avg = rows.length > 0 ? rows[0].fc_pct_7d : null
    const bars = last7.map((r) => {
      const fc = r.fc_pct
      const h = fc == null ? 0 : Math.min(100, fc)
      return `<div title="${r.date}: ${fmtPct(fc)}" style="flex:1;background:${colorFor(fc, target)};height:${h}%;border-radius:3px;min-height:2px;"></div>`
    }).join('')
    return `
      <div class="card" style="padding:18px;">
        <div style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">
          7-day rolling
        </div>
        <div style="font-size:24px;font-weight:800;letter-spacing:-0.02em;margin-top:6px;color:${colorFor(avg, target)};">
          ${fmtPct(avg)}
        </div>
        <div style="display:flex;gap:5px;align-items:flex-end;height:60px;margin-top:14px;">
          ${bars || '<div style="width:100%;color:var(--muted);font-size:11px;text-align:center;line-height:60px;">No data yet</div>'}
        </div>
      </div>
    `
  }

  function renderTodayRunning(panel, rows, todayInvoices) {
    const today = new Date().toISOString().slice(0, 10)
    const todayRow = rows.find((r) => r.date === today)
    const fc = todayRow?.fc_pct
    const target = 25
    return `
      <div class="card" style="padding:18px;">
        <div style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">
          Today running — ${fmtDate(today)}
        </div>
        <div style="font-size:24px;font-weight:800;letter-spacing:-0.02em;margin-top:6px;color:${colorFor(fc, target)};">
          ${fmtPct(fc)}
        </div>
        <div style="font-size:11px;color:var(--muted);margin-top:8px;">
          ${todayInvoices.length} invoice${todayInvoices.length === 1 ? '' : 's'} in · ${fmtMoney(todayInvoices.reduce((s, i) => s + Number(i.total_amount ?? 0), 0))} purchases · sales pending close
        </div>
        <div style="font-size:11px;color:var(--muted);margin-top:14px;font-style:italic;line-height:1.5;">
          Updates throughout the day. Locks at 03:00 tomorrow.
        </div>
      </div>
    `
  }

  async function renderDailyTab() {
    const panel = $('fc-tab-daily')
    if (!panel) return
    panel.innerHTML = '<div style="padding:30px;color:var(--muted);text-align:center;">Loading…</div>'
    try {
      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      if (!restaurantId) {
        panel.innerHTML = '<div style="padding:30px;color:var(--muted);text-align:center;">No restaurant selected</div>'
        return
      }
      const [rows, todayInvoices] = await Promise.all([
        window.culinaraApi.fetchDailyFoodCost(restaurantId, 14),
        window.culinaraApi.fetchTodayInvoices(restaurantId),
      ])

      // Get target from restaurants row (cached on window if other code already loaded it)
      let target = 25
      const sb = window.culinaraApi.getClient()
      const { data: rest } = await sb
        .from('restaurants')
        .select('fc_target_pct')
        .eq('id', restaurantId)
        .maybeSingle()
      if (rest?.fc_target_pct != null) target = Number(rest.fc_target_pct)

      // Yesterday = most recent row that's NOT today
      const today = new Date().toISOString().slice(0, 10)
      const yesterday = rows.find((r) => r.date < today)

      panel.innerHTML = `
        <div style="display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:12px;">
          ${renderHero(panel, yesterday, target)}
          ${renderSevenDay(panel, rows, target)}
          ${renderTodayRunning(panel, rows, todayInvoices)}
        </div>
        <div id="fc-daily-variance" style="margin-top:12px;"></div>
        <div id="fc-daily-suppliers" style="margin-top:12px;"></div>
      `
    } catch (e) {
      console.error('renderDailyTab failed', e)
      panel.innerHTML = `<div style="padding:30px;color:var(--red);text-align:center;">Failed to load: ${e.message}</div>`
    }
  }

  // Render on initial page load (default tab = daily)
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(renderDailyTab, 600) // wait for auth + restaurant resolution
  })
  // Re-render when user switches back to Daily tab
  document.addEventListener('foodcost:tab-change', (e) => {
    if (e.detail?.tab === 'daily') renderDailyTab()
  })

  // Expose for manual invalidation
  window.renderFoodcostDaily = renderDailyTab
})()
```

- [ ] **Step 3: Add `<script>` tags to `index.html`**

Just before `</body>`, add (after `js/foodcost-tabs.js`):

```html
<script src="js/api.js"></script>
<script src="js/foodcost-daily.js"></script>
```

- [ ] **Step 4: Manual verification (Bottē)**

Reload the page. Sign in as Bottē user. Navigate to Food Cost. Daily tab should show:

- Hero: most recent yesterday's FC% with delta vs 25% target. Color-coded.
- 7-day card: rolling average + bar chart (red/amber/green per day).
- Today running card: 0 invoices in (unless it's already showing some), $0 purchases.

Open browser devtools → Network tab → confirm 2-3 successful requests to `qexjxndommlfqzngxqym.supabase.co/rest/v1/daily_food_cost`, `restaurants`, `invoices`.

If hero shows "No data" — check `select count(*) from daily_food_cost where restaurant_id='botte';` returns rows. If 0, run a manual close for any past date with invoices via Task 5 step 4.

- [ ] **Step 5: Commit**

```bash
git add js/api.js js/foodcost-daily.js index.html
git commit -m "feat(foodcost-daily): hero, 7-day rolling chart, today running"
```

---

## Task 8: Daily tab — variance breakdown + supplier impact + today's invoices

**Files:**
- Modify: `js/foodcost-daily.js` (extend with variance + supplier panels)

- [ ] **Step 1: Add variance and supplier renderers**

Append the following to `js/foodcost-daily.js` BEFORE the IIFE close `})()`:

```javascript
  // ----- Variance breakdown -----

  async function fetchVariance(restaurantId, yesterdayDate) {
    if (!yesterdayDate) return null
    const sb = window.culinaraApi.getClient()
    // Fetch yesterday's closed snapshot (preferred — includes variance_drivers)
    const { data: closed } = await sb
      .from('fc_daily_close')
      .select('variance_drivers, food_purchases, revenue, variance_vs_target')
      .eq('restaurant_id', restaurantId)
      .eq('date', yesterdayDate)
      .maybeSingle()
    return closed
  }

  function renderVariance(closed) {
    const el = document.getElementById('fc-daily-variance')
    if (!el) return
    if (!closed) {
      el.innerHTML = ''
      return
    }
    const drivers = closed.variance_drivers?.top_suppliers ?? []
    const variance = Number(closed.variance_vs_target ?? 0)
    if (Math.abs(variance) < 0.5) {
      el.innerHTML = `
        <div class="card" style="padding:14px;">
          <div style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">Yesterday's variance</div>
          <div style="font-size:13px;color:var(--text);margin-top:8px;">On target — no notable drivers.</div>
        </div>
      `
      return
    }
    el.innerHTML = `
      <div class="card" style="padding:14px;">
        <div style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">
          Why did yesterday ${variance > 0 ? 'miss' : 'beat'} target?
        </div>
        <div style="font-size:13px;font-weight:600;margin:6px 0 10px 0;">Top driver suppliers</div>
        ${drivers.length === 0
          ? '<div style="font-size:11.5px;color:var(--muted);">No supplier-level data available.</div>'
          : drivers.map((d) => `
              <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px;">
                <span>${escapeHtml(d.name)}</span>
                <span style="font-weight:700;color:${variance > 0 ? '#F05252' : '#34C97A'};">$${Math.round(d.total).toLocaleString()}</span>
              </div>
            `).join('')
        }
      </div>
    `
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    )
  }

  // ----- Today's invoices side panel -----

  function renderTodayInvoicesPanel(invoices) {
    const el = document.getElementById('fc-daily-suppliers')
    if (!el) return
    if (invoices.length === 0) {
      el.innerHTML = `
        <div class="card" style="padding:14px;">
          <div style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">Today's invoices</div>
          <div style="font-size:12px;color:var(--muted);margin-top:8px;">None received yet.</div>
        </div>
      `
      return
    }
    const rows = invoices.map((inv) => {
      const time = inv.received_at
        ? new Date(inv.received_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
        : '—'
      const tag = inv.is_food_cost === false
        ? '<span style="font-size:9px;background:rgba(139,146,165,0.15);color:var(--muted);padding:2px 6px;border-radius:3px;margin-left:6px;">non-food</span>'
        : inv.is_food_cost == null
        ? '<span style="font-size:9px;background:rgba(245,166,35,0.15);color:#F5A623;padding:2px 6px;border-radius:3px;margin-left:6px;">unclassified</span>'
        : ''
      return `
        <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border);font-size:12px;">
          <span>${escapeHtml(inv.supplier_name ?? 'Unknown supplier')}${tag}<br><span style="color:var(--muted);font-size:10px;">${time}</span></span>
          <span style="font-weight:700;">$${Math.round(Number(inv.total_amount ?? 0)).toLocaleString()}</span>
        </div>
      `
    }).join('')
    const total = invoices.reduce((s, i) => s + Number(i.total_amount ?? 0), 0)
    el.innerHTML = `
      <div class="card" style="padding:14px;">
        <div style="font-size:11px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">Today's invoices</div>
        <div style="font-size:13px;font-weight:600;margin:6px 0 10px 0;">${invoices.length} received · $${Math.round(total).toLocaleString()} in</div>
        ${rows}
      </div>
    `
  }
```

- [ ] **Step 2: Wire variance + invoices into the renderDailyTab function**

Find the existing `renderDailyTab` function. After the line that sets `panel.innerHTML = ...` (with the 3-card grid), add:

```javascript
      // Populate variance + today's invoices panels (lazy)
      if (yesterday) {
        fetchVariance(restaurantId, yesterday.date).then(renderVariance)
      }
      renderTodayInvoicesPanel(todayInvoices)
```

So the function tail looks like:

```javascript
      panel.innerHTML = `
        <div style="display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:12px;">
          ${renderHero(panel, yesterday, target)}
          ${renderSevenDay(panel, rows, target)}
          ${renderTodayRunning(panel, rows, todayInvoices)}
        </div>
        <div id="fc-daily-variance" style="margin-top:12px;"></div>
        <div id="fc-daily-suppliers" style="margin-top:12px;"></div>
      `
      if (yesterday) {
        fetchVariance(restaurantId, yesterday.date).then(renderVariance)
      }
      renderTodayInvoicesPanel(todayInvoices)
    } catch (e) {
      ...
```

- [ ] **Step 3: Backfill a closed-day row for variance to render**

To see variance with real data, manually close a past Bottē day with multiple suppliers:

```bash
TOKEN=<DAILY_FC_CLOSE_TOKEN>
# Pick any date with multiple invoices, e.g. one of Bottē's recent days
curl -X POST "https://qexjxndommlfqzngxqym.supabase.co/functions/v1/daily-fc-close?token=$TOKEN&date=2026-04-10"
```

```sql
select date, fc_pct, variance_vs_target, variance_drivers
from public.fc_daily_close
where restaurant_id='botte'
order by date desc
limit 3;
-- Expected: at least one row with non-empty variance_drivers JSON
```

- [ ] **Step 4: Manual verification**

Reload Food Cost → Daily tab. Verify:

- Variance card appears below the hero row, listing 1-3 supplier rows with dollar amounts
- Today's invoices card appears below variance — either "None received yet" or a list with timestamps and `non-food` / `unclassified` tags where applicable

- [ ] **Step 5: Commit**

```bash
git add js/foodcost-daily.js
git commit -m "feat(foodcost-daily): variance breakdown + today's invoices panel"
```

---

## Task 9: By Supplier tab

**Files:**
- Create: `js/foodcost-by-supplier.js`
- Modify: `index.html` (add `<script>` tag)

- [ ] **Step 1: Create renderer**

Create `js/foodcost-by-supplier.js`:

```javascript
;(function () {
  const $ = (id) => document.getElementById(id)
  const fmtMoney = (v) => `$${Math.round(Number(v ?? 0)).toLocaleString()}`

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    )
  }

  async function fetchSupplierAggregates(restaurantId, lookbackDays = 30) {
    const sb = window.culinaraApi.getClient()
    const since = new Date()
    since.setUTCDate(since.getUTCDate() - lookbackDays)
    const sinceISO = since.toISOString()
    const { data, error } = await sb
      .from('invoices')
      .select('supplier_id, supplier_name, total_amount, is_food_cost, received_at')
      .eq('restaurant_id', restaurantId)
      .gte('received_at', sinceISO)
    if (error) throw error
    const byKey = new Map()
    for (const inv of data ?? []) {
      const key = inv.supplier_id ?? `name:${inv.supplier_name ?? 'unknown'}`
      const cur = byKey.get(key) ?? {
        supplier_id: inv.supplier_id,
        name: inv.supplier_name ?? 'Unknown',
        total: 0,
        invoice_count: 0,
        is_food_cost: inv.is_food_cost,
      }
      cur.total += Number(inv.total_amount ?? 0)
      cur.invoice_count++
      byKey.set(key, cur)
    }
    return Array.from(byKey.values()).sort((a, b) => b.total - a.total)
  }

  async function renderBySupplierTab() {
    const panel = $('fc-tab-by-supplier')
    if (!panel) return
    panel.innerHTML = '<div style="padding:30px;color:var(--muted);text-align:center;">Loading…</div>'
    try {
      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      if (!restaurantId) {
        panel.innerHTML = '<div style="padding:30px;color:var(--muted);text-align:center;">No restaurant selected</div>'
        return
      }
      const aggs = await fetchSupplierAggregates(restaurantId, 30)
      if (aggs.length === 0) {
        panel.innerHTML = '<div style="padding:30px;color:var(--muted);text-align:center;">No invoices in the last 30 days.</div>'
        return
      }
      const total = aggs.reduce((s, a) => s + a.total, 0)
      const rows = aggs.map((a) => {
        const pct = total > 0 ? Math.round((a.total / total) * 100) : 0
        const tag = a.is_food_cost === false
          ? '<span style="font-size:9px;background:rgba(139,146,165,0.15);color:var(--muted);padding:2px 6px;border-radius:3px;margin-left:6px;">non-food</span>'
          : a.is_food_cost == null
          ? '<span style="font-size:9px;background:rgba(245,166,35,0.15);color:#F5A623;padding:2px 6px;border-radius:3px;margin-left:6px;">unclassified</span>'
          : '<span style="font-size:9px;background:rgba(52,201,122,0.15);color:#34C97A;padding:2px 6px;border-radius:3px;margin-left:6px;">food</span>'
        return `
          <tr style="border-bottom:1px solid var(--border);">
            <td style="padding:10px 8px;font-size:13px;">${escapeHtml(a.name)}${tag}</td>
            <td style="padding:10px 8px;font-size:12px;color:var(--muted);text-align:right;">${a.invoice_count}</td>
            <td style="padding:10px 8px;font-size:13px;font-weight:700;text-align:right;">${fmtMoney(a.total)}</td>
            <td style="padding:10px 8px;font-size:11px;color:var(--muted);text-align:right;">${pct}%</td>
          </tr>
        `
      }).join('')

      panel.innerHTML = `
        <div class="card" style="padding:18px;">
          <div style="display:flex;justify-content:space-between;margin-bottom:16px;align-items:center;">
            <div>
              <div class="section-title" style="font-size:16px;">Suppliers — last 30 days</div>
              <div class="section-sub" style="font-size:12px;color:var(--muted);">${aggs.length} suppliers · ${fmtMoney(total)} total</div>
            </div>
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="border-bottom:1px solid var(--border);">
                <th style="padding:8px;text-align:left;font-size:10px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">Supplier</th>
                <th style="padding:8px;text-align:right;font-size:10px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">Invoices</th>
                <th style="padding:8px;text-align:right;font-size:10px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">Total</th>
                <th style="padding:8px;text-align:right;font-size:10px;color:var(--muted);font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">Share</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `
    } catch (e) {
      console.error('renderBySupplierTab failed', e)
      panel.innerHTML = `<div style="padding:30px;color:var(--red);text-align:center;">Failed to load: ${e.message}</div>`
    }
  }

  document.addEventListener('foodcost:tab-change', (e) => {
    if (e.detail?.tab === 'by-supplier') renderBySupplierTab()
  })
  window.renderFoodcostBySupplier = renderBySupplierTab
})()
```

- [ ] **Step 2: Add script tag to `index.html`**

Just before `</body>`, after `js/foodcost-daily.js`:

```html
<script src="js/foodcost-by-supplier.js"></script>
```

- [ ] **Step 3: Manual verification**

Reload, sign in as Bottē, Food Cost → click "By Supplier" tab. Verify:

- Loading spinner briefly visible, then table appears
- Suppliers sorted by total spend descending
- Each row has supplier name + "food"/"non-food"/"unclassified" tag
- Invoice count, total $, and share % populated
- Bottom of table shows correct total

- [ ] **Step 4: Commit**

```bash
git add js/foodcost-by-supplier.js index.html
git commit -m "feat(foodcost): By Supplier tab — 30-day spend by vendor with classification tags"
```

---

## Task 10: Drift alert banner

**Files:**
- Create: `js/alerts.js`
- Modify: `index.html` (add `<script>` tag and a banner mount point)

- [ ] **Step 1: Add banner mount point in `index.html`**

Locate the top of `<body>` (or whatever element wraps the main content area below the sidebar). Insert a banner mount point right at the top of the main content region:

```html
<div id="culi-alert-mount" style="position:sticky;top:0;z-index:50;"></div>
```

If unclear where this goes, place it as the first child inside `<main>` or whatever element the existing pages render into.

- [ ] **Step 2: Create `js/alerts.js`**

```javascript
;(function () {
  const fmtPct = (v) => (v == null ? '—' : `${Number(v).toFixed(1)}%`)

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    )
  }

  function bannerColors(variance) {
    if (variance > 3) return { bg: 'rgba(240,82,82,0.12)', border: '#F05252', accent: '#F05252', emoji: '🔴' }
    if (variance < -3) return { bg: 'rgba(52,201,122,0.10)', border: '#34C97A', accent: '#34C97A', emoji: '🟢' }
    return { bg: 'rgba(245,166,35,0.10)', border: '#F5A623', accent: '#F5A623', emoji: '🟡' }
  }

  function renderBanner(closed, restaurantId) {
    const mount = document.getElementById('culi-alert-mount')
    if (!mount) return
    if (!closed) {
      mount.innerHTML = ''
      return
    }
    const variance = Number(closed.variance_vs_target ?? 0)
    const target = Number(closed.fc_target_pct ?? 25)
    const c = bannerColors(variance)
    const drivers = closed.variance_drivers?.top_suppliers ?? []
    const topDriver = drivers[0]

    const driverText = topDriver
      ? `Top driver: <strong>${escapeHtml(topDriver.name)}</strong> $${Math.round(topDriver.total).toLocaleString()}.`
      : ''

    mount.innerHTML = `
      <div style="background:${c.bg};border:1px solid ${c.border}55;border-left:4px solid ${c.border};padding:11px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;">
        <div style="font-size:13px;line-height:1.4;color:var(--text);">
          <span style="font-size:14px;margin-right:6px;">${c.emoji}</span>
          <strong style="color:${c.accent};">${closed.date} closed at ${fmtPct(closed.fc_pct)} FC</strong>
          — ${variance > 0 ? `${variance.toFixed(1)}pp over` : `${Math.abs(variance).toFixed(1)}pp under`} the ${target}% target.
          ${driverText}
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;">
          <button onclick="window.culiAlertView('${closed.date}')" style="background:#4F8EF7;color:white;border:none;border-radius:6px;padding:6px 12px;font-size:11.5px;font-weight:600;cursor:pointer;">View</button>
          <button onclick="window.culiAlertAck('${closed.date}', '${restaurantId}')" style="background:transparent;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:6px 12px;font-size:11.5px;font-weight:600;cursor:pointer;">Acknowledge</button>
        </div>
      </div>
    `
  }

  async function loadAndRender() {
    try {
      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      if (!restaurantId) return
      const closed = await window.culinaraApi.fetchUnacknowledgedAlert(restaurantId)
      renderBanner(closed, restaurantId)
    } catch (e) {
      console.error('alerts loadAndRender failed', e)
    }
  }

  window.culiAlertView = function (date) {
    if (typeof window.navigate === 'function') window.navigate('profitability')
    if (typeof window.foodcostShowTab === 'function') window.foodcostShowTab('daily')
  }

  window.culiAlertAck = async function (date, restaurantId) {
    try {
      await window.culinaraApi.acknowledgeAlert(restaurantId, date)
      const mount = document.getElementById('culi-alert-mount')
      if (mount) mount.innerHTML = ''
    } catch (e) {
      console.error('ack failed', e)
      alert('Failed to acknowledge: ' + e.message)
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadAndRender, 800)
  })
  window.culiAlertReload = loadAndRender
})()
```

- [ ] **Step 3: Add `<script>` tag**

Just before `</body>`:

```html
<script src="js/alerts.js"></script>
```

- [ ] **Step 4: Manual verification — force a drift alert**

Pick a Bottē date with FC% over target. If `fc_daily_close` already has a row from Task 5/8, it might be acknowledged or not. To force one:

```sql
-- Reset a closed row to unacknowledged so the banner appears
update public.fc_daily_close
set acknowledged_at = null
where restaurant_id = 'botte'
  and date = (
    select date from public.fc_daily_close
    where restaurant_id='botte'
    and abs(coalesce(variance_vs_target,0)) > 3
    order by date desc limit 1
  );
```

Reload the page → expect a colored banner (red if variance > 3, amber for borderline, green if under-target). Click "Acknowledge" → banner disappears.

```sql
-- Verify ack persisted
select acknowledged_at from public.fc_daily_close
where restaurant_id='botte' order by date desc limit 1;
-- Expected: not null
```

- [ ] **Step 5: Commit**

```bash
git add index.html js/alerts.js
git commit -m "feat(alerts): drift banner with View/Acknowledge actions, three states (red/amber/green)"
```

---

## Task 11: Supplier classification modal + nav red dot

**Files:**
- Create: `js/suppliers-modal.js`
- Modify: `index.html` (add modal mount point, sidebar red-dot logic, script tag)

- [ ] **Step 1: Add modal + dot mount markup to `index.html`**

Just before `</body>`:

```html
<div id="culi-supplier-modal-mount"></div>
```

For the sidebar nav red-dot: locate the existing nav item for "Suppliers" (search for "Suppliers" or `data-i18n="nav_suppliers"` / similar). Add `id="nav-suppliers"` to that nav item if not already present.

- [ ] **Step 2: Create `js/suppliers-modal.js`**

```javascript
;(function () {
  const $ = (id) => document.getElementById(id)

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    )
  }

  function fmtMoney(v) { return `$${Math.round(Number(v ?? 0)).toLocaleString()}` }

  async function fetchUnclassified(restaurantId) {
    const sb = window.culinaraApi.getClient()
    const { data, error } = await sb
      .from('suppliers')
      .select('id, name, address')
      .eq('restaurant_id', restaurantId)
      .is('default_food_cost', null)
      .order('created_at', { ascending: false })
    if (error) throw error
    return data ?? []
  }

  async function fetchLatestInvoice(supplierId, restaurantId) {
    const sb = window.culinaraApi.getClient()
    const { data } = await sb
      .from('invoices')
      .select('invoice_number, invoice_date, line_items, total_amount, currency')
      .eq('supplier_id', supplierId)
      .eq('restaurant_id', restaurantId)
      .order('received_at', { ascending: false })
      .limit(1)
      .maybeSingle()
    return data
  }

  async function refreshDot() {
    try {
      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      if (!restaurantId) return
      const list = await fetchUnclassified(restaurantId)
      const navEl = document.getElementById('nav-suppliers')
      if (!navEl) return
      let dot = navEl.querySelector('.culi-nav-dot')
      if (list.length > 0) {
        if (!dot) {
          dot = document.createElement('span')
          dot.className = 'culi-nav-dot'
          dot.style.cssText = 'display:inline-block;width:7px;height:7px;border-radius:50%;background:#F05252;margin-left:6px;vertical-align:middle;'
          navEl.appendChild(dot)
        }
        dot.title = `${list.length} unclassified supplier${list.length === 1 ? '' : 's'}`
        // Also click-to-classify
        navEl.style.cursor = 'pointer'
        navEl.onclick = () => openModal(list[0], restaurantId)
      } else if (dot) {
        dot.remove()
      }
    } catch (e) {
      console.error('refreshDot failed', e)
    }
  }

  async function openModal(supplier, restaurantId) {
    const mount = $('culi-supplier-modal-mount')
    if (!mount) return
    const inv = await fetchLatestInvoice(supplier.id, restaurantId)
    const lines = (inv?.line_items ?? []).slice(0, 4).map((li) =>
      `<div>• ${escapeHtml(li.description ?? li.name ?? 'item')} — ${fmtMoney(li.total ?? li.amount)}</div>`
    ).join('')

    mount.innerHTML = `
      <div style="position:fixed;inset:0;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;z-index:1000;" onclick="if(event.target===this) window.culiCloseSupplierModal()">
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:22px;width:480px;max-width:92vw;color:var(--text);font-family:'Inter',sans-serif;">
          <div style="font-size:16px;font-weight:700;">New supplier detected</div>
          <div style="font-size:12px;color:var(--muted);margin:6px 0 16px 0;line-height:1.5;">First time we've seen an invoice from this vendor. Tag them once and we'll classify all future invoices automatically.</div>

          <div style="background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:14px;">
            <div style="font-size:14px;font-weight:700;">${escapeHtml(supplier.name)}</div>
            ${supplier.address ? `<div style="font-size:11px;color:var(--muted);margin-top:2px;">${escapeHtml(supplier.address)}</div>` : ''}
          </div>

          ${inv ? `
            <div style="background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:14px;">
              <div style="font-size:9.5px;font-weight:700;color:var(--muted);letter-spacing:0.06em;text-transform:uppercase;">Latest invoice — ${escapeHtml(inv.invoice_number ?? '—')} · ${escapeHtml(inv.invoice_date ?? '—')}</div>
              <div style="font-size:11.5px;color:var(--muted);margin-top:6px;line-height:1.5;">
                ${lines || '<em>No line items extracted.</em>'}
                <strong style="color:var(--text);display:block;margin-top:4px;">Total: ${fmtMoney(inv.total_amount)} ${inv.currency ?? ''}</strong>
              </div>
            </div>
          ` : ''}

          <div style="font-size:13px;font-weight:600;margin-bottom:10px;">Are these invoices food cost?</div>

          <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button onclick="window.culiCloseSupplierModal()" style="background:transparent;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:7px 14px;font-size:11.5px;font-weight:600;cursor:pointer;">Skip for now</button>
            <button onclick="window.culiSupplierClassify('${supplier.id}', false)" style="background:#F05252;color:white;border:none;border-radius:6px;padding:7px 14px;font-size:11.5px;font-weight:600;cursor:pointer;">No — non-food</button>
            <button onclick="window.culiSupplierClassify('${supplier.id}', true)" style="background:#34C97A;color:#171B26;border:none;border-radius:6px;padding:7px 14px;font-size:11.5px;font-weight:600;cursor:pointer;">Yes — food</button>
          </div>
        </div>
      </div>
    `
  }

  window.culiCloseSupplierModal = function () {
    const mount = $('culi-supplier-modal-mount')
    if (mount) mount.innerHTML = ''
  }

  window.culiSupplierClassify = async function (supplierId, isFood) {
    try {
      const sb = window.culinaraApi.getClient()
      const { error } = await sb
        .from('suppliers')
        .update({ default_food_cost: isFood })
        .eq('id', supplierId)
      if (error) throw error
      window.culiCloseSupplierModal()
      await refreshDot()
      // Re-render Daily tab + alerts since FC% may now have changed
      if (typeof window.renderFoodcostDaily === 'function') window.renderFoodcostDaily()
      if (typeof window.culiAlertReload === 'function') window.culiAlertReload()
    } catch (e) {
      console.error('classify failed', e)
      alert('Failed to classify: ' + e.message)
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(refreshDot, 1000)
  })
  // Periodic refresh — picks up newly created suppliers
  setInterval(refreshDot, 60_000)

  window.culiSuppliersRefreshDot = refreshDot
})()
```

- [ ] **Step 3: Add `<script>` tag**

Just before `</body>`:

```html
<script src="js/suppliers-modal.js"></script>
```

- [ ] **Step 4: Manual verification — force an unclassified supplier**

Insert a fake unclassified supplier for Bottē:

```sql
insert into public.suppliers (id, restaurant_id, name, address, default_food_cost)
values (gen_random_uuid(), 'botte', 'Test Flower Co', '123 Test St', null)
returning id;
```

Reload the page. Verify:
- Red dot appears on the Suppliers nav item
- Click on Suppliers nav → modal opens with "Test Flower Co" + Skip/No/Yes buttons
- Click "No — non-food" → modal closes, dot disappears

```sql
select default_food_cost from public.suppliers where name = 'Test Flower Co';
-- Expected: false

-- Cleanup
delete from public.suppliers where name = 'Test Flower Co';
```

- [ ] **Step 5: Commit**

```bash
git add index.html js/suppliers-modal.js
git commit -m "feat(suppliers): classification modal + sidebar red-dot for unclassified vendors"
```

---

## Task 12: In-app sales CSV upload UI

**Files:**
- Create: `js/sales-upload.js`
- Modify: `index.html` (add upload UI mount point + script tag)

- [ ] **Step 1: Add upload UI mount in `index.html`**

Inside the Daily tab panel template (`fc-tab-daily`) is rendered dynamically — instead, add a small "Upload sales CSV" button to the sidebar OR to the Settings section. Easiest path: add to Settings section. Search `index.html` for `data-section="settings"` or `Settings`. Add inside the settings card area:

```html
<div class="card" style="padding:18px;margin-top:14px;">
  <div class="section-title" style="font-size:14px;">Sales CSV upload</div>
  <div class="section-sub" style="font-size:11.5px;color:var(--muted);margin-bottom:14px;">Upload a daily sales export from your POS, or email it to your invoice address.</div>
  <div id="culi-sales-upload-mount"></div>
</div>
```

- [ ] **Step 2: Create `js/sales-upload.js`**

```javascript
;(function () {
  const $ = (id) => document.getElementById(id)

  function render() {
    const mount = $('culi-sales-upload-mount')
    if (!mount) return
    mount.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:10px;">
        <input type="file" id="culi-sales-file" accept=".csv,text/csv" style="font-size:12px;color:var(--muted);" />
        <div style="display:flex;align-items:center;gap:10px;color:var(--muted);font-size:11px;">— or —</div>
        <div style="display:flex;gap:8px;align-items:center;">
          <input type="date" id="culi-sales-date" style="background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:6px;padding:7px 10px;font-size:12px;color:var(--text);" />
          <input type="number" id="culi-sales-rev" placeholder="Revenue ($)" step="0.01" style="background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:6px;padding:7px 10px;font-size:12px;color:var(--text);width:140px;" />
          <button onclick="window.culiSalesManualSave()" style="background:#4F8EF7;color:white;border:none;border-radius:6px;padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer;">Save</button>
        </div>
        <button onclick="window.culiSalesUploadCsv()" style="background:#34C97A;color:#171B26;border:none;border-radius:6px;padding:8px 14px;font-size:12px;font-weight:700;cursor:pointer;align-self:flex-start;">Upload CSV</button>
        <div id="culi-sales-status" style="font-size:11.5px;color:var(--muted);min-height:16px;"></div>
      </div>
    `
    const todayInput = $('culi-sales-date')
    if (todayInput) {
      const yest = new Date()
      yest.setDate(yest.getDate() - 1)
      todayInput.value = yest.toISOString().slice(0, 10)
    }
  }

  function setStatus(msg, color = 'var(--muted)') {
    const s = $('culi-sales-status')
    if (s) {
      s.style.color = color
      s.textContent = msg
    }
  }

  window.culiSalesManualSave = async function () {
    const date = $('culi-sales-date')?.value
    const rev = parseFloat($('culi-sales-rev')?.value ?? '')
    if (!date || isNaN(rev)) {
      setStatus('Date and revenue required.', '#F05252')
      return
    }
    try {
      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      const sb = window.culinaraApi.getClient()
      const { error } = await sb
        .from('sales_daily')
        .upsert(
          {
            restaurant_id: restaurantId,
            date,
            revenue_total: rev,
            source: 'manual',
            updated_at: new Date().toISOString(),
          },
          { onConflict: 'restaurant_id,date' }
        )
      if (error) throw error
      setStatus(`Saved $${rev.toLocaleString()} for ${date}.`, '#34C97A')
      if (typeof window.renderFoodcostDaily === 'function') window.renderFoodcostDaily()
    } catch (e) {
      console.error(e)
      setStatus('Save failed: ' + e.message, '#F05252')
    }
  }

  window.culiSalesUploadCsv = async function () {
    const f = $('culi-sales-file')?.files?.[0]
    if (!f) {
      setStatus('Pick a CSV file first.', '#F05252')
      return
    }
    setStatus('Uploading…')
    try {
      const text = await f.text()
      // Reuse the parser that the edge fn uses, but we don't have it bundled in browser.
      // Simplest path: POST raw text to a small RPC or to the edge fn directly with auth.
      // For v1 in-app upload we send to process-sales-csv but with an inline payload pattern.
      // Easier: parse client-side with a minimal duplicate parser, then upsert via PostgREST.
      const parsed = parseCsvClient(text)
      if (parsed.error) throw new Error(parsed.error)
      if (parsed.rows.length === 0) throw new Error('No recognizable rows in CSV.')

      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      const sb = window.culinaraApi.getClient()
      const payload = parsed.rows.map((r) => ({
        restaurant_id: restaurantId,
        date: r.date,
        revenue_total: r.revenue_total,
        cover_count: r.cover_count,
        source: 'csv-upload',
        updated_at: new Date().toISOString(),
      }))
      const { error } = await sb
        .from('sales_daily')
        .upsert(payload, { onConflict: 'restaurant_id,date' })
      if (error) throw error
      setStatus(`Uploaded ${parsed.rows.length} day${parsed.rows.length === 1 ? '' : 's'}.`, '#34C97A')
      if (typeof window.renderFoodcostDaily === 'function') window.renderFoodcostDaily()
    } catch (e) {
      console.error(e)
      setStatus('Upload failed: ' + e.message, '#F05252')
    }
  }

  // Minimal client-side parser (mirrors the Deno parser; if format is unrecognized, user can email-in)
  function parseCsvClient(text) {
    let t = text
    const sep = /^sep=(.)\s*\r?\n/i.exec(t)
    let forced = null
    if (sep) { forced = sep[1]; t = t.slice(sep[0].length) }
    const lines = t.split(/\r?\n/).filter((l) => l.trim() !== '')
    if (lines.length < 2) return { rows: [], error: 'too_few_lines' }
    const detect = (line) => [',', ';', '\t', '|']
      .map((c) => [c, line.split(c).length - 1])
      .sort((a, b) => b[1] - a[1])[0][0]
    const delim = forced ?? detect(lines[0])
    const headers = lines[0].split(delim).map((h) => h.toLowerCase().trim())
    const findIdx = (cands) => headers.findIndex((h) => cands.some((c) => h === c || h.includes(c)))
    const dateIdx = findIdx(['date', 'jour', 'day'])
    const revIdx = findIdx(['revenue', 'sales', 'gross', 'net sales', 'total ttc', 'ventes', 'ca'])
    const coverIdx = findIdx(['covers', 'cover_count', 'guests', 'couverts', 'pax'])
    if (dateIdx === -1 || revIdx === -1) return { rows: [], error: 'no_recognized_columns' }
    const byDate = new Map()
    for (let i = 1; i < lines.length; i++) {
      const cells = lines[i].split(delim)
      const d = (cells[dateIdx] ?? '').trim().replace(/^"|"$/g, '')
      let r = (cells[revIdx] ?? '').trim().replace(/^"|"$/g, '')
      if (r.includes(',') && !r.includes('.')) r = r.replace(/,/g, '.')
      else r = r.replace(/,/g, '')
      const rev = parseFloat(r)
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || isNaN(rev)) continue
      const cov = coverIdx >= 0 ? parseInt(cells[coverIdx] ?? '', 10) : NaN
      const cur = byDate.get(d) ?? { revenue: 0, covers: null }
      cur.revenue += rev
      if (!isNaN(cov)) cur.covers = (cur.covers ?? 0) + cov
      byDate.set(d, cur)
    }
    return {
      rows: Array.from(byDate.entries()).map(([date, v]) => ({
        date,
        revenue_total: Math.round(v.revenue * 100) / 100,
        cover_count: v.covers,
      })),
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(render, 700)
  })
})()
```

- [ ] **Step 3: Add `<script>` tag**

```html
<script src="js/sales-upload.js"></script>
```

- [ ] **Step 4: Manual verification**

Reload, sign in. Navigate to Settings (or wherever the upload UI mounts). Verify:

- File picker + manual date+revenue input visible
- Manual save: pick yesterday's date, enter `1234.56`, click Save → status shows "Saved $1,234.56 for ..."
- Verify in DB:

```sql
select * from public.sales_daily where restaurant_id='botte' and source='manual';
-- Expected: 1+ row
```

- Test CSV upload: create a small CSV file `Date,Revenue\n2026-04-25,500\n2026-04-26,750`, pick it, click Upload CSV → status shows "Uploaded 2 days."

```sql
delete from public.sales_daily where source = 'manual' and revenue_total = 1234.56;
delete from public.sales_daily where source = 'csv-upload' and revenue_total in (500, 750);
```

- [ ] **Step 5: Commit**

```bash
git add index.html js/sales-upload.js
git commit -m "feat(sales): in-app CSV upload + manual revenue entry, mirror parser of process-sales-csv"
```

---

## Task 13: Feature flags — sidebar gating for lean tier

**Files:**
- Create: `js/feature-flags.js`
- Modify: `index.html` (add `data-tier` attributes to nav items + script tag)

- [ ] **Step 1: Annotate sidebar nav items in `index.html`**

Find each nav item in the sidebar. Add a `data-tier` attribute marking which tier sees it:

- `data-tier="lean"` for: Dashboard, Food Cost, Invoices, Suppliers, Settings (always visible)
- `data-tier="full"` for: Recipes, Order Guide, Prep Board, Yield, Insights, Reports, Social, Staff (only visible to full-tier customers)

Example (existing markup on line 488):
```html
<div class="nav-item" onclick="navigate('profitability')"><span class="nav-icon">◎</span><span data-i18n="nav_foodcost">Food Cost</span></div>
```

Becomes:
```html
<div class="nav-item" data-tier="lean" onclick="navigate('profitability')"><span class="nav-icon">◎</span><span data-i18n="nav_foodcost">Food Cost</span></div>
```

For each `nav-item`, decide based on the section name: lean tier sees only the v1 surfaces.

- [ ] **Step 2: Create `js/feature-flags.js`**

```javascript
;(function () {
  async function applyFlags() {
    try {
      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      if (!restaurantId) return
      const sb = window.culinaraApi.getClient()
      const { data: rest } = await sb
        .from('restaurants')
        .select('feature_flags')
        .eq('id', restaurantId)
        .maybeSingle()
      const tier = rest?.feature_flags?.tier ?? 'full'
      // 'full' tier sees everything. 'lean' tier hides full-only items.
      document.querySelectorAll('[data-tier]').forEach((el) => {
        const itemTier = el.getAttribute('data-tier')
        // Show items marked 'lean' to all tiers; show items marked 'full' only to full
        const visible = itemTier === 'lean' || tier === 'full'
        el.style.display = visible ? '' : 'none'
      })
    } catch (e) {
      console.error('applyFlags failed', e)
    }
  }
  document.addEventListener('DOMContentLoaded', () => setTimeout(applyFlags, 500))
  window.culiApplyFeatureFlags = applyFlags
})()
```

- [ ] **Step 3: Add `<script>` tag**

```html
<script src="js/feature-flags.js"></script>
```

- [ ] **Step 4: Manual verification with a synthetic lean restaurant**

Bottē + Arthur's are `full` tier. To test lean rendering, temporarily flip Bottē:

```sql
update public.restaurants
set feature_flags = '{"tier":"lean"}'::jsonb
where id = 'botte';
```

Reload the app as a Bottē user. Sidebar should now only show: Dashboard, Food Cost, Invoices, Suppliers, Settings. Other items hidden.

Restore Bottē:

```sql
update public.restaurants
set feature_flags = '{"tier":"full"}'::jsonb
where id = 'botte';
```

Reload — full sidebar back.

- [ ] **Step 5: Commit**

```bash
git add index.html js/feature-flags.js
git commit -m "feat: feature_flags-based sidebar gating (lean tier shows v1 surfaces only)"
```

---

## Task 14: Lean signup wizard

**Files:**
- Create: `js/onboarding-wizard.js`
- Modify: `index.html` (add wizard mount point + script tag, hook into existing signup flow)

- [ ] **Step 1: Locate the existing signup flow in `index.html`**

```bash
grep -n 'signup\|signUp\|sign_up\|Create account\|self-serve' /Users/thomasgevas/Desktop/culinara/index.html | head -10
```

The existing self-serve signup was added in commit `1e522e5`. Note where the post-signup redirect happens.

- [ ] **Step 2: Add wizard mount point in `index.html`**

```html
<div id="culi-wizard-mount"></div>
```

- [ ] **Step 3: Create `js/onboarding-wizard.js`**

```javascript
;(function () {
  const $ = (id) => document.getElementById(id)

  let state = {
    step: 1,
    restaurantId: null,
    fcTarget: 25,
    yesterdayRevenue: null,
    yesterdayDate: null,
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    )
  }

  async function shouldShowWizard() {
    try {
      const restaurantId = await window.culinaraApi.getCurrentRestaurantId()
      if (!restaurantId) return false
      const sb = window.culinaraApi.getClient()
      const { data: rest } = await sb
        .from('restaurants')
        .select('id, feature_flags, fc_target_pct')
        .eq('id', restaurantId)
        .maybeSingle()
      if (!rest) return false
      const tier = rest.feature_flags?.tier ?? 'full'
      const wizardDone = rest.feature_flags?.wizard_done === true
      // Show only for lean tier and only if wizard hasn't been completed
      return tier === 'lean' && !wizardDone
    } catch {
      return false
    }
  }

  function render() {
    const mount = $('culi-wizard-mount')
    if (!mount) return
    const yest = new Date(); yest.setDate(yest.getDate() - 1)
    state.yesterdayDate = yest.toISOString().slice(0, 10)

    const stepContent = state.step === 1 ? renderStep1()
      : state.step === 2 ? renderStep2()
      : renderStep3()

    mount.innerHTML = `
      <div style="position:fixed;inset:0;background:rgba(23,27,38,0.92);z-index:2000;display:flex;align-items:center;justify-content:center;font-family:'Inter',sans-serif;">
        <div style="background:var(--card);border:1px solid var(--border);border-radius:14px;padding:30px;width:480px;max-width:92vw;color:var(--text);">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <div style="background:#4F8EF7;color:white;font-size:10px;font-weight:700;padding:2px 9px;border-radius:12px;letter-spacing:0.04em;">Step ${state.step} of 3</div>
            <div style="font-size:11px;color:var(--muted);">CulinaraOS setup</div>
          </div>
          ${stepContent}
        </div>
      </div>
    `
  }

  function renderStep1() {
    return `
      <div style="font-size:18px;font-weight:700;margin:6px 0 4px 0;">Set your food cost target</div>
      <div style="font-size:12px;color:var(--muted);margin-bottom:18px;line-height:1.5;">Industry benchmark is 25-32%. You can change it later in Settings.</div>
      <input id="culi-wiz-target" type="number" min="10" max="60" step="0.5" value="${state.fcTarget}"
        style="background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:6px;padding:14px;font-size:22px;font-weight:700;text-align:center;color:var(--text);width:100%;box-sizing:border-box;font-family:inherit;" />
      <div style="display:flex;justify-content:space-between;margin-top:18px;">
        <button onclick="window.culiWizSkipFinish()" style="background:transparent;border:1px solid var(--border);color:var(--text);padding:8px 16px;font-size:12px;font-weight:600;border-radius:6px;cursor:pointer;">Skip wizard</button>
        <button onclick="window.culiWizNext1()" style="background:#4F8EF7;color:white;border:none;padding:8px 16px;font-size:12px;font-weight:600;border-radius:6px;cursor:pointer;">Continue →</button>
      </div>
    `
  }

  function renderStep2() {
    const inbox = `${state.restaurantId}@invoices.culinaraos.com`
    return `
      <div style="font-size:18px;font-weight:700;margin:6px 0 4px 0;">Forward your invoices to:</div>
      <div style="font-size:12px;color:var(--muted);margin-bottom:14px;line-height:1.5;">Tell suppliers to CC this address — or forward existing invoices manually. We auto-extract everything.</div>
      <div style="background:rgba(79,142,247,0.12);border:1px dashed #4F8EF7;border-radius:8px;padding:14px;text-align:center;font-size:14px;font-weight:700;color:#4F8EF7;font-family:'Space Grotesk',monospace;letter-spacing:-0.01em;">
        ${escapeHtml(inbox)}
      </div>
      <button onclick="navigator.clipboard.writeText('${inbox}'); event.target.textContent='✓ Copied';"
        style="margin-top:8px;width:100%;background:transparent;border:1px solid var(--border);color:var(--text);padding:7px;font-size:11px;font-weight:600;border-radius:6px;cursor:pointer;font-family:inherit;">📋 Copy address</button>
      <div style="font-size:11px;color:var(--muted);margin-top:14px;line-height:1.5;">You can also forward sales CSV exports from your POS to the same address.</div>
      <div style="display:flex;justify-content:space-between;margin-top:18px;">
        <button onclick="window.culiWizBack()" style="background:transparent;border:1px solid var(--border);color:var(--text);padding:8px 16px;font-size:12px;font-weight:600;border-radius:6px;cursor:pointer;">← Back</button>
        <button onclick="window.culiWizNext2()" style="background:#4F8EF7;color:white;border:none;padding:8px 16px;font-size:12px;font-weight:600;border-radius:6px;cursor:pointer;">Continue →</button>
      </div>
    `
  }

  function renderStep3() {
    return `
      <div style="font-size:18px;font-weight:700;margin:6px 0 4px 0;">Add yesterday's sales</div>
      <div style="font-size:12px;color:var(--muted);margin-bottom:14px;line-height:1.5;">Just type yesterday's revenue to see your first food cost number. CSV upload is available later in Settings.</div>
      <div style="display:flex;gap:8px;align-items:center;">
        <span style="font-size:13px;color:var(--muted);">${state.yesterdayDate}</span>
        <input id="culi-wiz-rev" type="number" step="0.01" placeholder="Revenue ($)"
          style="background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font-size:14px;color:var(--text);flex:1;font-family:inherit;" />
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:18px;">
        <button onclick="window.culiWizSkipFinish()" style="background:transparent;border:1px solid var(--border);color:var(--text);padding:8px 16px;font-size:12px;font-weight:600;border-radius:6px;cursor:pointer;">Skip & Finish</button>
        <button onclick="window.culiWizFinish()" style="background:#34C97A;color:#171B26;border:none;padding:8px 16px;font-size:12px;font-weight:700;border-radius:6px;cursor:pointer;">Finish →</button>
      </div>
    `
  }

  window.culiWizNext1 = function () {
    const v = parseFloat($('culi-wiz-target')?.value ?? '25')
    state.fcTarget = isNaN(v) ? 25 : v
    state.step = 2
    render()
  }

  window.culiWizNext2 = function () {
    state.step = 3
    render()
  }

  window.culiWizBack = function () {
    state.step = Math.max(1, state.step - 1)
    render()
  }

  window.culiWizSkipFinish = async function () {
    await persist(false)
    closeWizard()
  }

  window.culiWizFinish = async function () {
    const rev = parseFloat($('culi-wiz-rev')?.value ?? '')
    if (!isNaN(rev)) state.yesterdayRevenue = rev
    await persist(true)
    closeWizard()
  }

  async function persist(includeRevenue) {
    try {
      const sb = window.culinaraApi.getClient()
      // 1. Update restaurant target + flag
      const { data: cur } = await sb
        .from('restaurants')
        .select('feature_flags')
        .eq('id', state.restaurantId)
        .maybeSingle()
      const newFlags = { ...(cur?.feature_flags ?? {}), wizard_done: true }
      await sb
        .from('restaurants')
        .update({ fc_target_pct: state.fcTarget, feature_flags: newFlags })
        .eq('id', state.restaurantId)

      // 2. Optional sales row
      if (includeRevenue && state.yesterdayRevenue != null) {
        await sb.from('sales_daily').upsert(
          {
            restaurant_id: state.restaurantId,
            date: state.yesterdayDate,
            revenue_total: state.yesterdayRevenue,
            source: 'manual',
            updated_at: new Date().toISOString(),
          },
          { onConflict: 'restaurant_id,date' }
        )
      }
    } catch (e) {
      console.error('wizard persist failed', e)
    }
  }

  function closeWizard() {
    const mount = $('culi-wizard-mount')
    if (mount) mount.innerHTML = ''
    if (typeof window.renderFoodcostDaily === 'function') window.renderFoodcostDaily()
  }

  async function maybeShow() {
    const show = await shouldShowWizard()
    if (!show) return
    state.restaurantId = await window.culinaraApi.getCurrentRestaurantId()
    render()
  }

  document.addEventListener('DOMContentLoaded', () => setTimeout(maybeShow, 1200))
  window.culiWizardShow = maybeShow
})()
```

- [ ] **Step 4: Add `<script>` tag**

```html
<script src="js/onboarding-wizard.js"></script>
```

- [ ] **Step 5: Add lean-tier provisioning at signup time**

Find the existing signup handler. Where it inserts a new restaurant row (or right after), set the lean flag:

```javascript
// After successfully creating a new restaurant via signup:
await sb.from('restaurants').update({
  feature_flags: { tier: 'lean', wizard_done: false }
}).eq('id', newRestaurantId)
```

(If the existing signup creates the row with default `{"tier":"full"}` from the column default, this update flips new signups to lean while leaving Bottē + Arthur's as full.)

- [ ] **Step 6: Manual verification**

Create a temporary lean test restaurant:

```sql
insert into public.restaurants (id, name, feature_flags, fc_target_pct)
values ('wiztest', 'Wizard Test', '{"tier":"lean","wizard_done":false}'::jsonb, 25);

-- Map yourself to it
insert into public.user_restaurants (user_id, restaurant_id)
values ((select id from auth.users where email='gevasjr@gmail.com' limit 1), 'wiztest');
```

Sign in, switch to "Wizard Test" restaurant. Wizard modal should appear. Walk through:
- Step 1: enter `28`, click Continue
- Step 2: see `wiztest@invoices.culinaraos.com`, click Continue
- Step 3: enter `1500`, click Finish

Verify state persisted:

```sql
select fc_target_pct, feature_flags from public.restaurants where id='wiztest';
-- Expected: 28, {"tier":"lean","wizard_done":true}

select * from public.sales_daily where restaurant_id='wiztest';
-- Expected: 1 row with yesterday's date, revenue_total=1500

-- Cleanup
delete from public.sales_daily where restaurant_id='wiztest';
delete from public.user_restaurants where restaurant_id='wiztest';
delete from public.restaurants where id='wiztest';
```

- [ ] **Step 7: Commit**

```bash
git add index.html js/onboarding-wizard.js
git commit -m "feat: lean 3-step signup wizard, sets fc_target_pct + first sales row"
```

---

## Task 15: End-to-end smoke test on Arthur's

**Files:** none modified — this task verifies the full v1 flow works for Arthur's data.

- [ ] **Step 1: Confirm Arthur's is on `full` tier and has the new schema applied**

```sql
select id, feature_flags, fc_target_pct from public.restaurants where id='arthurs';
-- Expected: feature_flags has tier=full, fc_target_pct populated
```

- [ ] **Step 2: Forward a real invoice email to `arthurs@invoices.culinaraos.com`**

Pick any recent invoice PDF you have. Email it from any address to the inbox. Within 30s, verify:

```sql
select id, supplier_name, total_amount, is_food_cost, status
from public.invoices
where restaurant_id='arthurs'
order by received_at desc limit 5;
-- Expected: most recent row with status='extracted', is_food_cost matches supplier classification
```

If `is_food_cost` is `null` and supplier exists with `default_food_cost = null`, the supplier is unclassified — that's correct. If supplier doesn't exist yet, the trigger pattern (Task 1, trigger 5a) should still leave `is_food_cost` null.

- [ ] **Step 3: Forward a sales CSV to the same inbox**

Create `arthurs-sales-test.csv`:
```
Date,Revenue
2026-04-26,2400.50
```

Email it as an attachment to `arthurs@invoices.culinaraos.com`. Within 30s:

```sql
select * from public.sales_daily where restaurant_id='arthurs' order by date desc limit 3;
-- Expected: row with date 2026-04-26, revenue_total 2400.50, source='csv-email'
```

- [ ] **Step 4: Open the app as Arthur's and verify Daily tab**

Sign in. Navigate to Food Cost. Daily tab should show:
- Hero with Arthur's most recent yesterday FC% (computed from invoices + sales we just landed)
- 7-day chart
- Today running

If "Yesterday" is the email-sent CSV date (2026-04-26) and the food invoice was classified, the FC% should be a reasonable number. If everything is `—`, check:
- Invoice has `is_food_cost = true` (run supplier classification modal if needed)
- `daily_food_cost` view returns rows for `arthurs`

- [ ] **Step 5: Trigger a manual close + verify alert flow**

```bash
TOKEN=<DAILY_FC_CLOSE_TOKEN>
curl -X POST "https://qexjxndommlfqzngxqym.supabase.co/functions/v1/daily-fc-close?token=$TOKEN&date=2026-04-26"
```

```sql
-- Force unacknowledged so banner appears
update public.fc_daily_close
set acknowledged_at = null
where restaurant_id='arthurs' and date='2026-04-26';
```

Reload app. Banner should appear with Arthur's drift number. Click "View" → routes to Food Cost → Daily. Click "Acknowledge" → banner clears.

- [ ] **Step 6: Verify By Supplier tab**

Click "By Supplier" tab. Table should show all suppliers from Arthur's invoices in the last 30 days, sorted by spend, with classification tags.

- [ ] **Step 7: Cleanup test data + commit final summary**

```sql
delete from public.sales_daily where restaurant_id='arthurs' and date='2026-04-26' and source='csv-email';
-- Optional: delete the test invoice if it shouldn't persist
```

```bash
git commit --allow-empty -m "chore: v1 MVP end-to-end verified on Arthur's data"
```

- [ ] **Step 8: Push to production**

```bash
git push origin main
```

Vercel auto-deploys to www.culinaraos.com within ~90 seconds. Verify by opening the live site.

---

## Self-Review Notes (post-write)

- **Spec coverage check:** Each of the 10 locked decisions in section 4 of the spec has at least one task implementing it.
  - Hybrid food cost (D1) → Tasks 1 (view), 7 (Daily render), 9 (By Supplier render)
  - Multi-location, no teardown (D2) → Tasks 1 (RLS), 13 (feature flags) — Bottē/Arthur's stay full
  - Yesterday + 7-day + today running (D3) → Task 7
  - CSV + email-in (D4) → Tasks 2, 3, 4, 12
  - Tabbed layout (D5) → Tasks 6, 7, 8, 9
  - Per-supplier classification (D6) → Tasks 1 (triggers), 11 (modal)
  - Lean wizard + checklist (D7) → Task 14
  - Single inbox (D8) → Task 2 (attachment-type routing)
  - In-app drift alerts (D9) → Tasks 5 (close fn), 10 (banner)
  - Cleanup pass — explicitly deferred per plan header (new code goes in modules; legacy inline stays)

- **Out-of-spec items not in plan (intentional):** Pricing page, landing-page CTA, marketing copy — deferred to a separate launch task, not blocking v1 product itself.
