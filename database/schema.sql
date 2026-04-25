-- ============================================================
-- RAKSHA-FORCE — COMPLETE SUPABASE DATABASE SETUP
-- Paste the full script into Supabase SQL Editor and run once.
--
-- What this script does:
-- 1. Recreates all RAKSHA-FORCE tables cleanly
-- 2. Fixes auth/profile sync issues with auth.users triggers
-- 3. Adds indexes, constraints, RLS, realtime setup
-- 4. Seeds demo data that matches the current frontend/backend
-- 5. Adds dummy data for Tejas, Shweta, Aryan, Sakshi, and Jiya
-- ============================================================

create extension if not exists pgcrypto;

-- ============================================================
-- CLEAN RESET (RAKSHA-FORCE TABLES ONLY)
-- ============================================================

drop table if exists public.incident_messages cascade;
drop table if exists public.assignments cascade;
drop table if exists public.gps_locations cascade;
drop table if exists public.sos_alerts cascade;
drop table if exists public.incident_reports cascade;
drop table if exists public.volunteers cascade;
drop table if exists public.area_alerts cascade;
drop table if exists public.resources cascade;
drop table if exists public.teams cascade;
drop table if exists public.profiles cascade;

drop function if exists public.set_updated_at() cascade;
drop function if exists public.sync_profile_from_auth() cascade;

-- ============================================================
-- TABLES
-- ============================================================

create table public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  full_name   text not null,
  phone       text,
  role        text not null default 'citizen'
              check (role in ('citizen', 'responder', 'admin')),
  created_at  timestamptz not null default now()
);

create table public.teams (
  id            uuid primary key default gen_random_uuid(),
  name          text not null unique,
  type          text not null
                check (type in ('fire', 'medical', 'police', 'ndrf')),
  status        text not null default 'available'
                check (status in ('available', 'busy', 'offline')),
  latitude      double precision not null check (latitude between -90 and 90),
  longitude     double precision not null check (longitude between -180 and 180),
  capacity      integer not null default 5 check (capacity > 0),
  current_load  integer not null default 0 check (current_load >= 0 and current_load <= capacity),
  created_at    timestamptz not null default now()
);

create table public.resources (
  id                  uuid primary key default gen_random_uuid(),
  name                text not null unique,
  type                text not null
                      check (type in ('hospital', 'shelter', 'depot')),
  latitude            double precision not null check (latitude between -90 and 90),
  longitude           double precision not null check (longitude between -180 and 180),
  total_capacity      integer not null default 0 check (total_capacity >= 0),
  available_capacity  integer not null default 0
                      check (available_capacity >= 0 and available_capacity <= total_capacity),
  contact             text,
  created_at          timestamptz not null default now()
);

