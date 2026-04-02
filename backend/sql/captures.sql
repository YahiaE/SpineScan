create table if not exists public.captures (
    id bigserial primary key,
    user_scope text not null,
    object_key text not null unique,
    content_type text,
    checksum_sha256 text not null,
    signature text not null,
    status text not null default 'uploaded',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists captures_user_scope_created_at_idx
    on public.captures (user_scope, created_at desc);

create index if not exists captures_status_idx
    on public.captures (status);
