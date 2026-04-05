begin;

update public.discogs_collection_cache
set album_key = replace(album_key, ' ', ''),
    updated_at = now(),
    last_seen_at = now()
where album_key like '% %';

with ranked_albums as (
    select
        id,
        replace(normalized_key, ' ', '') as normalized_target,
        row_number() over (
            partition by replace(normalized_key, ' ', '')
            order by updated_at desc nulls last, created_at desc nulls last, id desc
        ) as rn
    from public.albums
), deleted_duplicates as (
    delete from public.albums
    where id in (
        select id
        from ranked_albums
        where rn > 1
    )
    returning id
)
update public.albums
set normalized_key = replace(normalized_key, ' ', ''),
    updated_at = now()
where normalized_key like '% %';

commit;
