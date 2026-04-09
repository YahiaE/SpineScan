-- Scheduled cleanup of stale import history rows.
--
-- Rows older than 7 days are removed once per week.
-- This preserves recent user-visible history while preventing the imports
-- audit table from growing without bound.
--
-- Prerequisites:
--   create extension if not exists pg_cron;
--
-- To register the job (run once in the Supabase SQL editor):

select cron.schedule(
    'cleanup-stale-import-history',
    '0 3 * * 0',
    $$
        delete from public.imports
        where created_at < now() - interval '7 days';
    $$
);

-- To verify:
--   select * from cron.job where jobname = 'cleanup-stale-import-history';
--
-- To remove:
--   select cron.unschedule('cleanup-stale-import-history');