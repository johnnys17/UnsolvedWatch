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

Optional:
    DEBUG=0             silence per-state diagnostic output

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
from collections import defaultdict, Counter

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Set SUPABASE_URL and SUPABASE_ANON_KEY environment variables.", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "site" / "states"

DEBUG = os.environ.get("DEBUG", "1") != "0"

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

# Colors for the 8-offense overlay chart. Selected to coexist on cream paper,
# desaturated enough that no single line shouts over the others, but with
# enough hue separation to identify each at a glance.
OFFENSE_COLORS = {
    "HOM": "#0a1f3d",  # navy ink — homicide gets the anchor color
    "RPE": "#b8222d",  # federal red
    "ROB": "#a37c2c",  # gold
    "ASS": "#5e6b3a",  # dusty olive
    "BUR": "#4a5a6b",  # slate
    "LAR": "#8a5a48",  # terra cotta
    "MVT": "#6b4a6b",  # plum
    "ARS": "#9c6a6a",  # dusty rose
}

OFFENSE_ALIASES = {
    "HOM": "HOM", "MUR": "HOM", "MURDER": "HOM", "HOMICIDE": "HOM",
    "RPE": "RPE", "RAP": "RPE", "RAPE": "RPE",
    "ROB": "ROB", "ROBBERY": "ROB",
    "ASS": "ASS", "AGG": "ASS", "ASSAULT": "ASS", "AGGRAVATED_ASSAULT": "ASS",
    "BUR": "BUR", "BURG": "BUR", "BURGLARY": "BUR",
    "LAR": "LAR", "LARCENY": "LAR", "THEFT": "LAR",
    "MVT": "MVT", "MV": "MVT", "MOTOR_VEHICLE_THEFT": "MVT",
    "ARS": "ARS", "ARSON": "ARS",
}


def normalize_offense_code(raw):
    if raw is None:
        return None
    key = str(raw).strip().upper()
    return OFFENSE_ALIASES.get(key)


MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
MONTH_SHORT = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# -------------------------------------------------------------------------
# Supabase fetch helper
# -------------------------------------------------------------------------

def sb_query(path, params=None):
    if params is None:
        params = {}
    qs = urllib.parse.urlencode(params)
    url = f"{SUPABASE_URL}/rest/v1/{path}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
        "Range-Unit": "items",
        "Range": "0-9999",
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


def shape_data(rows, debug_label=None):
    by_offense = defaultdict(list)
    raw_codes_seen = Counter()
    unmapped_codes = Counter()
    null_count_rows = 0

    for r in rows:
        raw_code = r.get("offense_code")
        raw_codes_seen[str(raw_code)] += 1

        code = normalize_offense_code(raw_code)
        if code is None:
            unmapped_codes[str(raw_code)] += 1
            continue

        oc = r.get("offenses_count")
        if oc is None:
            null_count_rows += 1
            continue

        try:
            count = int(oc)
        except (TypeError, ValueError):
            null_count_rows += 1
            continue

        by_offense[code].append({
            "year": r["period_year"],
            "month": r["period_month"],
            "count": count,
            "clearances": r.get("clearances_count"),
        })

    for code in by_offense:
        by_offense[code].sort(key=lambda x: (x["year"], x["month"]))

    if DEBUG and debug_label:
        codes_str = ", ".join(f"{c}:{n}" for c, n in raw_codes_seen.most_common(12))
        print(f"  [{debug_label}] raw codes: {codes_str}")
        if unmapped_codes:
            print(f"  [{debug_label}] UNMAPPED codes (dropped): {dict(unmapped_codes)}")
        if null_count_rows:
            print(f"  [{debug_label}] dropped {null_count_rows} rows with null/bad offenses_count")
        bucketed = {k: len(v) for k, v in by_offense.items()}
        print(f"  [{debug_label}] bucketed: {bucketed}")

    return by_offense


def compute_stats(by_offense):
    stats = {}
    for code, label in OFFENSES:
        series = by_offense.get(code, [])
        if not series:
            stats[code] = None
            continue

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


