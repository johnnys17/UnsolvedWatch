-- UnsolvedWatch.live - Initial Schema
-- Run this in Supabase SQL Editor

-- =========================================================================
-- AGENCIES: directory of law enforcement agencies
-- =========================================================================
CREATE TABLE IF NOT EXISTS agencies (
    ori TEXT PRIMARY KEY,                 -- FBI Originating Agency Identifier, e.g. "FL0480400"
    name TEXT NOT NULL,                   -- "Orlando Police Department"
    state_abbr TEXT NOT NULL,             -- "FL"
    county TEXT,
    agency_type TEXT,                     -- city, county, state, federal, university, etc.
    is_nibrs BOOLEAN DEFAULT FALSE,       -- currently reporting NIBRS
    nibrs_start_date DATE,                -- when they started/will start NIBRS
    population INTEGER,                   -- latest known
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agencies_state ON agencies(state_abbr);
CREATE INDEX IF NOT EXISTS idx_agencies_nibrs ON agencies(is_nibrs);

-- =========================================================================
-- CRIME_DATA: time-series, one row per (jurisdiction, offense, month)
-- Handles both state-level and agency-level data
-- =========================================================================
CREATE TABLE IF NOT EXISTS crime_data (
    id BIGSERIAL PRIMARY KEY,
    jurisdiction_type TEXT NOT NULL CHECK (jurisdiction_type IN ('state', 'agency', 'national')),
    state_abbr TEXT,                      -- "FL", or NULL for national
    ori TEXT REFERENCES agencies(ori),    -- only set when jurisdiction_type = 'agency'
    offense_code TEXT NOT NULL,           -- MUR, RAP, ROB, ASS, BUR, LAR, MVT, ARS
    period_month INTEGER NOT NULL CHECK (period_month BETWEEN 1 AND 12),
    period_year INTEGER NOT NULL CHECK (period_year BETWEEN 1985 AND 2100),

    -- Raw counts (can be NULL when agency didn't report)
    offenses_count INTEGER,
    clearances_count INTEGER,

    -- Per 100k rates (FBI-calculated)
    offenses_rate NUMERIC(10, 2),
    clearances_rate NUMERIC(10, 2),

    -- Coverage metadata
    population INTEGER,
    participated_population INTEGER,
    coverage_pct NUMERIC(5, 2),

    -- Metadata
    is_annual_rollup BOOLEAN DEFAULT FALSE,  -- TRUE if value is a year-total stuffed into one month (legacy SRS quirk)
    fetched_at TIMESTAMPTZ DEFAULT NOW(),

    -- Uniqueness: one row per jurisdiction+offense+month
    UNIQUE NULLS NOT DISTINCT (jurisdiction_type, state_abbr, ori, offense_code, period_year, period_month)
);

CREATE INDEX IF NOT EXISTS idx_crime_state_offense ON crime_data(state_abbr, offense_code, period_year DESC, period_month DESC);
CREATE INDEX IF NOT EXISTS idx_crime_ori_offense ON crime_data(ori, offense_code, period_year DESC, period_month DESC);
CREATE INDEX IF NOT EXISTS idx_crime_jurisdiction ON crime_data(jurisdiction_type, period_year DESC);

-- =========================================================================
-- SCRAPE_RUNS: audit log of every scraper invocation
-- =========================================================================
CREATE TABLE IF NOT EXISTS scrape_runs (
    id BIGSERIAL PRIMARY KEY,
    run_type TEXT NOT NULL,               -- 'full', 'state', 'agency', 'heartbeat'
    target TEXT,                          -- state abbr or ORI being scraped, NULL for full
    status TEXT NOT NULL,                 -- 'started', 'success', 'partial', 'failed'
    fbi_max_data_date TEXT,               -- from cde_properties.max_data_date.UCR
    fbi_last_refresh_date TEXT,           -- from cde_properties.last_refresh_date.UCR
    rows_written INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_started ON scrape_runs(started_at DESC);

-- =========================================================================
-- VIEW: reporting_status — last reported month per agency
-- This powers the "Orlando hasn't reported in 4 years" angle
-- =========================================================================
CREATE OR REPLACE VIEW reporting_status AS
SELECT
    a.ori,
    a.name,
    a.state_abbr,
    a.is_nibrs,
    a.nibrs_start_date,
    a.population,
    MAX(MAKE_DATE(c.period_year, c.period_month, 1)) FILTER (
        WHERE c.offenses_count IS NOT NULL AND NOT c.is_annual_rollup
    ) AS last_monthly_report,
    MAX(c.period_year) FILTER (
        WHERE c.offenses_count IS NOT NULL
    ) AS last_year_with_data,
    COUNT(*) FILTER (
        WHERE c.offenses_count IS NOT NULL
            AND c.period_year = EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER
    ) AS months_reported_this_year
FROM agencies a
LEFT JOIN crime_data c ON c.ori = a.ori
GROUP BY a.ori, a.name, a.state_abbr, a.is_nibrs, a.nibrs_start_date, a.population;

-- =========================================================================
-- VIEW: state_latest — most recent month of state-level data per state
-- =========================================================================
CREATE OR REPLACE VIEW state_latest AS
SELECT DISTINCT ON (state_abbr, offense_code)
    state_abbr,
    offense_code,
    period_year,
    period_month,
    offenses_count,
    clearances_count,
    offenses_rate,
    clearances_rate,
    coverage_pct
FROM crime_data
WHERE jurisdiction_type = 'state'
    AND offenses_count IS NOT NULL
ORDER BY state_abbr, offense_code, period_year DESC, period_month DESC;

-- =========================================================================
-- ROW LEVEL SECURITY: lock down writes, allow public reads
-- =========================================================================
ALTER TABLE agencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE crime_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs ENABLE ROW LEVEL SECURITY;

-- Public can read everything
CREATE POLICY "Public read agencies" ON agencies FOR SELECT USING (true);
CREATE POLICY "Public read crime_data" ON crime_data FOR SELECT USING (true);
CREATE POLICY "Public read scrape_runs" ON scrape_runs FOR SELECT USING (true);

-- Only service_role can write (Edge Functions use service_role internally)
-- No INSERT/UPDATE/DELETE policies for anon/authenticated = denied by default

-- =========================================================================
-- SEED: 50 states + DC
-- =========================================================================
CREATE TABLE IF NOT EXISTS states (
    abbr TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    population INTEGER
);

ALTER TABLE states ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read states" ON states FOR SELECT USING (true);

INSERT INTO states (abbr, name) VALUES
('AL','Alabama'),('AK','Alaska'),('AZ','Arizona'),('AR','Arkansas'),('CA','California'),
('CO','Colorado'),('CT','Connecticut'),('DE','Delaware'),('FL','Florida'),('GA','Georgia'),
('HI','Hawaii'),('ID','Idaho'),('IL','Illinois'),('IN','Indiana'),('IA','Iowa'),
('KS','Kansas'),('KY','Kentucky'),('LA','Louisiana'),('ME','Maine'),('MD','Maryland'),
('MA','Massachusetts'),('MI','Michigan'),('MN','Minnesota'),('MS','Mississippi'),('MO','Missouri'),
('MT','Montana'),('NE','Nebraska'),('NV','Nevada'),('NH','New Hampshire'),('NJ','New Jersey'),
('NM','New Mexico'),('NY','New York'),('NC','North Carolina'),('ND','North Dakota'),('OH','Ohio'),
('OK','Oklahoma'),('OR','Oregon'),('PA','Pennsylvania'),('RI','Rhode Island'),('SC','South Carolina'),
('SD','South Dakota'),('TN','Tennessee'),('TX','Texas'),('UT','Utah'),('VT','Vermont'),
('VA','Virginia'),('WA','Washington'),('WV','West Virginia'),('WI','Wisconsin'),('WY','Wyoming'),
('DC','District of Columbia')
ON CONFLICT (abbr) DO NOTHING;

-- =========================================================================
-- OFFENSE CODES reference table
-- =========================================================================
CREATE TABLE IF NOT EXISTS offenses (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL
);

ALTER TABLE offenses ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read offenses" ON offenses FOR SELECT USING (true);

INSERT INTO offenses (code, name, short_name, sort_order) VALUES
('MUR','Murder and Nonnegligent Manslaughter','Murder',1),
('RAP','Rape','Rape',2),
('ROB','Robbery','Robbery',3),
('ASS','Aggravated Assault','Aggravated Assault',4),
('BUR','Burglary','Burglary',5),
('LAR','Larceny-Theft','Larceny',6),
('MVT','Motor Vehicle Theft','Vehicle Theft',7),
('ARS','Arson','Arson',8)
ON CONFLICT (code) DO NOTHING;

-- Done.
