// /js/map.js — v3
// US state choropleth with explicit sizing
import { sbQuery, fmtNum, fmtPeriod } from './config.js'

const STATE_POP = {
    AL: 5108468, AK: 733406, AZ: 7431344, AR: 3067732, CA: 38965193,
    CO: 5877610, CT: 3617176, DE: 1031890, FL: 22610726, GA: 11029227,
    HI: 1435138, ID: 1964726, IL: 12549689, IN: 6862199, IA: 3207004,
    KS: 2940546, KY: 4526154, LA: 4573749, ME: 1395722, MD: 6180253,
    MA: 7001399, MI: 10037261, MN: 5737915, MS: 2939690, MO: 6196156,
    MT: 1132812, NE: 1978379, NV: 3194176, NH: 1402054, NJ: 9290841,
    NM: 2114371, NY: 19571216, NC: 10835491, ND: 783926, OH: 11785935,
    OK: 4053824, OR: 4233358, PA: 12961683, RI: 1095962, SC: 5373555,
    SD: 919318, TN: 7126489, TX: 30503301, UT: 3417734, VT: 647464,
    VA: 8715698, WA: 7812880, WV: 1770071, WI: 5910955, WY: 584057,
    DC: 678972
}

const STATE_NAMES = {
    AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California',
    CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', FL: 'Florida', GA: 'Georgia',
    HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa',
    KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland',
    MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri',
    MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey',
    NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio',
    OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina',
    SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont',
    VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming',
    DC: 'District of Columbia'
}

const FIPS_TO_ABBR = {
    '01':'AL','02':'AK','04':'AZ','05':'AR','06':'CA','08':'CO','09':'CT','10':'DE',
    '11':'DC','12':'FL','13':'GA','15':'HI','16':'ID','17':'IL','18':'IN','19':'IA',
    '20':'KS','21':'KY','22':'LA','23':'ME','24':'MD','25':'MA','26':'MI','27':'MN',
    '28':'MS','29':'MO','30':'MT','31':'NE','32':'NV','33':'NH','34':'NJ','35':'NM',
    '36':'NY','37':'NC','38':'ND','39':'OH','40':'OK','41':'OR','42':'PA','44':'RI',
    '45':'SC','46':'SD','47':'TN','48':'TX','49':'UT','50':'VT','51':'VA','53':'WA',
    '54':'WV','55':'WI','56':'WY'
}

function getColorVar(ratePer100k) {
    // Literal hex - browsers don't support CSS variables in SVG fill attributes.
    // Scale tuned to be visible against cream paper background (#f4ede0).
    if (ratePer100k == null) return '#cfc6b0'  // no-data: warmer gray
    if (ratePer100k < 2)   return '#f0b890'    // pale peach - low
    if (ratePer100k < 5)   return '#e08866'    // warm coral
    if (ratePer100k < 8)   return '#c85a3e'    // rust
    if (ratePer100k < 12)  return '#a01e26'    // brick red
    return '#6f1217'                           // deep oxblood - highest
}

