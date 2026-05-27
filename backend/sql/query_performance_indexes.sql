-- Add query-performance indexes for hot validation/import paths.
--
-- Safe to run multiple times. Indexes are only created when the target
-- table/columns exist.

do $$
begin
    if exists (
        select 1
        from information_schema.tables
        where table_schema = 'public'
          and table_name = 'captures'
    ) then
        create index if not exists captures_user_scope_status_created_at_idx
            on public.captures (user_scope, status, created_at desc);
    end if;
end;
$$;

do $$
begin
    if exists (
        select 1
        from information_schema.tables
        where table_schema = 'public'
          and table_name = 'albums'
    ) and exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'albums'
          and column_name = 'normalized_key'
    ) then
        create unique index if not exists albums_normalized_key_uidx
            on public.albums (normalized_key);
    end if;
end;
$$;

do $$
begin
    if exists (
        select 1
        from information_schema.tables
        where table_schema = 'public'
          and table_name = 'albums'
    ) and exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'albums'
          and column_name = 'discogs_release_id'
    ) then
        create index if not exists albums_discogs_release_id_idx
            on public.albums (discogs_release_id);
    end if;
end;
$$;