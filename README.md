# UnsolvedWatch.live

Civic accountability project tracking FBI crime data and police reporting gaps across all 50 states.

Part of the Civic Tools Network alongside [CourtWatch.live](https://courtwatch.live). Built by Shadow Vortex LLC.

## Architecture

- **Database:** Supabase (PostgreSQL)
- **Scraper:** Supabase Edge Functions (Deno/TypeScript)
- **Scheduler:** pg_cron + pg_net (runs inside Supabase, no external VPS needed)
- **Site:** Static HTML/CSS/JS, hosted on Netlify
- **Data source:** [FBI Crime Data Explorer](https://cde.ucr.cjis.gov)

## Project layout

```
unsolvedwatch/
├── supabase/
│   ├── migrations/
│   │   ├── 001_initial_schema.sql     # Tables, views, RLS
│   │   └── 002_schedule_cron.sql      # pg_cron jobs (run AFTER deploying functions)
│   └── functions/
│       ├── scrape-fbi/index.ts        # Main scraper
│       └── heartbeat/index.ts         # Daily refresh check
├── site/
│   ├── index.html                     # Homepage
│   ├── styles.css                     # Editorial dark theme
│   └── js/
│       ├── config.js                  # Supabase client config
│       └── index.js                   # Homepage logic
└── netlify.toml                       # Netlify deployment config
```

## Deployment

### 1. Database schema

In the Supabase Dashboard → SQL Editor, paste and run:

```bash
supabase/migrations/001_initial_schema.sql
```

This creates tables (`agencies`, `crime_data`, `scrape_runs`, `states`, `offenses`), views (`reporting_status`, `state_latest`), and Row Level Security policies. It also seeds all 50 states + DC and the 8 offense codes.

### 2. Deploy Edge Functions

Install the Supabase CLI if you haven't:

```bash
npm install -g supabase
```

Login and link the project:

```bash
supabase login
supabase link --project-ref qledolmbjvxdqlztmqdd
```

Deploy both functions:

```bash
supabase functions deploy scrape-fbi
supabase functions deploy heartbeat
```

### 3. Set Edge Function secrets

The functions need access to `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. These are automatically available inside Supabase Edge Functions — no manual setup needed.

### 4. Run first scrape manually

Before scheduling, test by invoking the function manually:

```bash
curl -X POST 'https://qledolmbjvxdqlztmqdd.supabase.co/functions/v1/scrape-fbi' \
  -H 'Authorization: Bearer YOUR_SERVICE_ROLE_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"state_filter":"FL"}'
```

This scrapes only Florida as a smoke test. Check `scrape_runs` table for results.

For full 50-state run (will take ~5-10 minutes):

```bash
curl -X POST 'https://qledolmbjvxdqlztmqdd.supabase.co/functions/v1/scrape-fbi' \
  -H 'Authorization: Bearer YOUR_SERVICE_ROLE_KEY' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### 5. Schedule cron jobs

After confirming a manual scrape works, set up the recurring schedule. In Supabase SQL Editor, run:

```sql
-- First, store secrets in vault
SELECT vault.create_secret('https://qledolmbjvxdqlztmqdd.supabase.co', 'project_url');
SELECT vault.create_secret('YOUR_SERVICE_ROLE_KEY_HERE', 'service_role_key');
```

Then run `supabase/migrations/002_schedule_cron.sql` to schedule:
- **Weekly scrape**: every Monday 3 AM UTC
- **Daily heartbeat**: every day 3 AM UTC (triggers scrape if FBI refreshed)

### 6. Deploy site to Netlify

```bash
# Option A: Netlify CLI
npm install -g netlify-cli
netlify deploy --prod --dir=site

# Option B: Connect GitHub repo in Netlify dashboard
# Set publish directory: site
# Build command: (leave empty)
```

## API endpoint reference

State-level data:
```
GET https://cde.ucr.cjis.gov/LATEST/summarized/state/{STATE_ABBR}/{OFFENSE}?from=MM-YYYY&to=MM-YYYY&type=counts
```

Agency-level data:
```
GET https://cde.ucr.cjis.gov/LATEST/summarized/agency/{ORI}/{OFFENSE}?from=MM-YYYY&to=MM-YYYY&type=counts
```

Offense codes: `MUR`, `RAP`, `ROB`, `ASS`, `BUR`, `LAR`, `MVT`, `ARS`

No API key required. Browser-style session only.

## License

MIT
