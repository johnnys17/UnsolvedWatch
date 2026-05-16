import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const FBI_BASE = 'https://cde.ucr.cjis.gov/LATEST/summarized'
const OFFENSES = ['HOM', 'RPE', 'ROB', 'ASS', 'BUR', 'LAR', 'MVT', 'ARS']
const FROM = '01-1985'

function getToDate(): string {
  const now = new Date()
  const m = String(now.getUTCMonth() + 1).padStart(2, '0')
  const y = now.getUTCFullYear()
  return `${m}-${y}`
}

function parsePeriod(key: string) {
  const [m, y] = key.split('-')
  return { year: parseInt(y, 10), month: parseInt(m, 10) }
}

function detectAnnualRollups(actuals: Record<string, number | null>) {
  const rollups = new Set<string>()
  const byYear = new Map<number, Record<number, number | null>>()
  for (const [k, v] of Object.entries(actuals)) {
    const { year, month } = parsePeriod(k)
    if (!byYear.has(year)) byYear.set(year, {})
    byYear.get(year)![month] = v
  }
  for (const [year, months] of byYear) {
    const dec = months[12]
    if (dec == null || dec === 0) continue
    const other = Object.entries(months).filter(([m]) => parseInt(m) !== 12).reduce((s, [, v]) => s + (v ?? 0), 0)
    if (other === 0 && dec > 0) rollups.add(`12-${year}`)
    else if (dec > other * 4 && dec > 100) rollups.add(`12-${year}`)
  }
  return rollups
}

async function fetchStateData(stateAbbr: string, offense: string, to: string) {
  const url = `${FBI_BASE}/state/${stateAbbr}/${offense}?from=${FROM}&to=${to}&type=counts`
  try {
    const res = await fetch(url, { headers: { 'Accept': 'application/json', 'User-Agent': 'UnsolvedWatch.live' } })
    if (!res.ok) { console.error(`HTTP ${res.status} for ${stateAbbr}/${offense}`); return null }
    return await res.json()
  } catch (e) { console.error(`Fetch error ${stateAbbr}/${offense}:`, e); return null }
}

function transformResponse(data: any, stateAbbr: string, offense: string) {
  const rows: any[] = []
  const stateName = Object.keys(data.offenses.actuals).find(k => k.endsWith(' Offenses') && !k.startsWith('United States'))
  if (!stateName) return rows
  const stateBase = stateName.replace(' Offenses', '')
  const oa = data.offenses.actuals[`${stateBase} Offenses`] || {}
  const ca = data.offenses.actuals[`${stateBase} Clearances`] || {}
  const orates = data.offenses.rates[`${stateBase} Offenses`] || {}
  const crates = data.offenses.rates[`${stateBase} Clearances`] || {}
  const cov = data.tooltips['Percent of Population Coverage'][stateBase] || {}
  const pop = data.populations.population[stateBase] || {}
  const pp = data.populations.participated_population[stateBase] || {}
  const rollups = detectAnnualRollups(oa)
  for (const key of Object.keys(oa)) {
    const { year, month } = parsePeriod(key)
    rows.push({
      jurisdiction_type: 'state', state_abbr: stateAbbr, ori: null, offense_code: offense,
      period_year: year, period_month: month,
      offenses_count: oa[key] ?? null, clearances_count: ca[key] ?? null,
      offenses_rate: orates[key] ?? null, clearances_rate: crates[key] ?? null,
      population: pop[key] ?? null, participated_population: pp[key] ?? null,
      coverage_pct: cov[key] ?? null, is_annual_rollup: rollups.has(key)
    })
  }
  return rows
}

Deno.serve(async (req) => {
  const supabase = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!)

  let body: any = {}
  try { const t = await req.text(); if (t && t.trim()) body = JSON.parse(t) } catch {}
  const stateFilter: string | null = body.state_filter ?? null
  const offenseFilter: string | null = body.offense_filter ?? null
  const toDate = getToDate()

  const q = supabase.from('states').select('abbr').order('abbr')
  const { data: states, error: se } = stateFilter ? await q.eq('abbr', stateFilter) : await q
  if (se) return new Response(JSON.stringify({ error: se.message }), { status: 500 })
  if (!states || states.length === 0) return new Response(JSON.stringify({ error: `No states matched '${stateFilter}'` }), { status: 400 })

  const offensesToRun = offenseFilter ? OFFENSES.filter(o => o === offenseFilter) : OFFENSES

  const { data: run } = await supabase.from('scrape_runs').insert({
    run_type: (stateFilter || offenseFilter) ? 'state' : 'full', target: stateFilter ?? null, status: 'started'
  }).select().single()

  let totalRows = 0, fbiRefresh: string | null = null, fbiMax: string | null = null
  const errors: string[] = []

  for (const state of states) {
    for (const offense of offensesToRun) {
      const data = await fetchStateData(state.abbr, offense, toDate)
      if (!data) { errors.push(`${state.abbr}/${offense}: fetch`); continue }
      if (!fbiRefresh) { fbiRefresh = data.cde_properties.last_refresh_date.UCR; fbiMax = data.cde_properties.max_data_date.UCR }
      const rows = transformResponse(data, state.abbr, offense)
      if (rows.length === 0) continue
      for (let i = 0; i < rows.length; i += 500) {
        const batch = rows.slice(i, i + 500)
        const { error } = await supabase.from('crime_data').upsert(batch, {
          onConflict: 'jurisdiction_type,state_abbr,ori,offense_code,period_year,period_month', ignoreDuplicates: false
        })
        if (error) errors.push(`${state.abbr}/${offense} ins: ${error.message}`)
        else totalRows += batch.length
      }
      await new Promise(r => setTimeout(r, 100))
    }
  }

  await supabase.from('scrape_runs').update({
    status: errors.length === 0 ? 'success' : (totalRows > 0 ? 'partial' : 'failed'),
    fbi_max_data_date: fbiMax, fbi_last_refresh_date: fbiRefresh, rows_written: totalRows,
    error_message: errors.length > 0 ? errors.slice(0, 10).join('; ') : null,
    finished_at: new Date().toISOString()
  }).eq('id', run!.id)

  return new Response(JSON.stringify({
    run_id: run!.id, rows_written: totalRows, fbi_refresh: fbiRefresh, fbi_max_date: fbiMax,
    states_scraped: states.length, offenses_scraped: offensesToRun.length,
    errors: errors.length, filter_applied: { state: stateFilter, offense: offenseFilter }
  }), { headers: { 'Content-Type': 'application/json' } })
})
