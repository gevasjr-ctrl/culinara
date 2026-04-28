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
  variance_vs_target numeric(5,2),
  variance_drivers jsonb,
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
