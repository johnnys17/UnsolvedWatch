// /js/index.js
import { sbQuery, sbCount, fmtNum, fmtPeriod } from './config.js'

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
    const runs = await sbQuery('scrape_runs', {
        'select': 'fbi_last_refresh_date,fbi_max_data_date,started_at',
        'status': 'eq.success',
        'order': 'started_at.desc',
        'limit': '1'
    })

    const stateCount = await sbCount('states')
    const totalRows = await sbCount('crime_data', {
        'jurisdiction_type': 'eq.state'
    })

    document.querySelector('[data-stat="states"]').textContent = stateCount ?? 51
    document.querySelector('[data-stat="rows"]').textContent = totalRows ? fmtNum(totalRows) : '—'

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

    const now = new Date()
    const cutoffYear = now.getFullYear() - (now.getMonth() < 2 ? 2 : 1)
    const cutoffMonth = now.getMonth() < 2 ? now.getMonth() + 11 : now.getMonth() - 1

    const rows = await sbQuery('crime_data', {
        'select': 'state_abbr,period_year,period_month,offenses_count',
        'jurisdiction_type': 'eq.state',
        'offense_code': 'eq.HOM',
        'is_annual_rollup': 'eq.false',
        'or': `(period_year.gt.${cutoffYear},and(period_year.eq.${cutoffYear},period_month.gte.${cutoffMonth}))`,
        'order': 'state_abbr.asc,period_year.desc,period_month.desc'
    })

    const byState = {}
    for (const r of rows) {
        if (r.offenses_count == null) continue
        if (!byState[r.state_abbr]) {
            byState[r.state_abbr] = { total: 0, latestYear: r.period_year, latestMonth: r.period_month, count: 0 }
        }
        const s = byState[r.state_abbr]
        if (s.count < 12) {
            s.total += Number(r.offenses_count)
            s.count++
        }
    }

    grid.innerHTML = STATES_50.map(([abbr, name]) => {
        const d = byState[abbr]
        const hasData = d && d.count > 0
        const periodStr = hasData ? fmtPeriod(d.latestYear, d.latestMonth) : '—'
        const total = hasData ? fmtNum(d.total) : '—'
        const noDataNote = hasData
            ? ''
            : '<span style="color: var(--accent-2); font-size: 0.7rem; font-style: italic;">no recent data reported</span>'
        return `
            <a href="/states/${abbr.toLowerCase()}/" class="state-card">
                <div class="state-card-abbr">${abbr}</div>
                <div class="state-card-name">${name}</div>
                <div class="state-card-stat">
                    ${hasData ? `<strong>${total}</strong> homicides<br><span style="color: var(--ink-3); font-size: 0.75rem;">trailing 12 months · thru ${periodStr}</span>` : noDataNote}
                </div>
            </a>
        `
    }).join('')
}

loadStats().catch(console.error)
loadStateGrid().catch(console.error)

