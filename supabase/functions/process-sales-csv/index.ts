// Supabase Edge Function: process-sales-csv
// Takes an invoice_id whose attachment is a sales-shaped CSV, downloads it
// from storage, parses it, aggregates revenue per date, and upserts into
// public.sales_daily. Updates the originating invoice row with status.
//
// Invoke: POST { invoice_id: "uuid" }
// Endpoint: https://qexjxndommlfqzngxqym.supabase.co/functions/v1/process-sales-csv
//
// MVP scope: requires the CSV to have a per-row date column. Reports without
// a date column (e.g. "Period: Jan 1 – Apr 13" header-only CSVs) are not
// supported here — those should go through the manual upload UI instead.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
)

interface AttachmentRef {
  path: string
  name: string
  type: string
  size?: number
}

interface ParsedCsv {
  headers: string[]
  rows: Record<string, string>[]
}

function parseCsv(input: string): ParsedCsv {
  let text = input
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
  let lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0)
  if (lines.length < 2) return { headers: [], rows: [] }

  // Excel "sep=;" / "sep=\t" directive
  let forcedDelim: string | null = null
  const sepMatch = lines[0].match(/^sep=(.)/i)
  if (sepMatch) {
    forcedDelim = sepMatch[1]
    lines = lines.slice(1)
  }

  // Auto-detect delimiter (tab > semicolon > comma). QC/French POS exports
  // often use ';' because ',' is the decimal separator.
  const first = lines[0]
  const tab = (first.match(/\t/g) ?? []).length
  const semi = (first.match(/;/g) ?? []).length
  const comma = (first.match(/,/g) ?? []).length
  let delim = forcedDelim ?? ','
  if (!forcedDelim) {
    if (tab > semi && tab > comma) delim = '\t'
    else if (semi > comma) delim = ';'
  }

  const splitLine = (line: string): string[] => {
    const out: string[] = []
    let cur = ''
    let inQuote = false
    for (let i = 0; i < line.length; i++) {
      const c = line[i]
      if (c === '"') {
        if (inQuote && line[i + 1] === '"') {
          cur += '"'
          i++
        } else {
          inQuote = !inQuote
        }
      } else if (c === delim && !inQuote) {
        out.push(cur)
        cur = ''
      } else {
        cur += c
      }
    }
    out.push(cur)
    return out.map((v) => v.trim().replace(/^"|"$/g, ''))
  }

  const headers = splitLine(lines[0])
  const rows: Record<string, string>[] = []
  for (let i = 1; i < lines.length; i++) {
    const vals = splitLine(lines[i])
    if (vals.length < 2) continue
    const obj: Record<string, string> = {}
    headers.forEach((h, idx) => {
      obj[h] = vals[idx] ?? ''
    })
    rows.push(obj)
  }
  return { headers, rows }
}

function findHeader(headers: string[], patterns: RegExp[]): string | null {
  for (const p of patterns) {
    const m = headers.find((h) => p.test(h))
    if (m) return m
  }
  return null
}

// Decide whether ambiguous numeric dates should be parsed MM/DD or DD/MM by
// scanning all values: if any first-segment > 12, must be DD/MM. If any
// second-segment > 12, must be MM/DD. Default to MM/DD (Lightspeed default).
function detectDateOrder(samples: string[]): 'mdy' | 'dmy' {
  let mdyImpossible = false
  let dmyImpossible = false
  for (const s of samples) {
    const m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})/)
    if (!m) continue
    const a = parseInt(m[1], 10)
    const b = parseInt(m[2], 10)
    if (a > 12) mdyImpossible = true
    if (b > 12) dmyImpossible = true
  }
  if (mdyImpossible && !dmyImpossible) return 'dmy'
  if (dmyImpossible && !mdyImpossible) return 'mdy'
  return 'mdy'
}

