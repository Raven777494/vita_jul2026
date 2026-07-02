-- init-db/04-pg-cron-jobs.sql
-- Scheduled maintenance for gsw_eternal_echoes (replaces legacy embeddings cleanup).

DO $$
DECLARE
    existing_job_id bigint;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        RAISE NOTICE 'pg_cron not installed; skip scheduling';
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'gsw_eternal_echoes'
    ) THEN
        RAISE NOTICE 'gsw_eternal_echoes not found; cron job deferred to app bootstrap';
        RETURN;
    END IF;

    SELECT jobid INTO existing_job_id
    FROM cron.job
    WHERE jobname = 'clean-old-gsw-echoes'
    LIMIT 1;

    IF existing_job_id IS NOT NULL THEN
        PERFORM cron.unschedule(existing_job_id);
    END IF;

    PERFORM cron.schedule(
        'clean-old-gsw-echoes',
        '0 2 * * *',
        $cmd$DELETE FROM gsw_eternal_echoes WHERE created_at < NOW() - INTERVAL '30 days'$cmd$
    );

    RAISE NOTICE 'Scheduled pg_cron job clean-old-gsw-echoes';
EXCEPTION
    WHEN undefined_table THEN
        RAISE NOTICE 'cron catalog unavailable; job deferred to app bootstrap';
    WHEN OTHERS THEN
        RAISE NOTICE 'pg_cron scheduling skipped: %', SQLERRM;
END $$;
