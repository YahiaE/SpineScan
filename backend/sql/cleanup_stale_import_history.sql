-- Scheduled cleanup of stale import history rows.
--
-- Rows older than 6 hours are removed every 6 hours.
-- This preserves recent user-visible history while preventing the imports
-- audit table from growing without bound.
--
-- Prerequisites:
--   create extension if not exists pg_cron;
--
-- To register the job (run once in the Supabase SQL editor):

do $$
begin
    if exists (
        select 1
        from cron.job
        where jobname = 'cleanup-stale-import-history'
    ) then
        perform cron.unschedule('cleanup-stale-import-history');
    end if;
end;
$$;

select cron.schedule(
    'cleanup-stale-import-history',
    '0 */6 * * *',
    $$
        delete from public.imports
        where created_at < now() - interval '6 hours';
    $$
);

-- To verify:
--   select * from cron.job where jobname = 'cleanup-stale-import-history';
--
-- To remove:
--   select cron.unschedule('cleanup-stale-import-history');