create table public.incident_reports (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid references auth.users(id) on delete set null,
  emergency_type   text not null
                   check (emergency_type in (
                     'fire', 'medical', 'police', 'ambulance', 'fire_brigade',
                     'accident', 'flood', 'women', 'child', 'missing', 'other'
                   )),
  description      text not null default '',
  reporter_name    text,
  phone            text,
  location         text,
  latitude         double precision not null check (latitude between -90 and 90),
  longitude        double precision not null check (longitude between -180 and 180),
  status           text not null default 'pending'
                   check (status in ('pending', 'assigned', 'on_the_way', 'resolved')),
  priority         integer not null default 3 check (priority between 1 and 4),
  assigned_team_id uuid references public.teams(id) on delete set null,
  image_url        text,
  duplicate_of     uuid references public.incident_reports(id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table public.sos_alerts (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users(id) on delete set null,
  type        text not null
              check (type in (
                'medical', 'fire', 'police', 'flood', 'accident',
                'women_safety', 'child', 'missing', 'other'
              )),
  description text not null default '',
  latitude    double precision not null check (latitude between -90 and 90),
  longitude   double precision not null check (longitude between -180 and 180),
  status      text not null default 'active'
              check (status in ('active', 'resolved')),
  created_at  timestamptz not null default now()
);

create table public.gps_locations (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  latitude      double precision not null check (latitude between -90 and 90),
  longitude     double precision not null check (longitude between -180 and 180),
  page_context  text not null default 'unknown'
                check (page_context in ('citizen', 'admin', 'report', 'volunteer', 'unknown')),
  updated_at    timestamptz not null default now()
);

create table public.assignments (
  id           uuid primary key default gen_random_uuid(),
  incident_id  uuid not null unique references public.incident_reports(id) on delete cascade,
  team_id      uuid not null references public.teams(id) on delete cascade,
  eta_minutes  integer check (eta_minutes is null or eta_minutes > 0),
  notes        text,
  assigned_at  timestamptz not null default now()
);

create table public.incident_messages (
  id           uuid primary key default gen_random_uuid(),
  incident_id  uuid not null references public.incident_reports(id) on delete cascade,
  sender_name  text not null,
  sender_role  text not null
               check (sender_role in ('citizen', 'responder', 'admin')),
  message      text not null,
  created_at   timestamptz not null default now()
);

create table public.volunteers (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  phone       text not null unique,
  city        text not null,
  skill       text not null
              check (skill in (
                'doctor', 'nurse', 'paramedic', 'firefighter', 'police',
                'ndrf_trained', 'flood_rescue', 'counselor', 'driver',
                'translator', 'logistics', 'other'
              )),
  status      text not null default 'available'
              check (status in ('available', 'busy', 'inactive')),
  created_at  timestamptz not null default now()
);

create table public.area_alerts (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  message     text not null,
  area        text not null,
  severity    text not null default 'medium'
              check (severity in ('low', 'medium', 'high')),
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

-- ============================================================
-- INDEXES
-- ============================================================

create index idx_incident_reports_user_id      on public.incident_reports(user_id);
create index idx_incident_reports_status       on public.incident_reports(status);
create index idx_incident_reports_priority     on public.incident_reports(priority);
create index idx_incident_reports_type         on public.incident_reports(emergency_type);
create index idx_incident_reports_created_at   on public.incident_reports(created_at desc);

create index idx_sos_alerts_status             on public.sos_alerts(status);
create index idx_sos_alerts_created_at         on public.sos_alerts(created_at desc);

create index idx_gps_locations_context         on public.gps_locations(page_context);
create index idx_gps_locations_updated_at      on public.gps_locations(updated_at desc);

create index idx_assignments_team_id           on public.assignments(team_id);

create index idx_incident_messages_incident_id on public.incident_messages(incident_id);
create index idx_incident_messages_created_at  on public.incident_messages(created_at);

create index idx_teams_status                  on public.teams(status);
create index idx_teams_type                    on public.teams(type);

create index idx_resources_type                on public.resources(type);

create index idx_volunteers_status             on public.volunteers(status);
create index idx_volunteers_skill              on public.volunteers(skill);
create index idx_volunteers_city               on public.volunteers(city);

create index idx_area_alerts_active            on public.area_alerts(active);
create index idx_area_alerts_created_at        on public.area_alerts(created_at desc);

-- ============================================================
-- TIMESTAMP TRIGGER
-- ============================================================

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger trg_incident_reports_updated_at
before update on public.incident_reports
for each row execute function public.set_updated_at();

create trigger trg_gps_locations_updated_at
before update on public.gps_locations
for each row execute function public.set_updated_at();

-- ============================================================
-- AUTH -> PROFILE SYNC
-- Fixes missing profile rows after signup/login flows
-- ============================================================

create or replace function public.sync_profile_from_auth()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_role  text;
  v_name  text;
  v_phone text;
begin
  v_role := coalesce(new.raw_user_meta_data ->> 'role', 'citizen');
  if v_role not in ('citizen', 'responder', 'admin') then
    v_role := 'citizen';
  end if;

  v_name := nullif(trim(coalesce(new.raw_user_meta_data ->> 'full_name', '')), '');
  if v_name is null then
    v_name := split_part(coalesce(new.email, 'user'), '@', 1);
  end if;

  v_phone := nullif(trim(coalesce(new.raw_user_meta_data ->> 'phone', '')), '');

  insert into public.profiles (id, full_name, phone, role)
  values (new.id, v_name, v_phone, v_role)
  on conflict (id) do update
  set
    full_name = excluded.full_name,
    phone = excluded.phone,
    role = excluded.role;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.sync_profile_from_auth();

drop trigger if exists on_auth_user_updated on auth.users;
create trigger on_auth_user_updated
after update of email, raw_user_meta_data on auth.users
for each row execute function public.sync_profile_from_auth();

-- Backfill profiles for any auth users that already exist.
insert into public.profiles (id, full_name, phone, role)
select
  u.id,
  coalesce(
    nullif(trim(coalesce(u.raw_user_meta_data ->> 'full_name', '')), ''),
    split_part(coalesce(u.email, 'user'), '@', 1)
  ) as full_name,
  nullif(trim(coalesce(u.raw_user_meta_data ->> 'phone', '')), '') as phone,
  case
    when coalesce(u.raw_user_meta_data ->> 'role', 'citizen') in ('citizen', 'responder', 'admin')
      then coalesce(u.raw_user_meta_data ->> 'role', 'citizen')
    else 'citizen'
  end as role
from auth.users u
on conflict (id) do update
set
  full_name = excluded.full_name,
  phone = excluded.phone,
  role = excluded.role;

-- ============================================================
-- RLS POLICIES
-- Demo-friendly so the current frontend works without table errors.
-- ============================================================

alter table public.profiles          enable row level security;
alter table public.teams             enable row level security;
alter table public.resources         enable row level security;
alter table public.incident_reports  enable row level security;
alter table public.sos_alerts        enable row level security;
alter table public.gps_locations     enable row level security;
alter table public.assignments       enable row level security;
alter table public.incident_messages enable row level security;
alter table public.volunteers        enable row level security;
alter table public.area_alerts       enable row level security;

-- ============================================================
-- RLS POLICIES
-- Production-hardened: Restrict access based on ownership and roles.
-- ============================================================

alter table public.profiles          enable row level security;
alter table public.teams             enable row level security;
alter table public.resources         enable row level security;
alter table public.incident_reports  enable row level security;
alter table public.sos_alerts        enable row level security;
alter table public.gps_locations     enable row level security;
alter table public.assignments       enable row level security;
alter table public.incident_messages enable row level security;
alter table public.volunteers        enable row level security;
alter table public.area_alerts       enable row level security;

-- PROFILES
create policy "profiles_select_self" on public.profiles for select using (auth.uid() = id or exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));
create policy "profiles_update_self" on public.profiles for update using (auth.uid() = id);

-- TEAMS
create policy "teams_select_all" on public.teams for select using (true);
create policy "teams_admin_all" on public.teams for all using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));

