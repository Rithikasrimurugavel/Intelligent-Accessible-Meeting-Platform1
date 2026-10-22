-- Run this INSTEAD of supabase_schema.sql if you already have data: it only ADDS the summaries table.
create table if not exists public.meeting_summaries (
  meeting_id   uuid primary key references public.meetings(id) on delete cascade,
  summary      jsonb not null,
  source       text not null default 'conversation' check (source in ('conversation','recording')),
  engine       text,
  generated_by uuid references public.profiles(id) on delete set null,
  generated_at timestamptz default now()
);
alter table public.meeting_summaries enable row level security;
drop policy if exists "app_full_access" on public.meeting_summaries;
create policy "app_full_access" on public.meeting_summaries for all to anon, authenticated using (true) with check (true);
