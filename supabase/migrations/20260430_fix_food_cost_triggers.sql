-- v1 MVP: fix food-cost triggers to match real schema
-- The original 20260427 migration referenced invoices.supplier_id which does not exist.
-- This migration rewrites both trigger functions to match suppliers by
-- (restaurant_id, lower(trim(name))) against invoices.supplier_name (text).
-- Idempotent. Safe to re-run.

------------------------------------------------------------
-- 1. Unique index for classification upserts
------------------------------------------------------------
-- Lets the classification UI do INSERT ... ON CONFLICT (restaurant_id, lower(trim(name)))
-- without worrying about race conditions.
create unique index if not exists suppliers_restaurant_name_uniq
  on public.suppliers (restaurant_id, lower(trim(name)));

------------------------------------------------------------
-- 2. Replace trigger 5a (BEFORE INSERT on invoices)
--    Inherit is_food_cost by matching supplier_name to suppliers.name
------------------------------------------------------------
create or replace function public.invoices_inherit_food_cost()
returns trigger
language plpgsql
security definer
as $$
begin
  if new.is_food_cost is null and new.supplier_name is not null and new.restaurant_id is not null then
    select default_food_cost into new.is_food_cost
    from public.suppliers
    where restaurant_id = new.restaurant_id
      and lower(trim(name)) = lower(trim(new.supplier_name))
    limit 1;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_invoices_inherit_food_cost on public.invoices;
create trigger trg_invoices_inherit_food_cost
  before insert on public.invoices
  for each row
  execute function public.invoices_inherit_food_cost();

------------------------------------------------------------
-- 3. Replace trigger 5b (AFTER INSERT OR UPDATE on suppliers)
--    Backfill all matching invoices when classification is set or changed.
--    Fires on INSERT so first-time classification (insert with default_food_cost)
--    cascades to historical invoices.
------------------------------------------------------------
create or replace function public.suppliers_backfill_food_cost()
returns trigger
language plpgsql
security definer
as $$
begin
  if (TG_OP = 'INSERT' and new.default_food_cost is not null)
     or (TG_OP = 'UPDATE' and new.default_food_cost is distinct from old.default_food_cost) then
    update public.invoices
    set is_food_cost = new.default_food_cost
    where restaurant_id = new.restaurant_id
      and lower(trim(supplier_name)) = lower(trim(new.name));
  end if;
  return new;
end;
$$;

drop trigger if exists trg_suppliers_backfill_food_cost on public.suppliers;
create trigger trg_suppliers_backfill_food_cost
  after insert or update of default_food_cost on public.suppliers
  for each row
  execute function public.suppliers_backfill_food_cost();