-- RESOURCES
create policy "resources_select_all" on public.resources for select using (true);
create policy "resources_admin_all" on public.resources for all using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));

-- INCIDENTS
create policy "incidents_select_own_or_admin" on public.incident_reports for select using (auth.uid() = user_id or exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));
create policy "incidents_insert_authenticated" on public.incident_reports for insert with check (auth.role() = 'authenticated' or true); -- Allow anonymous for life-saving
create policy "incidents_update_own_or_admin" on public.incident_reports for update using (auth.uid() = user_id or exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));

-- SOS
create policy "sos_select_own_or_admin" on public.sos_alerts for select using (auth.uid() = user_id or exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));
create policy "sos_insert_all" on public.sos_alerts for insert with check (true);
create policy "sos_update_admin" on public.sos_alerts for update using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));

-- GPS
create policy "gps_select_admin" on public.gps_locations for select using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));
create policy "gps_upsert_self" on public.gps_locations for all using (auth.uid() = user_id);

-- ASSIGNMENTS
create policy "assignments_select_all" on public.assignments for select using (true);
create policy "assignments_admin_all" on public.assignments for all using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));

-- MESSAGES
create policy "messages_select_incident" on public.incident_messages for select using (exists (select 1 from public.incident_reports where id = incident_id and (user_id = auth.uid() or exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'))));
create policy "messages_insert_incident" on public.incident_messages for insert with check (exists (select 1 from public.incident_reports where id = incident_id and (user_id = auth.uid() or exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'))));

-- VOLUNTEERS
create policy "volunteers_select_admin" on public.volunteers for select using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));
create policy "volunteers_insert_all" on public.volunteers for insert with check (true);

-- ALERTS
create policy "alerts_select_all" on public.area_alerts for select using (true);
create policy "alerts_admin_all" on public.area_alerts for all using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));

-- ============================================================
-- REALTIME
-- ============================================================

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'incident_reports'
    ) then
      alter publication supabase_realtime add table public.incident_reports;
    end if;

    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'sos_alerts'
    ) then
      alter publication supabase_realtime add table public.sos_alerts;
    end if;

    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'incident_messages'
    ) then
      alter publication supabase_realtime add table public.incident_messages;
    end if;

    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'area_alerts'
    ) then
      alter publication supabase_realtime add table public.area_alerts;
    end if;

    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'teams'
    ) then
      alter publication supabase_realtime add table public.teams;
    end if;
  end if;