function parseDate(raw: string, order: 'mdy' | 'dmy'): string | null {
  const s = raw.trim()
  if (!s) return null
  // ISO YYYY-MM-DD or YYYY/MM/DD
  const iso = s.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})/)
  if (iso) {
    const y = iso[1]
    const m = iso[2].padStart(2, '0')
    const d = iso[3].padStart(2, '0')
    return `${y}-${m}-${d}`
  }
  // MM/DD/YYYY or DD/MM/YYYY (or with dashes)
  const num = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})/)
  if (num) {
    let yy = num[3]
    if (yy.length === 2) yy = (parseInt(yy, 10) >= 70 ? '19' : '20') + yy
    const a = num[1].padStart(2, '0')
    const b = num[2].padStart(2, '0')
    const month = order === 'mdy' ? a : b
    const day = order === 'mdy' ? b : a
    return `${yy}-${month}-${day}`
  }
  return null
}

function parseNumber(raw: string): number {
  if (!raw) return 0
  // Strip currency symbols, spaces. Handle European decimal comma when no
  // dot is present (e.g. "1 234,56" → 1234.56).
  let s = raw.replace(/[$£€\s]/g, '')
  if (s.includes(',') && !s.includes('.')) {
    s = s.replace(/\./g, '').replace(',', '.')
  } else {
    s = s.replace(/,/g, '')
  }
  const n = parseFloat(s)
  return Number.isFinite(n) ? n : 0
}

async function markError(invoiceId: string, message: string) {
  await supabase
    .from('invoices')
    .update({
      status: 'error',
      extraction_error: message.slice(0, 1000),
      updated_at: new Date().toISOString(),
    })
    .eq('id', invoiceId)
}

