-- Scheduled cleanup of stale discogs_collection_cache rows.
--
-- Rows inactive for more than 30 days are removed. last_seen_at is updated
-- on every collection warm and every write-through cache entry, so any user
-- who has imported within the past 30 days is unaffected.
--
-- Prerequisites:
--   create extension if not exists pg_cron;
--
-- To register the job (run once in the Supabase SQL editor):

select cron.schedule(
    'cleanup-stale-collection-cache',
    '0 3 * * *',
    $$
        delete from public.discogs_collection_cache
        where last_seen_at < now() - interval '30 days';
    $$
);

-- To verify:
--   select * from cron.job where jobname = 'cleanup-stale-collection-cache';
--
-- To remove:
--   select cron.unschedule('cleanup-stale-collection-cache');
