create table if not exists public.imports (
    id bigserial primary key,
    discogs_username text not null,
    folder_id bigint not null,
    folder_name text,
    status text not null,
    added_count integer not null default 0,
    skipped_count integer not null default 0,
    failed_count integer not null default 0,
    results_json jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists imports_discogs_username_created_at_idx
    on public.imports (discogs_username, created_at desc);