Deno.serve(async (req) => {
  if (req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 })
  }

  let body: { invoice_id?: string }
  try {
    body = await req.json()
  } catch {
    return new Response('Invalid JSON', { status: 400 })
  }

  const invoiceId = body.invoice_id
  if (!invoiceId) {
    return new Response(JSON.stringify({ error: 'invoice_id required' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  const { data: invoice, error: loadErr } = await supabase
    .from('invoices')
    .select('id, restaurant_id, attachments, status')
    .eq('id', invoiceId)
    .maybeSingle()

  if (loadErr || !invoice) {
    return new Response(
      JSON.stringify({ error: 'invoice not found', detail: loadErr?.message }),
      { status: 404, headers: { 'Content-Type': 'application/json' } }
    )
  }

  const attachments = (invoice.attachments ?? []) as AttachmentRef[]
  const csvAtt = attachments.find(
    (a) =>
      a.name.toLowerCase().endsWith('.csv') ||
      (a.type ?? '').toLowerCase().includes('csv') ||
      (a.type ?? '').toLowerCase().includes('text/plain')
  )
  if (!csvAtt) {
    await markError(invoiceId, 'sales csv: no CSV attachment found on invoice')
    return new Response(JSON.stringify({ ok: false, reason: 'no_csv' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  await supabase
    .from('invoices')
    .update({ status: 'sales_csv_processing' })
    .eq('id', invoiceId)

  // Download CSV from storage
  const { data: blob, error: dlErr } = await supabase.storage
    .from('invoices')
    .download(csvAtt.path)
  if (dlErr || !blob) {
    await markError(invoiceId, `sales csv: download failed — ${dlErr?.message ?? 'unknown'}`)
    return new Response(JSON.stringify({ ok: false, reason: 'download_failed' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  const text = await blob.text()
  const { headers, rows } = parseCsv(text)
  if (headers.length === 0 || rows.length === 0) {
    await markError(invoiceId, 'sales csv: empty or unparseable')
    return new Response(JSON.stringify({ ok: false, reason: 'unparseable' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // Locate the date, revenue, and (optional) cover columns.
  const dateCol = findHeader(headers, [
    /^date$/i,
    /business\s*date/i,
    /transaction\s*date/i,
    /day/i,
    /jour/i,
    /^date\s/i,
  ])
  if (!dateCol) {
    await markError(
      invoiceId,
      `sales csv: no date column found in headers [${headers.slice(0, 8).join(', ')}…]. ` +
        `Reports without a per-row date column aren't supported via email — use the manual upload UI.`
    )
    return new Response(JSON.stringify({ ok: false, reason: 'no_date_column' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // Prefer net sales > gross sales > revenue > generic amount/total fallback.
  const revenueCol =
    findHeader(headers, [/net\s*sales/i, /ventes\s*nettes/i]) ??
    findHeader(headers, [/gross\s*sales/i, /ventes\s*brutes/i]) ??
    findHeader(headers, [/revenue/i, /chiffre\s*d/i]) ??
    findHeader(headers, [/transaction\s*amount/i]) ??
    findHeader(headers, [/^amount$/i, /^total$/i, /montant/i, /^ca\b/i])

  if (!revenueCol) {
    await markError(
      invoiceId,
      `sales csv: no revenue column found in headers [${headers.slice(0, 8).join(', ')}…]`
    )
    return new Response(JSON.stringify({ ok: false, reason: 'no_revenue_column' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  const coverCol = findHeader(headers, [
    /^covers?$/i,
    /guests?/i,
    /customers?/i,
    /tickets?/i,
    /transactions?/i,
    /couverts?/i,
  ])

  // Disambiguate numeric date order across the whole file.
  const dateSamples = rows.map((r) => r[dateCol] ?? '').filter(Boolean)
  const order = detectDateOrder(dateSamples)

  // Aggregate revenue and covers per date.
  const byDate = new Map<string, { revenue: number; covers: number }>()
  let badDates = 0
  for (const r of rows) {
    const d = parseDate(r[dateCol] ?? '', order)
    if (!d) {
      badDates++
      continue
    }
    const rev = parseNumber(r[revenueCol] ?? '')
    const cov = coverCol ? Math.round(parseNumber(r[coverCol] ?? '')) : 0
    const acc = byDate.get(d) ?? { revenue: 0, covers: 0 }
    acc.revenue += rev
    acc.covers += cov
    byDate.set(d, acc)
  }

  if (byDate.size === 0) {
    await markError(
      invoiceId,
      `sales csv: parsed ${rows.length} rows but no usable dates (date column "${dateCol}", order ${order})`
    )
    return new Response(JSON.stringify({ ok: false, reason: 'no_usable_dates' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // Upsert into sales_daily (one row per date).
  const upserts = Array.from(byDate.entries()).map(([date, acc]) => ({
    restaurant_id: invoice.restaurant_id,
    date,
    revenue_total: Math.round(acc.revenue * 100) / 100,
    cover_count: coverCol ? acc.covers : null,
    source: 'csv-email',
    source_file_id: invoice.id,
    updated_at: new Date().toISOString(),
  }))

  const { error: upErr } = await supabase
    .from('sales_daily')
    .upsert(upserts, { onConflict: 'restaurant_id,date' })

  if (upErr) {
    await markError(invoiceId, `sales csv: upsert failed — ${upErr.message}`)
    return new Response(
      JSON.stringify({ ok: false, error: 'upsert_failed', detail: upErr.message }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    )
  }

  await supabase
    .from('invoices')
    .update({
      status: 'sales_csv_processed',
      extraction_error: badDates > 0 ? `${badDates} rows had unparseable dates` : null,
      updated_at: new Date().toISOString(),
    })
    .eq('id', invoiceId)

  return new Response(
    JSON.stringify({
      ok: true,
      invoice_id: invoiceId,
      restaurant_id: invoice.restaurant_id,
      days_written: byDate.size,
      rows_parsed: rows.length,
      bad_dates: badDates,
      date_column: dateCol,
      revenue_column: revenueCol,
      cover_column: coverCol,
      date_order: order,
    }),
    { headers: { 'Content-Type': 'application/json' } }
  )
})