export async function buildMap() {
    const container = document.getElementById('us-map')
    if (!container) return

    try {
        console.log('[map] loading dependencies...')

        const [d3Module, topojsonModule, usResp] = await Promise.all([
            import('https://cdn.jsdelivr.net/npm/d3@7/+esm'),
            import('https://cdn.jsdelivr.net/npm/topojson-client@3/+esm'),
            fetch('https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json')
        ])

        const d3 = d3Module
        const topojson = topojsonModule
        const us = await usResp.json()

        console.log('[map] dependencies loaded, fetching data...')

        // Fetch homicide data — trailing 12 months
        const now = new Date()
        const cutoffYear = now.getFullYear() - 1
        const cutoffMonth = now.getMonth() + 1

        const rows = await sbQuery('crime_data', {
            'select': 'state_abbr,period_year,period_month,offenses_count',
            'jurisdiction_type': 'eq.state',
            'offense_code': 'eq.HOM',
            'is_annual_rollup': 'eq.false',
            'or': `(period_year.gt.${cutoffYear},and(period_year.eq.${cutoffYear},period_month.gte.${cutoffMonth}))`,
            'order': 'state_abbr.asc,period_year.desc,period_month.desc'
        })

        console.log(`[map] received ${rows.length} crime data rows`)

        const byState = {}
        for (const r of rows) {
            if (r.offenses_count == null) continue
            if (!byState[r.state_abbr]) {
                byState[r.state_abbr] = { total: 0, count: 0, latestYear: r.period_year, latestMonth: r.period_month }
            }
            const s = byState[r.state_abbr]
            if (s.count < 12) {
                s.total += Number(r.offenses_count)
                s.count++
            }
        }

        for (const abbr of Object.keys(byState)) {
            const pop = STATE_POP[abbr]
            if (pop) {
                byState[abbr].ratePer100k = (byState[abbr].total / pop) * 100000
            }
        }

        // Build SVG with explicit dimensions
        const width = 975
        const height = 610

        const states = topojson.feature(us, us.objects.states)

        // us-atlas serves raw geographic coordinates (lat/long).
        // geoAlbersUsa is the standard projection for US choropleth maps —
        // it correctly handles the continental US plus insets for AK/HI.
        const projection = d3.geoAlbersUsa().fitSize([width, height], states)
        const path = d3.geoPath(projection)

        // Clear container completely
        container.innerHTML = ''

        // Create SVG element directly (more reliable than d3 select on empty container)
        const svg = d3.select(container)
            .append('svg')
            .attr('class', 'map-canvas')
            .attr('viewBox', `0 0 ${width} ${height}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .attr('width', '100%')
            .attr('height', '100%')

        // Draw states
        svg.append('g')
            .selectAll('path')
            .data(states.features)
            .join('path')
            .attr('class', 'state-path')
            .attr('d', path)
            .attr('fill', d => {
                const fipsKey = String(d.id).padStart(2, '0')
                const abbr = FIPS_TO_ABBR[fipsKey]
                const data = abbr && byState[abbr]
                return getColorVar(data?.ratePer100k)
            })
            .on('mouseenter', function(event, d) {
                const fipsKey = String(d.id).padStart(2, '0')
                const abbr = FIPS_TO_ABBR[fipsKey]
                if (!abbr) return
                updateInfo(abbr, byState[abbr])
                d3.select(this).classed('is-selected', true)
            })
            .on('mouseleave', function() {
                d3.select(this).classed('is-selected', false)
            })
            .on('click', function(event, d) {
                const fipsKey = String(d.id).padStart(2, '0')
                const abbr = FIPS_TO_ABBR[fipsKey]
                if (!abbr) return
                window.location.href = `/states/${abbr.toLowerCase()}/`
            })
            .append('title')  // Native browser tooltip as fallback
            .text(d => {
                const fipsKey = String(d.id).padStart(2, '0')
                const abbr = FIPS_TO_ABBR[fipsKey]
                if (!abbr) return ''
                const data = byState[abbr]
                if (!data) return `${STATE_NAMES[abbr]} — no recent data`
                return `${STATE_NAMES[abbr]}: ${data.total} homicides (${data.ratePer100k.toFixed(1)} per 100k)`
            })

        console.log('[map] rendered successfully')

    } catch (err) {
        console.error('[map] failed:', err)
        container.innerHTML = `<div class="loading" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 1rem; padding: 2rem; text-align: center;">
            <span>Map failed to load.</span>
            <span style="font-size: 0.75rem; opacity: 0.7;">${err.message || 'Unknown error'}</span>
            <a href="/states/" style="color: var(--red); text-decoration: underline; font-weight: 600;">View state list →</a>
        </div>`
    }
}

function updateInfo(abbr, data) {
    const info = document.getElementById('map-info')
    if (!info) return

    const name = STATE_NAMES[abbr]
    const pop = STATE_POP[abbr]

    if (!data || data.count === 0) {
        info.innerHTML = `
            <div class="map-info-eyebrow">${abbr} · Pop. ${fmtNum(pop)}</div>
            <div class="map-info-title">${name}</div>
            <div class="state-card-nodata" style="margin-bottom: 1rem;">No recent homicide data reported</div>
            <p class="map-info-body">
                Either the state has not yet submitted NIBRS data to the FBI for the trailing 12-month window, or the FBI has not yet published it.
            </p>
            <a href="/states/${abbr.toLowerCase()}/" class="map-info-link">View ${name} →</a>
        `
        return
    }

    const periodStr = fmtPeriod(data.latestYear, data.latestMonth)
    const rate = data.ratePer100k

    info.innerHTML = `
        <div class="map-info-eyebrow">${abbr} · Pop. ${fmtNum(pop)}</div>
        <div class="map-info-title">${name}</div>

        <div class="map-info-stat">
            <div class="map-info-stat-value">${fmtNum(data.total)}</div>
            <div class="map-info-stat-label">Homicides · trailing 12 months</div>
        </div>

        <div class="map-info-stat">
            <div class="map-info-stat-value">${rate.toFixed(1)}</div>
            <div class="map-info-stat-label">Per 100,000 residents</div>
        </div>

        <div class="map-info-meta">
            Through ${periodStr} · ${data.count} months of records
        </div>
        <a href="/states/${abbr.toLowerCase()}/" class="map-info-link">View ${name} →</a>
    `
}

// Auto-init
buildMap().catch(console.error)
