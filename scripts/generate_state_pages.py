#!/usr/bin/env python3
"""
generate_state_pages.py
------------------------
Reads state-level crime data from Supabase and writes one static HTML
page per state to site/states/{abbr}/index.html. Also writes a
site/states/index.html directory page listing all states.

Run after each FBI scrape so the site reflects the latest data.

Environment variables required:
    SUPABASE_URL        e.g. https://qledolmbjvxdqlztmqdd.supabase.co
    SUPABASE_ANON_KEY   the public anon key (safe — read-only via RLS)

Usage:
    cd ~/Documents/Shadow\\ Vortex\\ LLC/Companies/UnsolvedWatch
    export SUPABASE_URL="https://qledolmbjvxdqlztmqdd.supabase.co"
    export SUPABASE_ANON_KEY="eyJ..."
    python3 scripts/generate_state_pages.py
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Set SUPABASE_URL and SUPABASE_ANON_KEY environment variables.", file=sys.stderr)
    sys.exit(1)

# Project root = parent of this script's directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "site" / "states"

# -------------------------------------------------------------------------
# Reference data
# -------------------------------------------------------------------------

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}

STATE_POPS = {
    "AL": 5108468, "AK": 733406, "AZ": 7431344, "AR": 3067732,
    "CA": 38965193, "CO": 5877610, "CT": 3617176, "DE": 1031890,
    "FL": 22610726, "GA": 11029227, "HI": 1435138, "ID": 1964726,
    "IL": 12549689, "IN": 6862199, "IA": 3207004, "KS": 2940546,
    "KY": 4526154, "LA": 4573749, "ME": 1395722, "MD": 6180253,
    "MA": 7001399, "MI": 10037261, "MN": 5737915, "MS": 2939690,
    "MO": 6196156, "MT": 1132812, "NE": 1978379, "NV": 3194176,
    "NH": 1402054, "NJ": 9290841, "NM": 2114371, "NY": 19571216,
    "NC": 10835491, "ND": 783926, "OH": 11785935, "OK": 4053824,
    "OR": 4233358, "PA": 12961683, "RI": 1095962, "SC": 5373555,
    "SD": 919318, "TN": 7126489, "TX": 30503301, "UT": 3417734,
    "VT": 647464, "VA": 8715698, "WA": 7812880, "WV": 1770071,
    "WI": 5910955, "WY": 584057, "DC": 678972,
}

OFFENSES = [
    ("HOM", "Homicide"),
    ("RPE", "Rape"),
    ("ROB", "Robbery"),
    ("ASS", "Aggravated assault"),
    ("BUR", "Burglary"),
    ("LAR", "Larceny"),
    ("MVT", "Motor vehicle theft"),
    ("ARS", "Arson"),
]
OFFENSE_NAMES = dict(OFFENSES)

MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
MONTH_SHORT = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# -------------------------------------------------------------------------
# Supabase fetch helper
# -------------------------------------------------------------------------

def sb_query(path, params=None):
    """Fetch from Supabase REST API. Returns parsed JSON or []."""
    if params is None:
        params = {}
    qs = urllib.parse.urlencode(params)
    url = f"{SUPABASE_URL}/rest/v1/{path}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ERROR fetching {path}: {e}", file=sys.stderr)
        return []


# -------------------------------------------------------------------------
# Data shaping
# -------------------------------------------------------------------------

def fetch_state_data(abbr):
    """Pull last 5 years of monthly data for one state, all offenses."""
    current_year = datetime.now().year
    rows = sb_query("crime_data", {
        "select": "state_abbr,offense_code,period_year,period_month,offenses_count,clearances_count",
        "jurisdiction_type": "eq.state",
        "state_abbr": f"eq.{abbr}",
        "is_annual_rollup": "eq.false",
        "period_year": f"gte.{current_year - 5}",
        "order": "period_year.asc,period_month.asc,offense_code.asc",
    })
    return rows


def shape_data(rows):
    """Group rows into a structure useful for the template."""
    by_offense = defaultdict(list)
    for r in rows:
        if r.get("offenses_count") is None:
            continue
        by_offense[r["offense_code"]].append({
            "year": r["period_year"],
            "month": r["period_month"],
            "count": int(r["offenses_count"]),
            "clearances": r.get("clearances_count"),
        })

    # Sort each offense's series by date
    for code in by_offense:
        by_offense[code].sort(key=lambda x: (x["year"], x["month"]))

    return by_offense


def compute_stats(by_offense):
    """For each offense compute trailing 12mo, prior 12mo, YoY change, period."""
    stats = {}
    for code, label in OFFENSES:
        series = by_offense.get(code, [])
        if not series:
            stats[code] = None
            continue

        # Trailing 12 most recent months
        last12 = series[-12:] if len(series) >= 12 else series
        prior12 = series[-24:-12] if len(series) >= 24 else []

        last_total = sum(p["count"] for p in last12)
        prior_total = sum(p["count"] for p in prior12) if prior12 else None

        yoy_pct = None
        if prior_total and prior_total > 0:
            yoy_pct = ((last_total - prior_total) / prior_total) * 100

        stats[code] = {
            "last12_total": last_total,
            "prior12_total": prior_total,
            "yoy_pct": yoy_pct,
            "months_of_data": len(last12),
            "latest_year": series[-1]["year"],
            "latest_month": series[-1]["month"],
            "earliest_in_window": last12[0] if last12 else None,
        }
    return stats


# -------------------------------------------------------------------------
# HTML rendering helpers
# -------------------------------------------------------------------------

def fmt_num(n):
    if n is None:
        return "—"
    return f"{int(n):,}"


def fmt_rate(rate):
    if rate is None:
        return "—"
    return f"{rate:.1f}"


def fmt_pct_change(pct):
    if pct is None:
        return "—"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def yoy_class(pct):
    if pct is None:
        return "neutral"
    if pct > 1:
        return "up"
    if pct < -1:
        return "down"
    return "flat"


def build_sparkline(series, width=200, height=40):
    """Tiny inline SVG sparkline of monthly counts. Last 60 months."""
    points = series[-60:] if len(series) > 60 else series
    if len(points) < 2:
        return '<svg width="200" height="40" viewBox="0 0 200 40"></svg>'

    counts = [p["count"] for p in points]
    max_c = max(counts) if counts else 1
    min_c = min(counts) if counts else 0
    rng = max(max_c - min_c, 1)

    n = len(counts)
    coords = []
    for i, c in enumerate(counts):
        x = (i / (n - 1)) * width if n > 1 else 0
        y = height - ((c - min_c) / rng) * height
        coords.append(f"{x:.1f},{y:.1f}")

    path_d = "M " + " L ".join(coords)
    last_x = (n - 1) / (n - 1) * width if n > 1 else 0
    last_y = height - ((counts[-1] - min_c) / rng) * height

    return f'''<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
        <path d="{path_d}" fill="none" stroke="var(--red)" stroke-width="1.5" />
        <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="var(--ink)" />
    </svg>'''


# -------------------------------------------------------------------------
# Page templates
# -------------------------------------------------------------------------

def render_state_page(abbr, stats, by_offense, all_state_index_data):
    name = STATE_NAMES[abbr]
    pop = STATE_POPS[abbr]

    # Build prev/next nav based on alphabetical order
    abbrs_sorted = sorted(STATE_NAMES.keys())
    idx = abbrs_sorted.index(abbr)
    prev_abbr = abbrs_sorted[idx - 1] if idx > 0 else abbrs_sorted[-1]
    next_abbr = abbrs_sorted[idx + 1] if idx < len(abbrs_sorted) - 1 else abbrs_sorted[0]

    hom = stats.get("HOM")
    if hom and hom["last12_total"] is not None:
        hom_total = hom["last12_total"]
        hom_rate = (hom_total / pop) * 100000
        period_str = f"{MONTH_NAMES[hom['latest_month']]} {hom['latest_year']}"
        hom_yoy = hom["yoy_pct"]
        hom_yoy_str = fmt_pct_change(hom_yoy)
        hom_yoy_cls = yoy_class(hom_yoy)
        has_data = True
    else:
        hom_total = 0
        hom_rate = 0
        period_str = "—"
        hom_yoy_str = "—"
        hom_yoy_cls = "neutral"
        has_data = False

    # Narrative analysis
    narrative = build_narrative(abbr, name, pop, stats, by_offense, all_state_index_data)

    # Offense table rows
    offense_rows = []
    for code, label in OFFENSES:
        st = stats.get(code)
        if not st or st["last12_total"] is None:
            offense_rows.append(f'''
            <tr class="offense-row offense-row--nodata">
                <td class="offense-name">{label}</td>
                <td class="offense-count">—</td>
                <td class="offense-rate">—</td>
                <td class="offense-yoy">—</td>
                <td class="offense-spark"></td>
            </tr>''')
            continue

        rate = (st["last12_total"] / pop) * 100000
        spark_svg = build_sparkline(by_offense.get(code, []))
        yoy_cls = yoy_class(st["yoy_pct"])

        offense_rows.append(f'''
        <tr class="offense-row">
            <td class="offense-name">{label}</td>
            <td class="offense-count">{fmt_num(st["last12_total"])}</td>
            <td class="offense-rate">{fmt_rate(rate)}</td>
            <td class="offense-yoy offense-yoy--{yoy_cls}">{fmt_pct_change(st["yoy_pct"])}</td>
            <td class="offense-spark">{spark_svg}</td>
        </tr>''')

    offense_table = "".join(offense_rows)

    # Build the page
    page_title = f"{name} crime data — UnsolvedWatch"
    page_desc = (
        f"FBI Uniform Crime Reporting data for {name}: "
        f"{fmt_num(hom_total)} homicides reported in the trailing 12 months "
        f"({fmt_rate(hom_rate)} per 100,000 residents)."
    ) if has_data else f"FBI crime data for {name}. Data may not yet be reported."

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <meta name="description" content="{page_desc}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;0,6..72,800;1,6..72,400;1,6..72,500&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/styles.css">
</head>
<body>
    <header class="masthead">
        <div class="container">
            <a href="/" class="brand">
                <span class="brand-mark"><span class="brand-star">★</span></span>
                <span class="brand-text">UnsolvedWatch</span>
            </a>
            <nav class="nav">
                <a href="/states/" class="is-active">States</a>
                <a href="/agencies/">Agencies</a>
                <a href="/gap/">The Gap</a>
                <a href="/about/">About</a>
            </nav>
        </div>
        <div class="masthead-stripe">
            <span class="stripe-red"></span>
            <span class="stripe-cream"></span>
            <span class="stripe-navy"></span>
        </div>
    </header>

    <main>
        <section class="state-hero">
            <div class="container">
                <a href="/" class="breadcrumb">← Back to map</a>
                <div class="state-hero-grid">
                    <div class="state-hero-main">
                        <div class="state-eyebrow">State of <span class="abbr-tag">{abbr}</span> · Pop. {fmt_num(pop)}</div>
                        <h1 class="state-name">{name}</h1>
                        <p class="state-dateline">Crime data through {period_str} · trailing 12 months</p>
                    </div>
                    <div class="state-hero-stat">
                        <div class="state-hero-stat-value">{fmt_num(hom_total)}</div>
                        <div class="state-hero-stat-label">Homicides reported</div>
                        <div class="state-hero-stat-rate">{fmt_rate(hom_rate)} <span>per 100k</span></div>
                        <div class="state-hero-stat-yoy yoy--{hom_yoy_cls}">YoY {hom_yoy_str}</div>
                    </div>
                </div>
            </div>
        </section>

        <section class="section section-paper-darker">
            <div class="container">
                <div class="section-header">
                    <h2 class="section-title">All eight FBI Part I offenses</h2>
                    <span class="section-meta">Trailing 12 months · per 100,000 residents</span>
                </div>
                <div class="offense-table-wrap">
                    <table class="offense-table">
                        <thead>
                            <tr>
                                <th>Offense</th>
                                <th class="num-col">Count</th>
                                <th class="num-col">Per 100k</th>
                                <th class="num-col">YoY</th>
                                <th class="trend-col">5-year trend</th>
                            </tr>
                        </thead>
                        <tbody>
                            {offense_table}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <section class="section">
            <div class="container">
                <div class="section-header">
                    <h2 class="section-title">What this data says</h2>
                </div>
                <div class="narrative">
                    {narrative}
                </div>
            </div>
        </section>

        <section class="section section-paper-darker">
            <div class="container">
                <div class="section-header">
                    <h2 class="section-title">Reporting agencies</h2>
                    <span class="section-meta">Local PDs and sheriffs in {name}</span>
                </div>
                <div class="agencies-placeholder">
                    <p>The UnsolvedWatch agency directory is being built. Once complete, this section will list every police department and sheriff's office in {name}, with their FBI reporting status and recent homicide clearance rates.</p>
                    <p class="placeholder-note">Want to see this faster? <a href="mailto:hello@unsolvedwatch.live">Reach out.</a></p>
                </div>
            </div>
        </section>

        <nav class="state-pagination">
            <div class="container">
                <a href="/states/{prev_abbr.lower()}/" class="state-pagination-prev">
                    <span class="state-pagination-label">← Previous state</span>
                    <span class="state-pagination-name">{STATE_NAMES[prev_abbr]}</span>
                </a>
                <a href="/states/" class="state-pagination-all">All 51 states</a>
                <a href="/states/{next_abbr.lower()}/" class="state-pagination-next">
                    <span class="state-pagination-label">Next state →</span>
                    <span class="state-pagination-name">{STATE_NAMES[next_abbr]}</span>
                </a>
            </div>
        </nav>
    </main>

    <footer class="site-footer">
        <div class="container">
            <p class="footer-line">UnsolvedWatch · A Civic Tools project · Sourcing FBI Crime Data Explorer</p>
            <p class="footer-line"><a href="/">unsolvedwatch.live</a> · <a href="https://courtwatch.live">courtwatch.live</a></p>
        </div>
    </footer>
</body>
</html>
'''


def build_narrative(abbr, name, pop, stats, by_offense, all_state_index_data):
    """Build a multi-paragraph narrative analysis from the data."""
    paragraphs = []

    hom = stats.get("HOM")
    if hom and hom["last12_total"] is not None:
        rate = (hom["last12_total"] / pop) * 100000

        # Paragraph 1: Headline
        yoy = hom.get("yoy_pct")
        if yoy is None:
            yoy_phrase = "Year-over-year comparison is not available."
        elif yoy > 5:
            yoy_phrase = f"That's a <strong>{fmt_pct_change(yoy)} increase</strong> compared to the prior 12-month window."
        elif yoy < -5:
            yoy_phrase = f"That's a <strong>{fmt_pct_change(yoy)} decrease</strong> compared to the prior 12-month window."
        else:
            yoy_phrase = f"That's roughly flat ({fmt_pct_change(yoy)}) compared to the prior 12-month window."

        paragraphs.append(
            f"<p>{name} reported <strong>{fmt_num(hom['last12_total'])} homicides</strong> in the trailing "
            f"12 months — a rate of <strong>{fmt_rate(rate)} per 100,000 residents</strong>. "
            f"{yoy_phrase}</p>"
        )

        # Paragraph 2: National comparison
        national_rates = []
        for st_abbr, idx_data in all_state_index_data.items():
            if idx_data.get("homicide_rate") is not None:
                national_rates.append((st_abbr, idx_data["homicide_rate"]))
        national_rates.sort(key=lambda x: x[1], reverse=True)

        if national_rates:
            rank = next((i + 1 for i, (a, _) in enumerate(national_rates) if a == abbr), None)
            total_ranked = len(national_rates)
            if rank:
                median_rate = national_rates[len(national_rates) // 2][1]
                if rate > median_rate * 1.3:
                    relative = "above the national median"
                elif rate < median_rate * 0.7:
                    relative = "below the national median"
                else:
                    relative = "near the national median"
                paragraphs.append(
                    f"<p>{name}'s rate is {relative}. It ranks <strong>#{rank} of {total_ranked}</strong> states "
                    f"by homicides per capita (1 = highest). The national median across all states is "
                    f"{fmt_rate(median_rate)} per 100,000.</p>"
                )
    else:
        paragraphs.append(
            f"<p>{name} has not yet submitted homicide data to the FBI for a complete trailing 12-month window — "
            f"or the data has not yet been published. This is itself a story: when states or their largest "
            f"police departments don't report, the national picture has blind spots.</p>"
        )

    # Paragraph 3: Other offenses callout
    notable = []
    for code, label in OFFENSES:
        if code == "HOM":
            continue
        st = stats.get(code)
        if st and st.get("yoy_pct") is not None:
            if abs(st["yoy_pct"]) > 15:
                direction = "up" if st["yoy_pct"] > 0 else "down"
                notable.append((label.lower(), direction, st["yoy_pct"]))

    if notable:
        bits = [f"<strong>{label} is {dir} {abs(p):.1f}%</strong>" for label, dir, p in notable[:3]]
        paragraphs.append(
            f"<p>Other notable year-over-year shifts: " + ", ".join(bits) + ".</p>"
        )

    # Paragraph 4: Methodology note
    paragraphs.append(
        f"<p class='narrative-meta'>All figures are pulled directly from the FBI's Crime Data Explorer, "
        f"which aggregates monthly submissions from local law enforcement agencies. Numbers reflect "
        f"offenses reported to police — not all crime, and not crime that was solved. Rate calculations "
        f"use 2024 U.S. Census Bureau population estimates.</p>"
    )

    return "\n".join(paragraphs)


def render_states_index(all_state_index_data):
    """The /states/ directory page listing all 51 states."""
    # Sort by homicide rate descending so the most-affected are highlighted at top,
    # but offer alphabetical view as well via CSS-only future enhancement.
    sorted_states = sorted(
        STATE_NAMES.keys(),
        key=lambda a: STATE_NAMES[a]
    )

    cards = []
    for abbr in sorted_states:
        name = STATE_NAMES[abbr]
        pop = STATE_POPS[abbr]
        idx = all_state_index_data.get(abbr, {})
        hom_total = idx.get("homicide_count")
        hom_rate = idx.get("homicide_rate")
        period = idx.get("period_str") or "—"

        if hom_total is not None:
            stat_line = f'<span class="card-stat-value">{fmt_num(hom_total)}</span> homicides · <span class="card-stat-rate">{fmt_rate(hom_rate)} per 100k</span>'
            period_line = f'Trailing 12mo · thru {period}'
        else:
            stat_line = '<span class="card-nodata">No recent data reported</span>'
            period_line = '—'

        cards.append(f'''
        <a class="state-card" href="/states/{abbr.lower()}/">
            <div class="state-card-eyebrow">{abbr} · Pop. {fmt_num(pop)}</div>
            <div class="state-card-name">{name}</div>
            <div class="state-card-stat">{stat_line}</div>
            <div class="state-card-period">{period_line}</div>
        </a>''')

    cards_html = "".join(cards)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>All 51 states — UnsolvedWatch</title>
    <meta name="description" content="FBI crime data for all 50 states and the District of Columbia. Trailing 12-month homicide counts and rates per 100,000.">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;0,6..72,800;1,6..72,400;1,6..72,500&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/styles.css">
</head>
<body>
    <header class="masthead">
        <div class="container">
            <a href="/" class="brand">
                <span class="brand-mark"><span class="brand-star">★</span></span>
                <span class="brand-text">UnsolvedWatch</span>
            </a>
            <nav class="nav">
                <a href="/states/" class="is-active">States</a>
                <a href="/agencies/">Agencies</a>
                <a href="/gap/">The Gap</a>
                <a href="/about/">About</a>
            </nav>
        </div>
        <div class="masthead-stripe">
            <span class="stripe-red"></span>
            <span class="stripe-cream"></span>
            <span class="stripe-navy"></span>
        </div>
    </header>

    <main>
        <section class="states-index-hero">
            <div class="container">
                <a href="/" class="breadcrumb">← Back to map</a>
                <h1 class="states-index-title">Every state, every month</h1>
                <p class="states-index-lede">FBI Uniform Crime Reporting data for all 50 states plus the District of Columbia. Click any state for the full breakdown — eight Part I offenses, trailing 12-month totals, and five-year trend lines.</p>
            </div>
        </section>

        <section class="section">
            <div class="container">
                <div class="states-grid">
                    {cards_html}
                </div>
            </div>
        </section>
    </main>

    <footer class="site-footer">
        <div class="container">
            <p class="footer-line">UnsolvedWatch · A Civic Tools project · Sourcing FBI Crime Data Explorer</p>
            <p class="footer-line"><a href="/">unsolvedwatch.live</a> · <a href="https://courtwatch.live">courtwatch.live</a></p>
        </div>
    </footer>
</body>
</html>
'''


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def main():
    print(f"Generating state pages → {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # First pass: compute every state's headline stats so the narrative
    # can do national-rank comparisons.
    print("Pass 1: Computing national index...")
    all_state_index_data = {}
    all_state_data = {}  # cache raw rows for pass 2

    for abbr in sorted(STATE_NAMES.keys()):
        print(f"  fetching {abbr}...", end=" ", flush=True)
        rows = fetch_state_data(abbr)
        by_offense = shape_data(rows)
        stats = compute_stats(by_offense)
        all_state_data[abbr] = (by_offense, stats)

        hom = stats.get("HOM")
        if hom and hom["last12_total"] is not None:
            rate = (hom["last12_total"] / STATE_POPS[abbr]) * 100000
            period_str = f"{MONTH_SHORT[hom['latest_month']]} {hom['latest_year']}"
            all_state_index_data[abbr] = {
                "homicide_count": hom["last12_total"],
                "homicide_rate": rate,
                "period_str": period_str,
            }
            print(f"{hom['last12_total']} hom / {rate:.1f}")
        else:
            all_state_index_data[abbr] = {
                "homicide_count": None,
                "homicide_rate": None,
                "period_str": None,
            }
            print("no data")

    # Pass 2: render each state page
    print("\nPass 2: Rendering pages...")
    for abbr in sorted(STATE_NAMES.keys()):
        by_offense, stats = all_state_data[abbr]
        html = render_state_page(abbr, stats, by_offense, all_state_index_data)

        state_dir = OUTPUT_DIR / abbr.lower()
        state_dir.mkdir(exist_ok=True)
        (state_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"  wrote {abbr.lower()}/index.html")

    # Render index page
    print("\nWriting states/index.html...")
    index_html = render_states_index(all_state_index_data)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")

    print(f"\nDone. Generated {len(STATE_NAMES)} state pages + 1 index page.")


if __name__ == "__main__":
    main()
