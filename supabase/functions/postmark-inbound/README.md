# postmark-inbound edge function

Receives inbound emails from Postmark, stores attachments in Supabase Storage,
and creates an `invoices` row (status = `pending_extraction`).

## One-time setup

1. **Apply the migration** (in Supabase SQL Editor or CLI)
   - `supabase/migrations/20260416_invoices.sql`
   - Creates `invoices` table + `invoices` storage bucket + RLS policies.

2. **Generate a webhook secret** (any random string):
   ```bash
   openssl rand -hex 32
   ```

3. **Set edge function secrets** (Supabase Dashboard → Edge Functions → Secrets, or CLI):
   ```
   POSTMARK_WEBHOOK_TOKEN=<the random string from step 2>
   ```
   `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are auto-populated.

## Deploy

```bash
cd /Users/thomasgevas/Desktop/culinara
npx supabase login                # first time only
npx supabase functions deploy postmark-inbound --no-verify-jwt
```

Note: `--no-verify-jwt` because Postmark isn't sending a Supabase JWT —
we auth via `?token=...` query param instead.

## Configure in Postmark

1. Go to **Server → Default Inbound Stream → Settings**
2. Set **Inbound webhook URL** to:
   ```
   https://qexjxndommlfqzngxqym.supabase.co/functions/v1/postmark-inbound?token=<your token>
   ```
3. ✅ Enable **"Include raw email content in JSON payload"**

## Test (without waiting for Postmark approval)

```bash
curl -X POST "https://qexjxndommlfqzngxqym.supabase.co/functions/v1/postmark-inbound?token=YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d @test-payload.json
```

Sample `test-payload.json`:
```json
{
  "FromFull": { "Email": "supplier@example.com", "Name": "Test Supplier" },
  "ToFull": [{ "Email": "botte@invoices.culinaraos.com", "Name": "" }],
  "OriginalRecipient": "botte@invoices.culinaraos.com",
  "Subject": "Invoice #12345",
  "MessageID": "test-001",
  "Date": "2026-04-16T12:00:00Z",
  "TextBody": "See attached invoice.",
  "HtmlBody": "<p>See attached invoice.</p>",
  "Attachments": []
}
```

## Data flow

```
Supplier sends email
  → MX: invoices.culinaraos.com → Postmark
  → Postmark POSTs to edge function
  → Edge function:
      1. verifies ?token
      2. resolves restaurant by slug (botte@... → slug "botte")
      3. inserts invoice row (status=received)
      4. uploads attachments to storage: invoices/<restaurant_id>/<invoice_id>/<file>
      5. updates invoice (status=pending_extraction, attachments=[...])
  → (next step: separate extraction job reads pending_extraction invoices,
     runs AI on PDFs, fills line_items/total_amount/supplier_id)
```

## TODO (not in this function)

- Extraction job: background function that picks up `status=pending_extraction`
  invoices, runs AI on the PDFs, fills structured fields.
- Supplier matching: fuzzy-match `from_email` domain against existing suppliers.
- UI wiring: the Invoices section in index.html should query the `invoices` table
  instead of hardcoded data.
