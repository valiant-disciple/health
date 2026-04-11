-- Wearable connections: stores OAuth tokens + sync state per provider
create table if not exists public.wearable_connections (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  provider        text not null,          -- 'fitbit' | 'apple_health' | 'google_fit'
  status          text not null default 'connected',  -- 'connected' | 'disconnected' | 'error'
  access_token    text,
  refresh_token   text,
  token_expires_at timestamptz,
  scope           text,
  provider_user_id text,
  last_synced_at  timestamptz,
  sync_cursor     text,                   -- provider-specific cursor / last-fetched date
  metadata        jsonb default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (user_id, provider)
);

-- RLS
alter table public.wearable_connections enable row level security;

create policy "Users manage own connections"
  on public.wearable_connections for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Index for quick lookup
create index if not exists wearable_connections_user_provider_idx
  on public.wearable_connections (user_id, provider);

-- Auto-update updated_at
create or replace function public.update_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger wearable_connections_updated_at
  before update on public.wearable_connections
  for each row execute function public.update_updated_at();
