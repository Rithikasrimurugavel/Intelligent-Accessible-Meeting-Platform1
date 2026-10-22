-- =====================================================================
-- ACCESSIBLE MEETING APP - clean Supabase schema (run ONCE in SQL Editor)
-- WARNING: drops and recreates the 5 app tables (all data is deleted).
-- =====================================================================
create extension if not exists "pgcrypto";

drop table if exists public.meeting_summaries cascade;
drop table if exists public.messages     cascade;
drop table if exists public.participants cascade;
drop table if exists public.meetings     cascade;
drop table if exists public.profiles     cascade;

create table public.profiles (
  id         uuid primary key default gen_random_uuid(),
  email      text unique not null,
  name       text not null,
  role       text not null check (role in ('manager','normal','blind','deaf','mute')),
  created_at timestamptz default now()
);

create table public.meetings (
  id           uuid primary key default gen_random_uuid(),
  meeting_code varchar(20) unique not null,
  title        text not null,
  host_id      uuid not null references public.profiles(id) on delete cascade,
  status       text not null default 'active' check (status in ('scheduled','active','ended')),
  created_at   timestamptz default now(),
  started_at   timestamptz,
  ended_at     timestamptz
);

create table public.participants (
  id         uuid primary key default gen_random_uuid(),
  meeting_id uuid not null references public.meetings(id) on delete cascade,
  user_id    uuid not null references public.profiles(id) on delete cascade,
  role       text not null check (role in ('manager','normal','blind','deaf','mute')),
  status     text not null default 'active' check (status in ('active','left')),
  joined_at  timestamptz default now(),
  left_at    timestamptz,
  unique (meeting_id, user_id)
);

create table public.messages (
  id               uuid primary key default gen_random_uuid(),
  meeting_id       uuid not null references public.meetings(id) on delete cascade,
  sender_id        uuid references public.profiles(id) on delete set null,   -- NULL = system message
  sender_name      text not null,
  sender_role      text not null check (sender_role in ('manager','normal','blind','deaf','mute','system')),
  input_type       text not null check (input_type in ('voice','text','sign_language','system')),
  text_content     text not null,
  original_content text,
  confidence       numeric(5,4),
  target           text default 'all',
  status           text default 'completed' check (status in ('processing','completed','failed')),
  "timestamp"      timestamptz default now()
);

create table public.meeting_summaries (
  meeting_id   uuid primary key references public.meetings(id) on delete cascade,   -- one summary per meeting
  summary      jsonb not null,            -- {title, summary, action_items[], key_decisions[], topics_discussed[], full_transcript, stats, warnings}
  source       text not null default 'conversation' check (source in ('conversation','recording')),
  engine       text,
  generated_by uuid references public.profiles(id) on delete set null,
  generated_at timestamptz default now()
);

create index idx_meetings_code        on public.meetings(meeting_code);
create index idx_messages_meeting     on public.messages(meeting_id, "timestamp");
create index idx_participants_meeting on public.participants(meeting_id);

-- Row Level Security.
-- This app talks to Supabase with the ANON key and does not use Supabase Auth, so requests run as
-- the `anon` role. Policies must include `anon` (policies "to authenticated" block this app).
-- NOTE: this is open access - fine for a demo/college project. For production, switch to Supabase Auth
-- and restrict policies by auth.uid().
alter table public.profiles     enable row level security;
alter table public.meetings     enable row level security;
alter table public.participants enable row level security;
alter table public.messages     enable row level security;
alter table public.meeting_summaries enable row level security;

create policy "app_full_access" on public.profiles     for all to anon, authenticated using (true) with check (true);
create policy "app_full_access" on public.meetings     for all to anon, authenticated using (true) with check (true);
create policy "app_full_access" on public.participants for all to anon, authenticated using (true) with check (true);
create policy "app_full_access" on public.messages     for all to anon, authenticated using (true) with check (true);
create policy "app_full_access" on public.meeting_summaries for all to anon, authenticated using (true) with check (true);
