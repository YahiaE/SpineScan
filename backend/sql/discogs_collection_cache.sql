create table if not exists public.discogs_collection_cache (
    id bigserial primary key,
    discogs_username text not null,
    folder_id bigint not null,
    release_id bigint not null,
    snapshot_generation text not null default 'legacy',
    album_key text not null,
    last_seen_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.discogs_collection_cache
    add column if not exists snapshot_generation text not null default 'legacy';

drop index if exists public.discogs_collection_cache_release_uidx;

create unique index if not exists discogs_collection_cache_snapshot_release_uidx
    on public.discogs_collection_cache (
        discogs_username,
        folder_id,
        snapshot_generation,
        release_id
    );

create table if not exists public.discogs_collection_cache_state (
    discogs_username text not null,
    folder_id bigint not null,
    active_generation text,
    is_complete boolean not null default false,
    last_success_at timestamptz,
    entry_count integer not null default 0,
    pages_fetched integer not null default 0,
    pages_total integer not null default 0,
    updated_at timestamptz not null default now(),
    primary key (discogs_username, folder_id)
);

create index if not exists discogs_collection_cache_album_idx
    on public.discogs_collection_cache (discogs_username, folder_id, album_key);