def build_overlay_chart(by_offense, width=960, height=440):
    """
    Indexed-to-100 line chart showing all 8 offenses on one set of axes.
    Each line starts at 100 at the earliest comparable month and rises/falls
    from there as a percentage of its own baseline. This makes Larceny and
    Homicide directly comparable despite a 100x volume difference.

    Trailing 12-month rolling totals are used (not raw monthly counts) to
    smooth out seasonality and make the trend lines readable.

    End labels are pulled into a fixed column on the right, stacked
    vertically with guaranteed spacing, and connected to their data
    endpoints via L-shaped leader lines.
    """
    # Padding for axes + right-side label column
    pad_left = 56
    pad_right = 210   # room for the label column + leader lines
    pad_top = 28
    pad_bottom = 36
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    # Build trailing-12-month rolling totals for each offense.
    # Result: list of (year, month, total) tuples, one per month.
    rolling_series = {}
    for code, label in OFFENSES:
        series = by_offense.get(code, [])
        if len(series) < 13:
            continue
        # 12-month rolling sum, starting at month 12
        rolling = []
        for i in range(11, len(series)):
            window = series[i - 11 : i + 1]
            total = sum(p["count"] for p in window)
            rolling.append((series[i]["year"], series[i]["month"], total))
        if rolling and rolling[0][2] > 0:
            rolling_series[code] = rolling

    if not rolling_series:
        return ('<div class="overlay-chart-empty">Not enough monthly data to build the '
                'trend overlay (need at least 13 months per offense).</div>')

    # Find the common time window — earliest month shared by all offenses,
    # latest month shared by all offenses. Align everything to that.
    starts = [s[0] for s in rolling_series.values()]
    ends = [s[-1] for s in rolling_series.values()]

    def ym_to_idx(y, m):
        return y * 12 + (m - 1)

    common_start = max(ym_to_idx(s[0], s[1]) for s in starts)
    common_end = min(ym_to_idx(e[0], e[1]) for e in ends)
    if common_end <= common_start:
        return '<div class="overlay-chart-empty">Insufficient overlapping data across offenses.</div>'

    n_months = common_end - common_start + 1

    # Index each series so its value at common_start = 100.
    indexed = {}
    for code, series in rolling_series.items():
        baseline = None
        for y, m, total in series:
            if ym_to_idx(y, m) == common_start:
                baseline = total
                break
        if not baseline or baseline <= 0:
            continue
        line = []
        for y, m, total in series:
            i = ym_to_idx(y, m)
            if common_start <= i <= common_end:
                line.append((i - common_start, (total / baseline) * 100))
        if line:
            indexed[code] = line

    if not indexed:
        return '<div class="overlay-chart-empty">Could not build indexed series.</div>'

    # Y-axis scale
    all_vals = [v for line in indexed.values() for _, v in line]
    y_min = min(50, min(all_vals) - 5)
    y_max = max(150, max(all_vals) + 5)
    y_range = y_max - y_min

    def to_x(i):
        return pad_left + (i / max(n_months - 1, 1)) * plot_w

    def to_y(v):
        return pad_top + plot_h - ((v - y_min) / y_range) * plot_h

    # Y-axis gridlines at nice round numbers.
    # Step size adapts so we never have more than ~12 gridlines visible.
    if y_range <= 120:
        grid_step = 10
    elif y_range <= 250:
        grid_step = 25
    elif y_range <= 500:
        grid_step = 50
    elif y_range <= 1000:
        grid_step = 100
    else:
        grid_step = 200

    grid_vals = []
    v = (int(y_min / grid_step) + 1) * grid_step
    while v <= y_max:
        grid_vals.append(v)
        v += grid_step
    # Always include 100 as the baseline reference
    if 100 not in grid_vals and y_min <= 100 <= y_max:
        grid_vals.append(100)
        grid_vals.sort()

    # X-axis tick marks — first month, last month, and ~3 in between
    x_ticks = []
    n_ticks = 5
    for k in range(n_ticks):
        i = int(k * (n_months - 1) / (n_ticks - 1))
        ym_idx = common_start + i
        year = ym_idx // 12
        month = (ym_idx % 12) + 1
        x_ticks.append((i, MONTH_SHORT[month], year))

    # Build SVG pieces
    svg_parts = []

    # Background grid
    svg_parts.append(f'<rect x="{pad_left}" y="{pad_top}" width="{plot_w}" height="{plot_h}" '
                     f'fill="var(--paper, #f4ede0)" stroke="none" />')

    # Horizontal gridlines
    for v in grid_vals:
        y = to_y(v)
        is_baseline = (v == 100)
        stroke = "#0a1f3d" if is_baseline else "#d4c8b0"
        dash = '' if is_baseline else 'stroke-dasharray="2,3"'
        width_attr = '1' if is_baseline else '0.5'
        opacity = '0.4' if is_baseline else '0.6'
        svg_parts.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" y2="{y:.1f}" '
            f'stroke="{stroke}" stroke-width="{width_attr}" opacity="{opacity}" {dash} />'
        )
        svg_parts.append(
            f'<text x="{pad_left - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'class="overlay-axis-label">{v}</text>'
        )

    # Vertical gridlines: one per month (faint), with stronger ones at year boundaries.
    x_tick_indices = set(t[0] for t in x_ticks)
    for i in range(n_months):
        x = to_x(i)
        if i in x_tick_indices:
            # Year-boundary line (matches the date labels) — slightly stronger
            stroke = "#b8a888"
            width_attr = "0.6"
            opacity = "0.55"
        else:
            # Monthly tick — subtle texture
            stroke = "#c8bca0"
            width_attr = "0.4"
            opacity = "0.28"
        svg_parts.append(
            f'<line x1="{x:.1f}" y1="{pad_top}" x2="{x:.1f}" y2="{pad_top + plot_h}" '
            f'stroke="{stroke}" stroke-width="{width_attr}" opacity="{opacity}" />'
        )

    # X-axis tick labels
    for i, mon, yr in x_ticks:
        x = to_x(i)
        svg_parts.append(
            f'<text x="{x:.1f}" y="{pad_top + plot_h + 20}" text-anchor="middle" '
            f'class="overlay-axis-label">{mon} {str(yr)[-2:]}</text>'
        )

    # Lines + endpoint dots (drawn in order so HOM, RPE land on top)
    sort_order = ["LAR", "BUR", "ARS", "MVT", "ASS", "ROB", "RPE", "HOM"]
    endpoint_data = []  # (orig_y, endpoint_x, color, name, value, code)
    # For JS interactivity: capture each offense's monthly data points
    series_for_js = {}

    for code in sort_order:
        if code not in indexed:
            continue
        line = indexed[code]
        color = OFFENSE_COLORS.get(code, "#666")
        coords = [f"{to_x(i):.1f},{to_y(v):.1f}" for i, v in line]
        path_d = "M " + " L ".join(coords)
        is_anchor = code in ("HOM", "RPE")
        stroke_w = 2.0 if is_anchor else 1.4
        opacity = 1.0 if is_anchor else 0.85
        svg_parts.append(
            f'<path d="{path_d}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_w}" opacity="{opacity}" '
            f'stroke-linejoin="round" stroke-linecap="round" />'
        )
        last_i, last_v = line[-1]
        ex = to_x(last_i)
        ey = to_y(last_v)
        endpoint_data.append((ey, ex, color, OFFENSE_NAMES[code], last_v, code))
        # Endpoint dot directly on the data
        svg_parts.append(
            f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3.5" fill="{color}" '
            f'data-offense="{code}" class="overlay-endpoint-dot" />'
        )
        # Capture series data for hover JS: x position + value at each month
        series_for_js[code] = {
            "name": OFFENSE_NAMES[code],
            "color": color,
            "points": [{"i": i, "x": round(to_x(i), 1), "y": round(to_y(v), 1), "v": round(v, 1)} for i, v in line],
        }

    # ----------------------------------------------------------------
    # Leader-line label column on the right
    # ----------------------------------------------------------------
    endpoint_data.sort(key=lambda x: x[0])

    label_col_x = pad_left + plot_w + 36
    leader_bend_x = pad_left + plot_w + 18
    label_row_height = 22
    label_block_height = label_row_height * len(endpoint_data)

    if endpoint_data:
        avg_y = sum(e[0] for e in endpoint_data) / len(endpoint_data)
        first_label_y = avg_y - (label_block_height / 2) + (label_row_height / 2)
        min_first_y = pad_top + 8
        max_first_y = pad_top + plot_h - label_block_height + (label_row_height / 2)
        first_label_y = max(min_first_y, min(first_label_y, max_first_y))
    else:
        first_label_y = pad_top

    # Render each leader line + label.
    # Each label gets data-offense and a child <tspan class="overlay-label-value">
    # so JS can update the value on hover without touching the name.
    for slot_idx, (orig_y, ex, color, name, val, code) in enumerate(endpoint_data):
        label_y = first_label_y + slot_idx * label_row_height

        leader_start_x = ex + 4
        leader_end_x = label_col_x - 6
        svg_parts.append(
            f'<line x1="{leader_start_x:.1f}" y1="{orig_y:.1f}" '
            f'x2="{leader_end_x:.1f}" y2="{label_y:.1f}" '
            f'stroke="{color}" stroke-width="0.8" opacity="0.5" />'
        )

        svg_parts.append(
            f'<circle cx="{label_col_x - 4:.1f}" cy="{label_y:.1f}" r="2" fill="{color}" />'
        )

        svg_parts.append(
            f'<text x="{label_col_x:.1f}" y="{label_y + 4:.1f}" class="overlay-end-label" '
            f'fill="{color}" data-offense="{code}">'
            f'{name}'
            f'<tspan dx="6" class="overlay-end-value" fill="{color}" '
            f'data-offense-value="{code}">{val:.0f}</tspan>'
            f'</text>'
        )

    # ----------------------------------------------------------------
    # Hover guide line + hit area (rendered last so they sit on top)
    # ----------------------------------------------------------------
    # Vertical guide line — hidden until JS shows it
    svg_parts.append(
        f'<line id="overlay-hover-guide" x1="0" y1="{pad_top}" x2="0" y2="{pad_top + plot_h}" '
        f'stroke="#0a1f3d" stroke-width="0.8" opacity="0" stroke-dasharray="3,3" '
        f'pointer-events="none" />'
    )
    # Hover label above the guide
    svg_parts.append(
        f'<text id="overlay-hover-month" x="0" y="{pad_top - 8}" text-anchor="middle" '
        f'class="overlay-hover-month-label" opacity="0" pointer-events="none"></text>'
    )
    # Invisible hit target covering the whole plot area
    svg_parts.append(
        f'<rect id="overlay-hit-target" x="{pad_left}" y="{pad_top}" '
        f'width="{plot_w}" height="{plot_h}" fill="transparent" '
        f'style="cursor: crosshair;" />'
    )

    svg = (
        f'<svg class="overlay-chart" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Five-year trend lines for all 8 FBI Part I offenses, '
        f'indexed to 100 at the start of the window. Hover to see values for a specific month.">'
        + "".join(svg_parts)
        + '</svg>'
    )

    # Build the JS data payload
    # n_months total, each with year/month label + per-offense value
    month_labels = []
    for i in range(n_months):
        ym_idx = common_start + i
        year = ym_idx // 12
        month = (ym_idx % 12) + 1
        month_labels.append(f"{MONTH_SHORT[month]} {year}")

    chart_data = {
        "padLeft": pad_left,
        "padRight": pad_right,
        "padTop": pad_top,
        "padBottom": pad_bottom,
        "plotW": plot_w,
        "plotH": plot_h,
        "width": width,
        "height": height,
        "nMonths": n_months,
        "monthLabels": month_labels,
        "series": series_for_js,
    }

    # Embed chart data as JSON so the page-level JS can read it
    data_blob = f'<script type="application/json" id="overlay-chart-data">{json.dumps(chart_data)}</script>'

    return svg + data_blob