end $$;

-- ============================================================
-- DEMO SEED DATA
-- ============================================================

insert into public.teams (id, name, type, status, latitude, longitude, capacity, current_load) values
  ('10000000-0000-0000-0000-000000000001', 'Alpha Fire Unit',       'fire',    'available', 18.5204, 73.8567, 6, 0),
  ('10000000-0000-0000-0000-000000000002', 'Bravo Ambulance',       'medical', 'busy',      18.5104, 73.8450, 4, 1),
  ('10000000-0000-0000-0000-000000000003', 'Charlie Police Patrol', 'police',  'available', 18.5350, 73.8700, 5, 0),
  ('10000000-0000-0000-0000-000000000004', 'Delta NDRF Unit',       'ndrf',    'available', 18.5000, 73.8300, 8, 0),
  ('10000000-0000-0000-0000-000000000005', 'Echo Medical Team',     'medical', 'busy',      18.5500, 73.8800, 4, 1);

insert into public.resources (id, name, type, latitude, longitude, total_capacity, available_capacity, contact) values
  ('20000000-0000-0000-0000-000000000001', 'Sassoon General Hospital', 'hospital', 18.5147, 73.8553, 500, 87,  '020-26128000'),
  ('20000000-0000-0000-0000-000000000002', 'Ruby Hall Clinic',         'hospital', 18.5314, 73.8797, 300, 42,  '020-66455100'),
  ('20000000-0000-0000-0000-000000000003', 'KEM Hospital',             'hospital', 18.5024, 73.8563, 400, 110, '020-26127865'),
  ('20000000-0000-0000-0000-000000000004', 'Katraj Emergency Shelter', 'shelter',  18.4530, 73.8567, 200, 150, '020-24371234'),
  ('20000000-0000-0000-0000-000000000005', 'Shivajinagar Relief Camp', 'shelter',  18.5289, 73.8469, 150, 100, '020-25519999'),
  ('20000000-0000-0000-0000-000000000006', 'Khadki Fire Depot',        'depot',    18.5657, 73.8533, 50,  50,  '020-25813100');

insert into public.volunteers (id, name, phone, city, skill, status) values
  ('70000000-0000-0000-0000-000000000001', 'Tejas Dubey',      '9876543210', 'Pune',   'paramedic',    'available'),
  ('70000000-0000-0000-0000-000000000002', 'Shweta Patil',     '9876543211', 'Mumbai', 'doctor',       'available'),
  ('70000000-0000-0000-0000-000000000003', 'Aryan Sharma',     '9876543212', 'Pune',   'logistics',    'busy'),
  ('70000000-0000-0000-0000-000000000004', 'Sakshi Kulkarni',  '9876543213', 'Nashik', 'counselor',    'available'),
  ('70000000-0000-0000-0000-000000000005', 'Jiya Verma',       '9876543214', 'Nagpur', 'translator',   'inactive');

