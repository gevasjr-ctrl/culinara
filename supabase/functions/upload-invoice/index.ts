// Supabase Edge Function: upload-invoice
// Authenticated manual upload of an invoice PDF by a logged-in user.
// Accepts JSON: { restaurant_id, filename, content_type, base64 }
// Verifies user is linked to that restaurant via user_restaurants, stores the
// file, creates an invoices row (source=upload), fires extract-invoice.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const supabaseUrl = Deno.env.get('SUPABASE_URL')!
const serviceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
const anonKey = Deno.env.get('SUPABASE_ANON_KEY')!

const corsHeaders: HeadersInit = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })
  if (req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405, headers: corsHeaders })
  }

  // 1) Identify the caller from their Supabase JWT
  const authHeader = req.headers.get('authorization') ?? ''
  const token = authHeader.replace(/^Bearer\s+/i, '')
  if (!token) {
    return new Response(JSON.stringify({ error: 'missing_auth' }), {
      status: 401, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  const sbUser = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: `Bearer ${token}` } },
  })
  const { data: userResult, error: authErr } = await sbUser.auth.getUser()
  const user = userResult?.user
  if (authErr || !user) {
    return new Response(JSON.stringify({ error: 'invalid_auth' }), {
      status: 401, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  // 2) Read body
  let body: {
    restaurant_id?: string
    filename?: string
    content_type?: string
    base64?: string
  }
  try {
    body = await req.json()
  } catch {
    return new Response(JSON.stringify({ error: 'invalid_json' }), {
      status: 400, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  const { restaurant_id, filename, content_type, base64 } = body
  if (!restaurant_id || !filename || !base64) {
    return new Response(JSON.stringify({ error: 'missing_fields', required: ['restaurant_id','filename','base64'] }), {
      status: 400, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  // 3) Service-role client for DB + storage writes
  const sb = createClient(supabaseUrl, serviceKey)

  // 3a) Verify user belongs to this restaurant
  const { data: membership } = await sb
    .from('user_restaurants')
    .select('restaurant_id')
    .eq('user_id', user.id)
    .eq('restaurant_id', restaurant_id)
    .maybeSingle()

  if (!membership) {
    return new Response(JSON.stringify({ error: 'forbidden', detail: 'user not linked to restaurant' }), {
      status: 403, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  // 4) Insert invoice row first so we have its id for the storage path
  const { data: invoice, error: invErr } = await sb
    .from('invoices')
    .insert({
      restaurant_id,
      source: 'upload',
      status: 'received',
      from_email: user.email ?? null,
      from_name: 'Manual upload',
      subject: `Uploaded: ${filename}`,
      received_at: new Date().toISOString(),
    })
    .select('id')
    .single()

  if (invErr || !invoice) {
    return new Response(JSON.stringify({ error: 'invoice_insert_failed', detail: invErr?.message }), {
      status: 500, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  // 5) Decode + upload the PDF
  let bytes: Uint8Array
  try {
    bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
  } catch (e) {
    await sb.from('invoices').delete().eq('id', invoice.id)
    return new Response(JSON.stringify({ error: 'invalid_base64' }), {
      status: 400, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  const safeName = filename.replace(/[^a-zA-Z0-9._-]/g, '_')
  const path = `${restaurant_id}/${invoice.id}/${safeName}`

  const { error: upErr } = await sb.storage.from('invoices').upload(path, bytes, {
    contentType: content_type || 'application/pdf',
    upsert: false,
  })
  if (upErr) {
    await sb.from('invoices').delete().eq('id', invoice.id)
    return new Response(JSON.stringify({ error: 'upload_failed', detail: upErr.message }), {
      status: 500, headers: { ...corsHeaders, 'content-type': 'application/json' },
    })
  }

  const attachmentRef = {
    path,
    name: filename,
    type: content_type || 'application/pdf',
    size: bytes.byteLength,
  }

  await sb
    .from('invoices')
    .update({ attachments: [attachmentRef], status: 'pending_extraction' })
    .eq('id', invoice.id)

  // 6) Fire-and-forget extraction
  try {
    const extractionPromise = fetch(`${supabaseUrl}/functions/v1/extract-invoice`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${serviceKey}`,
      },
      body: JSON.stringify({ invoice_id: invoice.id }),
    }).catch((e) => console.error('extract-invoice trigger failed', e))
    // @ts-ignore — EdgeRuntime exists on Supabase
    if (typeof EdgeRuntime !== 'undefined' && EdgeRuntime.waitUntil) {
      // @ts-ignore
      EdgeRuntime.waitUntil(extractionPromise)
    }
  } catch (e) {
    console.error('failed to schedule extraction', e)
  }

  return new Response(
    JSON.stringify({ ok: true, invoice_id: invoice.id, restaurant_id, filename }),
    { status: 200, headers: { ...corsHeaders, 'content-type': 'application/json' } }
  )
})