# -------------------------------------------------------------------------
# Page templates
# -------------------------------------------------------------------------

def render_state_page(abbr, stats, by_offense, all_state_index_data):
    name = STATE_NAMES[abbr]
    pop = STATE_POPS[abbr]

    abbrs_sorted = sorted(STATE_NAMES.keys())
    idx = abbrs_sorted.index(abbr)
    prev_abbr = abbrs_sorted[idx - 1] if idx > 0 else abbrs_sorted[-1]
    next_abbr = abbrs_sorted[idx + 1] if idx < len(abbrs_sorted) - 1 else abbrs_sorted[0]

    hom = stats.get("HOM")
    if hom and hom.get("last12_total") is not None:
        period_str = f"{MONTH_NAMES[hom['latest_month']]} {hom['latest_year']}"
        has_data = True
    else:
        period_str = "—"
        has_data = False

    narrative = build_narrative(abbr, name, pop, stats, by_offense, all_state_index_data)
    overlay_svg = build_overlay_chart(by_offense)

    # Offense table rows
    offense_rows = []
    for code, label in OFFENSES:
        st = stats.get(code)
        if not st or st.get("last12_total") is None:
            offense_rows.append(f'''
            <tr class="offense-row offense-row--nodata">
                <td class="offense-name">
                    <span class="offense-swatch" style="background:{OFFENSE_COLORS.get(code, '#999')}"></span>
                    {label}
                </td>
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
            <td class="offense-name">
                <span class="offense-swatch" style="background:{OFFENSE_COLORS.get(code, '#999')}"></span>
                {label}
            </td>
            <td class="offense-count">{fmt_num(st["last12_total"])}</td>
            <td class="offense-rate">{fmt_rate(rate)}</td>
            <td class="offense-yoy offense-yoy--{yoy_cls}">{fmt_pct_change(st["yoy_pct"])}</td>
            <td class="offense-spark">{spark_svg}</td>
        </tr>''')

    offense_table = "".join(offense_rows)

    page_title = f"{name} crime data — UnsolvedWatch"
    if has_data and hom:
        hom_total = hom["last12_total"]
        hom_rate = (hom_total / pop) * 100000
        page_desc = (
            f"FBI Uniform Crime Reporting data for {name}: "
            f"{fmt_num(hom_total)} homicides reported in the trailing 12 months "
            f"({fmt_rate(hom_rate)} per 100,000 residents)."
        )
    else:
        page_desc = f"FBI Uniform Crime Reporting data for {name}."

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
        <section class="state-hero state-hero--simple">
            <div class="container">
                <a href="/" class="breadcrumb">← Back to map</a>
                <div class="state-eyebrow">State of <span class="abbr-tag">{abbr}</span> · Pop. {fmt_num(pop)}</div>
                <h1 class="state-name">{name}</h1>
                <p class="state-dateline">Crime data through {period_str} · trailing 12 months</p>
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
                    <h2 class="section-title">Five-year overlay</h2>
                    <span class="section-meta">All offenses indexed to 100 at the start of the window</span>
                </div>
                <p class="overlay-explainer">Each offense is rescaled so it starts at 100 five years ago. A line above 100 means more offenses reported now than then; below 100 means fewer. Trailing 12-month totals are used to smooth out seasonality. Hover the chart to inspect any month.</p>
                <div class="overlay-chart-wrap" id="overlay-chart-wrap">
                    {overlay_svg}
                    <div id="overlay-tooltip" class="overlay-tooltip" aria-hidden="true"></div>
                </div>
            </div>
        </section>

        <section class="section section-paper-darker">
            <div class="container">
                <div class="section-header">
                    <h2 class="section-title">What this data says</h2>
                </div>
                <div class="narrative">
                    {narrative}
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

    <script>
    (function() {{
        var dataScript = document.getElementById('overlay-chart-data');
        if (!dataScript) return;
        var data;
        try {{ data = JSON.parse(dataScript.textContent); }} catch (e) {{ return; }}

        var wrap = document.getElementById('overlay-chart-wrap');
        var svg = wrap && wrap.querySelector('svg.overlay-chart');
        var hitTarget = document.getElementById('overlay-hit-target');
        var guide = document.getElementById('overlay-hover-guide');
        var hoverMonth = document.getElementById('overlay-hover-month');
        var tooltip = document.getElementById('overlay-tooltip');
        if (!svg || !hitTarget || !tooltip) return;

        // Capture the "latest" values so we can restore them on mouseout
        var latestValues = {{}};
        Object.keys(data.series).forEach(function(code) {{
            var pts = data.series[code].points;
            latestValues[code] = pts[pts.length - 1].v;
        }});

        // Build tooltip rows once. Order by current value descending.
        var sortedCodes = Object.keys(data.series).sort(function(a, b) {{
            return latestValues[b] - latestValues[a];
        }});
        tooltip.innerHTML = sortedCodes.map(function(code) {{
            var s = data.series[code];
            return '<div class="overlay-tooltip-row" data-tt-row="' + code + '">' +
                   '<span class="overlay-tooltip-swatch" style="background:' + s.color + '"></span>' +
                   '<span class="overlay-tooltip-name">' + s.name + '</span>' +
                   '<span class="overlay-tooltip-value" data-tt-value="' + code + '">' +
                   Math.round(latestValues[code]) + '</span>' +
                   '</div>';
        }}).join('');

        function getSvgPoint(evt) {{
            var pt = svg.createSVGPoint();
            pt.x = evt.clientX;
            pt.y = evt.clientY;
            return pt.matrixTransform(svg.getScreenCTM().inverse());
        }}

        function findNearestMonth(svgX) {{
            var rel = (svgX - data.padLeft) / data.plotW;
            var idx = Math.round(rel * (data.nMonths - 1));
            return Math.max(0, Math.min(data.nMonths - 1, idx));
        }}

        function updateForMonth(monthIdx, clientX, clientY) {{
            var label = data.monthLabels[monthIdx];
            var xAtMonth = data.padLeft + (monthIdx / (data.nMonths - 1)) * data.plotW;

            guide.setAttribute('x1', xAtMonth);
            guide.setAttribute('x2', xAtMonth);
            guide.setAttribute('opacity', '0.4');

            hoverMonth.setAttribute('x', xAtMonth);
            hoverMonth.textContent = label;
            hoverMonth.setAttribute('opacity', '0.85');

            Object.keys(data.series).forEach(function(code) {{
                var pts = data.series[code].points;
                var pt = pts[monthIdx];
                if (!pt) return;
                var valEl = svg.querySelector('[data-offense-value="' + code + '"]');
                if (valEl) valEl.textContent = Math.round(pt.v);
                var ttValEl = tooltip.querySelector('[data-tt-value="' + code + '"]');
                if (ttValEl) ttValEl.textContent = Math.round(pt.v);
            }});

            var codes = Object.keys(data.series);
            codes.sort(function(a, b) {{
                return data.series[b].points[monthIdx].v - data.series[a].points[monthIdx].v;
            }});
            codes.forEach(function(code, i) {{
                var row = tooltip.querySelector('[data-tt-row="' + code + '"]');
                if (row) row.style.order = i;
            }});

            var wrapRect = wrap.getBoundingClientRect();
            var tooltipW = tooltip.offsetWidth || 180;
            var tooltipH = tooltip.offsetHeight || 200;
            var localX = clientX - wrapRect.left;
            var localY = clientY - wrapRect.top;
            var ttX = localX + 16;
            var ttY = localY - tooltipH / 2;
            if (ttX + tooltipW > wrapRect.width - 4) {{
                ttX = localX - tooltipW - 16;
            }}
            ttY = Math.max(4, Math.min(wrapRect.height - tooltipH - 4, ttY));
            tooltip.style.left = ttX + 'px';
            tooltip.style.top = ttY + 'px';
            tooltip.classList.add('is-visible');
        }}

        function resetToLatest() {{
            guide.setAttribute('opacity', '0');
            hoverMonth.setAttribute('opacity', '0');
            tooltip.classList.remove('is-visible');
            Object.keys(data.series).forEach(function(code) {{
                var valEl = svg.querySelector('[data-offense-value="' + code + '"]');
                if (valEl) valEl.textContent = Math.round(latestValues[code]);
            }});
        }}

        hitTarget.addEventListener('mousemove', function(evt) {{
            var pt = getSvgPoint(evt);
            var monthIdx = findNearestMonth(pt.x);
            updateForMonth(monthIdx, evt.clientX, evt.clientY);
        }});

        hitTarget.addEventListener('mouseleave', resetToLatest);

        hitTarget.addEventListener('touchmove', function(evt) {{
            if (!evt.touches.length) return;
            evt.preventDefault();
            var touch = evt.touches[0];
            var pt = getSvgPoint(touch);
            var monthIdx = findNearestMonth(pt.x);
            updateForMonth(monthIdx, touch.clientX, touch.clientY);
        }}, {{passive: false}});
    }})();
    </script>