insert into public.incident_reports (
  id, user_id, emergency_type, description, reporter_name, phone, location,
  latitude, longitude, status, priority, assigned_team_id, image_url, duplicate_of,
  created_at, updated_at
) values
  (
    '30000000-0000-0000-0000-000000000001',
    null,
    'fire',
    'Smoke and flames visible from a textile storage room near Shivajinagar bus stand.',
    'Tejas',
    '9876543210',
    'Shivajinagar Bus Stand, Pune',
    18.5303,
    73.8471,
    'pending',
    1,
    null,
    null,
    null,
    now() - interval '35 minutes',
    now() - interval '35 minutes'
  ),
  (
    '30000000-0000-0000-0000-000000000002',
    null,
    'medical',
    'An elderly person is unconscious outside a pharmacy and needs urgent ambulance support.',
    'Shweta',
    '9876543211',
    'FC Road, Pune',
    18.5208,
    73.8412,
    'assigned',
    1,
    '10000000-0000-0000-0000-000000000002',
    null,
    null,
    now() - interval '26 minutes',
    now() - interval '12 minutes'
  ),
  (
    '30000000-0000-0000-0000-000000000003',
    null,
    'police',
    'Suspicious unattended bag reported near the station entrance. Crowd gathering at the site.',
    'Aryan',
    '9876543212',
    'Pune Junction Railway Station',
    18.5286,
    73.8743,
    'resolved',
    3,
    null,
    null,
    null,
    now() - interval '2 hours',
    now() - interval '70 minutes'
  ),
  (
    '30000000-0000-0000-0000-000000000004',
    null,
    'accident',
    'Two-wheeler collision blocking one lane, one rider injured and traffic is building quickly.',
    'Sakshi',
    '9876543213',
    'JM Road, Pune',
    18.5196,
    73.8446,
    'on_the_way',
    2,
    '10000000-0000-0000-0000-000000000005',
    null,
    null,
    now() - interval '18 minutes',
    now() - interval '6 minutes'
  ),
  (
    '30000000-0000-0000-0000-000000000005',
    null,
    'flood',
    'Waterlogging is rising in a narrow lane and several residents are unable to move their vehicles.',
    'Jiya',
    '9876543214',
    'Kharadi Bypass Service Lane, Pune',
    18.5510,
    73.9440,
    'pending',
    1,
    null,
    null,
    null,
    now() - interval '9 minutes',
    now() - interval '9 minutes'
  );

insert into public.assignments (id, incident_id, team_id, eta_minutes, notes, assigned_at) values
  (
    '40000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000002',
    8,
    'Nearest ambulance assigned for unconscious patient on FC Road.',
    now() - interval '12 minutes'
  ),
  (
    '40000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000005',
    6,
    'Medical team and traffic assistance dispatched to JM Road collision.',
    now() - interval '6 minutes'
  );

insert into public.incident_messages (id, incident_id, sender_name, sender_role, message, created_at) values
  (
    '50000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000002',
    'Shweta',
    'citizen',
    'The patient is breathing but not responding properly.',
    now() - interval '20 minutes'
  ),
  (
    '50000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000002',
    'Command Desk',
    'responder',
    'Ambulance assigned. Keep the patient on their side if vomiting occurs.',
    now() - interval '11 minutes'
  ),
  (
    '50000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000004',
    'Sakshi',
    'citizen',
    'One rider has a leg injury and traffic is slowing down in both directions.',
    now() - interval '15 minutes'
  ),
  (
    '50000000-0000-0000-0000-000000000004',
    '30000000-0000-0000-0000-000000000004',
    'Command Desk',
    'responder',
    'Medical team is on the way. Police support has been informed for traffic clearance.',
    now() - interval '5 minutes'
  ),
  (
    '50000000-0000-0000-0000-000000000005',
    '30000000-0000-0000-0000-000000000001',
    'Tejas',
    'citizen',
    'Fire is getting stronger and nearby shops are shutting their shutters.',
    now() - interval '30 minutes'
  );

insert into public.sos_alerts (id, user_id, type, description, latitude, longitude, status, created_at) values
  (
    '80000000-0000-0000-0000-000000000001',
    null,
    'medical',
    'Emergency SOS triggered near FC Road for unconscious person.',
    18.5208,
    73.8412,
    'active',
    now() - interval '24 minutes'
  ),
  (
    '80000000-0000-0000-0000-000000000002',
    null,
    'women_safety',
    'SOS triggered from a moving cab route near Koregaon Park.',
    18.5362,
    73.8930,
    'active',
    now() - interval '14 minutes'
  );

insert into public.area_alerts (id, title, message, area, severity, active, created_at) values
  (
    '60000000-0000-0000-0000-000000000001',
    'Flood Watch Active',
    'Heavy rainfall forecast. Residents near rivers and low-lying roads should move vehicles and stay alert.',
    'Pune Riverfront Areas',
    'high',
    true,
    now() - interval '3 hours'
  ),
  (
    '60000000-0000-0000-0000-000000000002',
    'Traffic Advisory',
    'Emergency response movement expected near Pune Junction and FC Road. Use alternate routes where possible.',
    'Central Pune',
    'medium',
    true,
    now() - interval '90 minutes'
  );

-- ============================================================
-- DONE
-- This schema is aligned to the current frontend/backend.
-- ============================================================
