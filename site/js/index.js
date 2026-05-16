// /js/index.js
import { sbQuery, fmtNum, fmtPeriod } from './config.js'

const STATES_50 = [
    ['AL','Alabama'],['AK','Alaska'],['AZ','Arizona'],['AR','Arkansas'],['CA','California'],
    ['CO','Colorado'],['CT','Connecticut'],['DE','Delaware'],['FL','Florida'],['GA','Georgia'],
    ['HI','Hawaii'],['ID','Idaho'],['IL','Illinois'],['IN','Indiana'],['IA','Iowa'],
    ['KS','Kansas'],['KY','Kentucky'],['LA','Louisiana'],['ME','Maine'],['MD','Maryland'],
    ['MA','Massachusetts'],['MI','Michigan'],['MN','Minnesota'],['MS','Mississippi'],['MO','Missouri'],
    ['MT','Montana'],['NE','Nebraska'],['NV','Nevada'],['NH','New Hampshire'],['NJ','New Jersey'],
    ['NM','New Mexico'],['NY','New York'],['NC','North Carolina'],['ND','North Dakota'],['OH','Ohio'],
    ['OK','Oklahoma'],['OR','Oregon'],['PA','Pennsylvania'],['RI','Rhode Island'],['SC','South Carolina'],
    ['SD','South Dakota'],['TN','Tennessee'],['TX','Texas'],['UT','Utah'],['VT','Vermont'],
    ['VA','Virginia'],['WA','Washington'],['WV','West Virginia'],['WI','Wisconsin'],['WY','Wyoming'],
    ['DC','District of Columbia']
]

async function loadStats() {
    // Latest scrape run for FBI refresh date
    const runs = await sbQuery('scrape_runs', {
        'select': 'fbi_last_refresh_date,fbi_max_data_date,started_at',
        'status': 'eq.success',
        'order': 'started_at.desc',
        'limit': 1
    })

    // Total data points (HEAD request with count header would be cheaper, but this is fine)
    const { count: rowCount } = await fetch(`${import.meta.url.split('/js/')[0].replace('/js', '')}`, {})
        .then(() => ({ count: null }))
        .catch(() => ({ count: null }))

    // Just count states present in crime_data
    const stateRows = await sbQuery('crime_data', {
        'select': 'state_abbr',
        'jurisdiction_type': 'eq.state',
        'limit': 10000
    })
    const uniqueStates = new Set(stateRows.map(r => r.state_abbr).filter(Boolean))

    document.querySelector('[data-stat="states"]').textContent = uniqueStates.size || '51'
    document.querySelector('[data-stat="rows"]').textContent = stateRows.length >= 10000
        ? '10,000+'
        : fmtNum(stateRows.length)

    const refresh = runs[0]?.fbi_last_refresh_date
    document.querySelector('[data-stat="last_refresh"]').textContent = refresh || 'Pending'

    const footerEl = document.getElementById('footer-refresh')
    if (footerEl) {
        footerEl.textContent = refresh
            ? `FBI data last refreshed: ${refresh} · Site scraped: ${new Date(runs[0].started_at).toLocaleDateString()}`
            : 'Awaiting first scrape'
    }
}

async function loadStateGrid() {
    const grid = document.getElementById('state-grid')
    if (!grid) return

    // Query state_latest for ASS (aggravated assault) as a representative offense for the grid card
    const latest = await sbQuery('state_latest', {
        'select': 'state_abbr,period_year,period_month,offenses_count,coverage_pct',
        'offense_code': 'eq.ASS',
        'order': 'state_abbr.asc'
    })

    const byState = Object.fromEntries(latest.map(r => [r.state_abbr, r]))

    grid.innerHTML = STATES_50.map(([abbr, name]) => {
        const d = byState[abbr]
        const periodStr = d ? fmtPeriod(d.period_year, d.period_month) : '—'
        const offenses = d ? fmtNum(d.offenses_count) : '—'
        return `
            <a href="/states/${abbr.toLowerCase()}/" class="state-card">
                <div class="state-card-abbr">${abbr}</div>
                <div class="state-card-name">${name}</div>
                <div class="state-card-stat">
                    <strong>${offenses}</strong> aggravated assaults<br>
                    <span style="color: var(--ink-3); font-size: 0.75rem;">latest: ${periodStr}</span>
                </div>
            </a>
        `
    }).join('')
}

loadStats().catch(console.error)
loadStateGrid().catch(console.error)
