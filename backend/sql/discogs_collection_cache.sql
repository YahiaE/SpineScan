create table if not exists public.discogs_collection_cache (
    id bigserial primary key,
    discogs_username text not null,
    folder_id bigint not null,
    release_id bigint not null,
    album_key text not null,
    last_seen_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists discogs_collection_cache_release_uidx
    on public.discogs_collection_cache (discogs_username, folder_id, release_id);

create index if not exists discogs_collection_cache_album_idx
    on public.discogs_collection_cache (discogs_username, folder_id, album_key);