</body>
</html>
'''


def build_narrative(abbr, name, pop, stats, by_offense, all_state_index_data):
    paragraphs = []

    hom = stats.get("HOM")
    if hom and hom.get("last12_total") is not None:
        rate = (hom["last12_total"] / pop) * 100000

        yoy = hom.get("yoy_pct")
        if yoy is None:
            yoy_phrase = "Year-over-year comparison is not yet available."
        elif yoy > 5:
            yoy_phrase = f"That's a <strong>{fmt_pct_change(yoy)} increase</strong> compared to the prior 12-month window."
        elif yoy < -5:
            yoy_phrase = f"That's a <strong>{abs(yoy):.1f}% decrease</strong> compared to the prior 12-month window."
        else:
            yoy_phrase = f"That's roughly flat ({fmt_pct_change(yoy)}) compared to the prior 12-month window."

        paragraphs.append(
            f"<p>{name} reported <strong>{fmt_num(hom['last12_total'])} homicides</strong> in the trailing "
            f"12 months — a rate of <strong>{fmt_rate(rate)} per 100,000 residents</strong>. "
            f"{yoy_phrase}</p>"
        )

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
                    f"<p>{name}'s rate sits {relative}. It ranks <strong>#{rank} of {total_ranked}</strong> states "
                    f"by homicides per capita (1 = highest). The national median across all states is "
                    f"{fmt_rate(median_rate)} per 100,000.</p>"
                )
    else:
        paragraphs.append(
            f"<p>{name} has not submitted homicide data to the FBI sufficient to compute a complete "
            f"trailing 12-month window. When states or their largest police departments under-report, "
            f"the national picture has blind spots — and that itself is the story this site tracks.</p>"
        )

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
        bits = [f"<strong>{label} is {direction} {abs(p):.1f}%</strong>" for label, direction, p in notable[:3]]
        paragraphs.append(
            f"<p>Other notable year-over-year shifts: " + ", ".join(bits) + ".</p>"
        )

    paragraphs.append(
        f"<p class='narrative-meta'>All figures are pulled directly from the FBI's Crime Data Explorer, "
        f"which aggregates monthly submissions from local law enforcement agencies. Numbers reflect "
        f"offenses reported to police — not all crime, and not crime that was solved. Rate calculations "
        f"use 2024 U.S. Census Bureau population estimates.</p>"
    )

    return "\n".join(paragraphs)


def render_states_index(all_state_index_data):
    sorted_states = sorted(STATE_NAMES.keys(), key=lambda a: STATE_NAMES[a])

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
            stat_line = '<span class="card-nodata">No recent data reported to FBI</span>'
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
    print(f"Generating state pages -> {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nPass 1: Computing national index...")
    all_state_index_data = {}
    all_state_data = {}

    states_with_data = 0
    states_without = []

    for abbr in sorted(STATE_NAMES.keys()):
        print(f"\n  {abbr}: fetching...", flush=True)
        rows = fetch_state_data(abbr)
        print(f"  [{abbr}] fetched {len(rows)} rows")

        by_offense = shape_data(rows, debug_label=abbr)
        stats = compute_stats(by_offense)
        all_state_data[abbr] = (by_offense, stats)

        hom = stats.get("HOM")
        if hom and hom.get("last12_total") is not None:
            rate = (hom["last12_total"] / STATE_POPS[abbr]) * 100000
            period_str = f"{MONTH_SHORT[hom['latest_month']]} {hom['latest_year']}"
            all_state_index_data[abbr] = {
                "homicide_count": hom["last12_total"],
                "homicide_rate": rate,
                "period_str": period_str,
            }
            states_with_data += 1
            print(f"  [{abbr}] OK -> {hom['last12_total']} homicides / {rate:.1f} per 100k / thru {period_str}")
        else:
            all_state_index_data[abbr] = {
                "homicide_count": None,
                "homicide_rate": None,
                "period_str": None,
            }
            states_without.append(abbr)
            print(f"  [{abbr}] -- no HOM data")

    print(f"\n  Summary: {states_with_data}/{len(STATE_NAMES)} states have homicide data")
    if states_without:
        print(f"  Missing: {', '.join(states_without)}")

    print("\nPass 2: Rendering pages...")
    for abbr in sorted(STATE_NAMES.keys()):
        by_offense, stats = all_state_data[abbr]
        html = render_state_page(abbr, stats, by_offense, all_state_index_data)

        state_dir = OUTPUT_DIR / abbr.lower()
        state_dir.mkdir(exist_ok=True)
        (state_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"  wrote states/{abbr.lower()}/index.html")

    print("\nWriting states/index.html...")
    index_html = render_states_index(all_state_index_data)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")

    print(f"\nDone. Generated {len(STATE_NAMES)} state pages + 1 index page.")
    print(f"({states_with_data} with data, {len(states_without)} without)")


if __name__ == "__main__":
    main()
