// Supabase Edge Function: postmark-inbound
// Receives inbound email from Postmark, saves attachments to storage,
// and queues an invoice row for AI extraction.
//
// Endpoint: https://qexjxndommlfqzngxqym.supabase.co/functions/v1/postmark-inbound
// Auth: ?token=<POSTMARK_WEBHOOK_TOKEN>

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

interface PostmarkAttachment {
  Name: string
  ContentType: string
  Content: string
  ContentLength: number
  ContentID?: string
}

interface PostmarkInbound {
  FromFull?: { Email: string; Name: string }
  ToFull?: Array<{ Email: string; Name: string; MailboxHash?: string }>
  Subject?: string
  MessageID?: string
  Date?: string
  TextBody?: string
  HtmlBody?: string
  Attachments?: PostmarkAttachment[]
  OriginalRecipient?: string
  MailboxHash?: string
}

const EXPECTED_TOKEN = Deno.env.get('POSTMARK_WEBHOOK_TOKEN') ?? ''

const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
)

function normalizeEmail(e: string): string {
  return (e ?? '').trim().toLowerCase()
}

function looksLikeSalesCsv(att: PostmarkAttachment): boolean {
  const name = (att.Name ?? '').toLowerCase()
  const type = (att.ContentType ?? '').toLowerCase()
  if (!name.endsWith('.csv') && !type.includes('csv') && !type.includes('text/plain')) {
    return false
  }
  // Sample headers: strip base64 whitespace, take a chunk that decodes cleanly,
  // then scan only the first few lines (where headers live).
  let headerLine = ''
  try {
    const clean = (att.Content ?? '').replace(/\s+/g, '')
    const chunkLen = Math.min(clean.length, 4000) - (Math.min(clean.length, 4000) % 4)
    const sample = atob(clean.slice(0, chunkLen)).toLowerCase()
    headerLine = sample.split('\n').slice(0, 3).join(' ')
  } catch {
    return false
  }
  // Strong sales-only signals: phrases that appear in POS exports but NOT on
  // typical vendor invoice CSVs. Avoid bare "item"/"product"/"sales" — those
  // collide with invoice line-item headers ("sales tax", "item code", etc.).
  const salesHints = [
    'revenue', 'gross sales', 'net sales',
    'menu item', 'plu', 'modifier',
    'qty sold', 'quantity sold', 'units sold', 'tickets sold',
    'ventes nettes', 'ventes brutes', 'chiffre d',  // "chiffre d'affaires"
  ]
  return salesHints.some((h) => headerLine.includes(h))
}

Deno.serve(async (req) => {
  const url = new URL(req.url)
  const token = url.searchParams.get('token') ?? ''
  if (!EXPECTED_TOKEN || token !== EXPECTED_TOKEN) {
    return new Response('Unauthorized', { status: 401 })
  }
  if (req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 })
  }

  let payload: PostmarkInbound
  try {
    payload = await req.json()
  } catch {
    return new Response('Invalid JSON', { status: 400 })
  }

  const primaryTo = normalizeEmail(
    payload.OriginalRecipient ?? payload.ToFull?.[0]?.Email ?? ''
  )
  if (!primaryTo) {
    return new Response(JSON.stringify({ ok: true, dropped: true, reason: 'no_recipient' }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // 1. Try exact match on restaurants.invoice_email
  let restaurant:
    | { id: string; name: string | null; invoice_email: string | null }
    | null = null

  const { data: r1 } = await supabase
    .from('restaurants')
    .select('id, name, invoice_email')
    .eq('invoice_email', primaryTo)
    .maybeSingle()
  if (r1) restaurant = r1

  // 2. Fallback: match by local-part ("botte@..." -> restaurants.id = "botte")
  if (!restaurant) {
    const slug = primaryTo.split('@')[0]
    const { data: r2 } = await supabase
      .from('restaurants')
      .select('id, name, invoice_email')
      .eq('id', slug)
      .maybeSingle()
    if (r2) restaurant = r2
  }

  if (!restaurant) {
    console.warn(`No restaurant matched for ${primaryTo}`)
    return new Response(
      JSON.stringify({ ok: true, dropped: true, reason: 'unknown_recipient', to: primaryTo }),
      { headers: { 'Content-Type': 'application/json' } }
    )
  }

  // Insert invoice row (pending extraction)
  const { data: invoice, error: invErr } = await supabase
    .from('invoices')
    .insert({
      restaurant_id: restaurant.id,
      source: 'email',
      status: 'received',
      from_email: payload.FromFull?.Email ?? null,
      from_name: payload.FromFull?.Name ?? null,
      subject: payload.Subject ?? null,
      message_id: payload.MessageID ?? null,
      received_at: payload.Date ?? new Date().toISOString(),
      body_text: payload.TextBody ?? null,
      body_html: payload.HtmlBody ?? null,
    })
    .select('id')
    .single()

  if (invErr || !invoice) {
    console.error('invoice insert failed', invErr)
    return new Response(JSON.stringify({ error: 'invoice_insert_failed', detail: invErr?.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // Upload attachments to storage: invoices/<restaurant_id>/<invoice_id>/<filename>
  const attachmentRefs: Array<{ path: string; name: string; type: string; size: number }> = []
  for (const att of payload.Attachments ?? []) {
    try {
      const bytes = Uint8Array.from(atob(att.Content), (c) => c.charCodeAt(0))
      const safeName = att.Name.replace(/[^a-zA-Z0-9._-]/g, '_')
      const path = `${restaurant.id}/${invoice.id}/${safeName}`

      const { error: upErr } = await supabase.storage
        .from('invoices')
        .upload(path, bytes, {
          contentType: att.ContentType,
          upsert: false,
        })

      if (upErr) {
        console.error('attachment upload failed', path, upErr)
        continue
      }
      attachmentRefs.push({
        path,
        name: att.Name,
        type: att.ContentType,
        size: att.ContentLength,
      })
    } catch (e) {
      console.error('attachment decode failed', att.Name, e)
    }
  }

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

  return new Response(
    JSON.stringify({
      ok: true,
      invoice_id: invoice.id,
      restaurant_id: restaurant.id,
      attachments: attachmentRefs.length,
    }),
    { headers: { 'Content-Type': 'application/json' } }
  )
})
