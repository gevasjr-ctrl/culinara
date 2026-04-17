-- Extend existing invoices table to support email inbound via Postmark.
-- Additive only — does not touch existing columns.

alter table public.invoices
  add column if not exists source            text default 'manual',
  add column if not exists from_email        text,
  add column if not exists from_name         text,
  add column if not exists subject           text,
  add column if not exists message_id        text,
  add column if not exists received_at       timestamptz,
  add column if not exists body_text         text,
  add column if not exists body_html         text,
  add column if not exists attachments       jsonb default '[]'::jsonb,
  add column if not exists total_amount      numeric(12,2),
  add column if not exists currency          text default 'CAD',
  add column if not exists line_items        jsonb,
  add column if not exists extraction_error  text,
  add column if not exists updated_at        timestamptz default now();

-- Dedupe: (restaurant_id, message_id) unique when message_id present
create unique index if not exists invoices_restaurant_message_uidx
  on public.invoices (restaurant_id, message_id)
  where message_id is not null;

create index if not exists invoices_restaurant_received_idx
  on public.invoices (restaurant_id, received_at desc);

create index if not exists invoices_status_idx
  on public.invoices (status);

-- Storage bucket for invoice attachments (private)
insert into storage.buckets (id, name, public)
values ('invoices', 'invoices', false)
on conflict (id) do nothing;

-- Storage RLS: users can read attachments for their restaurants.
-- Folder layout: <restaurant_id>/<invoice_id>/<filename>
-- Note: storage.foldername returns text[], first element is restaurant_id (text).
drop policy if exists "read invoice attachments for own restaurants" on storage.objects;
create policy "read invoice attachments for own restaurants"
  on storage.objects for select
  using (
    bucket_id = 'invoices'
    and (storage.foldername(name))[1] in (
      select restaurant_id
      from public.user_restaurants
      where user_id = auth.uid()
    )
  );
