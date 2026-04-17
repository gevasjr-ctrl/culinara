// Supabase Edge Function: extract-invoice
// Takes an invoice_id, downloads its PDF attachments from storage,
// sends them to Claude for structured extraction, and updates the row.
//
// Invoke: POST { invoice_id: "uuid" }
// Endpoint: https://qexjxndommlfqzngxqym.supabase.co/functions/v1/extract-invoice

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
)

const ANTHROPIC_KEY = Deno.env.get('ANTHROPIC_API_KEY') ?? ''
const ANTHROPIC_MODEL = 'claude-sonnet-4-6' // current best Sonnet

interface LineItem {
  description: string
  quantity: number | null
  unit: string | null
  unit_cost: number | null
  total: number | null
  sku: string | null
}

interface ExtractedInvoice {
  supplier_name: string | null
  invoice_number: string | null
  invoice_date: string | null // YYYY-MM-DD
  currency: string | null
  subtotal: number | null
  tax: number | null
  total_amount: number | null
  line_items: LineItem[]
}

const EXTRACTION_PROMPT = `You are an expert at extracting structured data from restaurant supplier invoices.

Analyze the attached invoice PDF and return ONLY a JSON object matching this schema:

{
  "supplier_name": "string — the supplier/vendor/distributor name",
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "currency": "CAD, USD, EUR, etc. or null",
  "subtotal": number or null,
  "tax": number or null,
  "total_amount": number or null,
  "line_items": [
    {
      "description": "item name/description",
      "quantity": number or null,
      "unit": "kg, lb, case, box, each, L, etc. or null",
      "unit_cost": number or null,
      "total": number or null,
      "sku": "product code/SKU or null"
    }
  ]
}

Rules:
- Numbers must be numbers (not strings). No currency symbols, no commas.
- Dates strictly YYYY-MM-DD.
- If a field is unclear or missing, use null.
- Return ONLY the JSON object. No markdown, no explanation, no code fences.`

async function callClaudeWithPdfs(pdfBase64List: Array<{ name: string; base64: string }>) {
  const content: Array<Record<string, unknown>> = []

  for (const pdf of pdfBase64List) {
    content.push({
      type: 'document',
      source: {
        type: 'base64',
        media_type: 'application/pdf',
        data: pdf.base64,
      },
    })
  }
  content.push({ type: 'text', text: EXTRACTION_PROMPT })

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': ANTHROPIC_KEY,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: ANTHROPIC_MODEL,
      max_tokens: 4096,
      messages: [{ role: 'user', content }],
    }),
  })

  if (!res.ok) {
    const errText = await res.text()
    throw new Error(`Anthropic API ${res.status}: ${errText}`)
  }

  const data = await res.json()
  const text = data?.content?.[0]?.text ?? ''

  // Strip code fences if Claude slipped any
  const cleaned = text.trim().replace(/^```json\s*/i, '').replace(/^```\s*/i, '').replace(/\s*```$/, '')
  try {
    return JSON.parse(cleaned) as ExtractedInvoice
  } catch (e) {
    throw new Error(`Failed to parse Claude JSON: ${cleaned.slice(0, 500)}`)
  }
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary)
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

  // Load invoice
  const { data: invoice, error: loadErr } = await supabase
    .from('invoices')
    .select('id, restaurant_id, attachments, status')
    .eq('id', invoiceId)
    .maybeSingle()

  if (loadErr || !invoice) {
    return new Response(JSON.stringify({ error: 'invoice not found', detail: loadErr?.message }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  const attachments = (invoice.attachments ?? []) as Array<{
    path: string
    name: string
    type: string
  }>

  const pdfs = attachments.filter((a) => a.type === 'application/pdf' || a.name.toLowerCase().endsWith('.pdf'))
  if (pdfs.length === 0) {
    await supabase
      .from('invoices')
      .update({
        status: 'error',
        extraction_error: 'no PDF attachments found',
      })
      .eq('id', invoiceId)
    return new Response(JSON.stringify({ ok: false, reason: 'no_pdfs' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  await supabase.from('invoices').update({ status: 'extracting' }).eq('id', invoiceId)

  // Download PDFs from storage
  const pdfBase64List: Array<{ name: string; base64: string }> = []
  for (const pdf of pdfs) {
    const { data, error } = await supabase.storage.from('invoices').download(pdf.path)
    if (error || !data) {
      console.error('download failed', pdf.path, error)
      continue
    }
    const bytes = new Uint8Array(await data.arrayBuffer())
    pdfBase64List.push({ name: pdf.name, base64: bytesToBase64(bytes) })
  }

  if (pdfBase64List.length === 0) {
    await supabase
      .from('invoices')
      .update({ status: 'error', extraction_error: 'failed to download attachments' })
      .eq('id', invoiceId)
    return new Response(JSON.stringify({ ok: false, reason: 'download_failed' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // Call Claude
  let extracted: ExtractedInvoice
  try {
    extracted = await callClaudeWithPdfs(pdfBase64List)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    console.error('extraction failed', msg)
    await supabase
      .from('invoices')
      .update({ status: 'error', extraction_error: msg.slice(0, 1000) })
      .eq('id', invoiceId)
    return new Response(JSON.stringify({ ok: false, error: 'extraction_failed', detail: msg }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // Update invoice with structured data
  const { error: updErr } = await supabase
    .from('invoices')
    .update({
      status: 'extracted',
      supplier_name: extracted.supplier_name,
      invoice_number: extracted.invoice_number,
      invoice_date: extracted.invoice_date,
      currency: extracted.currency ?? 'CAD',
      total_amount: extracted.total_amount,
      amount: extracted.total_amount, // legacy column
      line_items: extracted.line_items ?? [],
      items_summary: (extracted.line_items ?? [])
        .map((li) => li.description)
        .filter(Boolean)
        .slice(0, 5)
        .join(', '),
      extraction_error: null,
      updated_at: new Date().toISOString(),
    })
    .eq('id', invoiceId)

  if (updErr) {
    return new Response(JSON.stringify({ ok: false, error: 'update_failed', detail: updErr.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  return new Response(
    JSON.stringify({
      ok: true,
      invoice_id: invoiceId,
      supplier: extracted.supplier_name,
      total: extracted.total_amount,
      line_items: extracted.line_items?.length ?? 0,
    }),
    { headers: { 'Content-Type': 'application/json' } }
  )
})
