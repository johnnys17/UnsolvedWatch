// supabase/functions/heartbeat/index.ts
// Lightweight daily check: hits one FBI endpoint, compares last_refresh_date
// to most recent successful run. If FBI refreshed since then, trigger full scrape.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

Deno.serve(async (_req) => {
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  )

  // Check FBI's current refresh date with a single lightweight request
  const probeUrl = 'https://cde.ucr.cjis.gov/LATEST/summarized/state/FL/MUR?from=01-2026&to=12-2026&type=counts'
  let fbiRefresh: string | null = null
  try {
    const res = await fetch(probeUrl, {
      headers: { 'User-Agent': 'UnsolvedWatch.live heartbeat' }
    })
    const data = await res.json()
    fbiRefresh = data?.cde_properties?.last_refresh_date?.UCR ?? null
  } catch (e) {
    await supabase.from('scrape_runs').insert({
      run_type: 'heartbeat',
      status: 'failed',
      error_message: `Probe failed: ${e}`,
      finished_at: new Date().toISOString()
    })
    return new Response(JSON.stringify({ error: 'probe failed' }), { status: 500 })
  }

  // Get most recent successful run
  const { data: lastRun } = await supabase
    .from('scrape_runs')
    .select('fbi_last_refresh_date')
    .eq('status', 'success')
    .eq('run_type', 'full')
    .order('started_at', { ascending: false })
    .limit(1)
    .single()

  const needsRefresh = !lastRun || lastRun.fbi_last_refresh_date !== fbiRefresh

  await supabase.from('scrape_runs').insert({
    run_type: 'heartbeat',
    status: 'success',
    fbi_last_refresh_date: fbiRefresh,
    rows_written: 0,
    finished_at: new Date().toISOString()
  })

  if (needsRefresh) {
    // Trigger the full scrape (fire and forget — runs in background)
    const scrapeUrl = `${Deno.env.get('SUPABASE_URL')}/functions/v1/scrape-fbi`
    fetch(scrapeUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    }).catch(e => console.error('Failed to trigger scrape:', e))
  }

  return new Response(JSON.stringify({
    fbi_refresh: fbiRefresh,
    last_known_refresh: lastRun?.fbi_last_refresh_date ?? null,
    triggered_scrape: needsRefresh
  }), { headers: { 'Content-Type': 'application/json' } })
})
