-- Run this against your Supabase Postgres database.
-- Connection: use the pooler URL from Supabase dashboard.

create extension if not exists "pgcrypto";

-- Users (magic-link accounts + guests)
create table if not exists users (
    id          uuid primary key default gen_random_uuid(),
    email       text unique,
    handle      text unique not null,
    is_guest    boolean not null default false,
    created_at  timestamptz not null default now()
);

-- Magic link tokens
create table if not exists magic_link_tokens (
    token       text primary key,
    email       text not null,
    intent      text not null check (intent in ('signup', 'login')),
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null,
    used_at     timestamptz
);

-- Sessions
create table if not exists sessions (
    id           text primary key,
    user_id      uuid not null references users(id) on delete cascade,
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null,
    last_seen_at timestamptz not null default now()
);

-- Problems
create table if not exists problems (
    id                 uuid primary key default gen_random_uuid(),
    slug               text unique not null,
    title              text not null,
    statement_md       text not null,
    difficulty         text not null check (difficulty in ('easy', 'medium', 'hard')),
    test_cases         jsonb not null default '[]',
    hidden_test_cases  jsonb not null default '[]',
    reference_solution text,
    language           text not null default 'python'
);

-- Matches
create table if not exists matches (
    id           uuid primary key default gen_random_uuid(),
    join_code    text unique not null,
    problem_id   uuid not null references problems(id),
    player_a_id  uuid not null references users(id),
    player_b_id  uuid references users(id),
    status       text not null default 'lobby' check (status in ('lobby', 'live', 'finished')),
    started_at   timestamptz,
    finished_at  timestamptz,
    winner_id    uuid references users(id),
    result       jsonb,
    created_at   timestamptz not null default now()
);

-- Code runs
create table if not exists match_runs (
    id           uuid primary key default gen_random_uuid(),
    match_id     uuid not null references matches(id) on delete cascade,
    player       text not null check (player in ('a', 'b')),
    code         text not null,
    stdout       text,
    stderr       text,
    exit_code    int,
    runtime_ms   int,
    tests_passed int,
    tests_total  int,
    ts_ms        bigint not null
);

-- Code snapshots (written every 500ms of activity for replay + agent)
create table if not exists match_snapshots (
    id       bigserial primary key,
    match_id uuid not null references matches(id) on delete cascade,
    player   text not null check (player in ('a', 'b')),
    code     text not null,
    ts_ms    bigint not null
);

-- Detected events
create table if not exists match_events (
    id         bigserial primary key,
    match_id   uuid not null references matches(id) on delete cascade,
    type       text not null,
    player     text not null,
    payload    jsonb not null default '{}',
    confidence real,
    ts_ms      bigint not null
);

-- Commentary lines
create table if not exists match_commentary (
    id                   bigserial primary key,
    match_id             uuid not null references matches(id) on delete cascade,
    ts_ms                bigint not null,
    text                 text not null,
    triggered_by_event_id bigint references match_events(id),
    model                text,
    prompt_version       text
);

-- Indexes
create index if not exists idx_sessions_user_id      on sessions(user_id);
create index if not exists idx_sessions_expires_at   on sessions(expires_at);
create index if not exists idx_matches_join_code      on matches(join_code);
create index if not exists idx_matches_player_a       on matches(player_a_id);
create index if not exists idx_matches_player_b       on matches(player_b_id);
create index if not exists idx_snapshots_match_player on match_snapshots(match_id, player);
create index if not exists idx_events_match           on match_events(match_id);
create index if not exists idx_commentary_match       on match_commentary(match_id);
create index if not exists idx_tokens_email           on magic_link_tokens(email);
