-- Run AFTER deploying Edge Functions
-- Run this in Supabase SQL Editor
-- IMPORTANT: Replace YOUR_PROJECT_REF and YOUR_SERVICE_ROLE_KEY below

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- Store secrets in vault (more secure than inline)
-- After running migration, set these via:
-- SELECT vault.create_secret('YOUR_SERVICE_ROLE_KEY_HERE', 'service_role_key');
-- SELECT vault.create_secret('https://YOUR_PROJECT.supabase.co', 'project_url');

-- ===========================================================================
-- Weekly full scrape: every Monday at 3:00 AM UTC
-- ===========================================================================
SELECT cron.schedule(
    'weekly-fbi-scrape',
    '0 3 * * 1',
    $$
    SELECT net.http_post(
        url := (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'project_url') || '/functions/v1/scrape-fbi',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'::jsonb
    );
    $$
);

-- ===========================================================================
-- Daily heartbeat: every day at 3:00 AM UTC
-- ===========================================================================
SELECT cron.schedule(
    'daily-fbi-heartbeat',
    '0 3 * * *',
    $$
    SELECT net.http_post(
        url := (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'project_url') || '/functions/v1/heartbeat',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'::jsonb
    );
    $$
);

-- View scheduled jobs
-- SELECT * FROM cron.job;

-- Unschedule (if needed)
-- SELECT cron.unschedule('weekly-fbi-scrape');
-- SELECT cron.unschedule('daily-fbi-heartbeat');
