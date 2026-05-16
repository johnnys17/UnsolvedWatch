// /js/config.js
// Supabase client configuration

// These are PUBLIC keys (anon key only) — safe to expose in client code.
// The service_role key NEVER goes here.
// Replace these placeholders with your actual values, or wire to Netlify build env vars.

export const SUPABASE_URL = 'https://qledolmbjvxdqlztmqdd.supabase.co'
export const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFsZWRvbG1ianZ4ZHFsenRtcWRkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg5NDc3MzIsImV4cCI6MjA5NDUyMzczMn0.R3bNi9uIlHYD1R4d77AxYQ2PNYF8df0CvHOCQT-pAoI'

// Helper for direct REST queries (avoids loading the full @supabase/supabase-js bundle)
export async function sbQuery(path, params = {}) {
    const url = new URL(`${SUPABASE_URL}/rest/v1/${path}`)
    for (const [k, v] of Object.entries(params)) {
        url.searchParams.set(k, v)
    }
    const res = await fetch(url, {
        headers: {
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
            'Accept': 'application/json'
        }
    })
    if (!res.ok) {
        console.error(`Supabase query failed: ${res.status}`, await res.text())
        return []
    }
    return res.json()
}

// Month-name lookup
export const MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// Format integer with commas
export function fmtNum(n) {
    if (n == null) return '—'
    return Number(n).toLocaleString('en-US')
}

// Format period e.g. "May 2026"
export function fmtPeriod(year, month) {
    return `${MONTH_NAMES[month]} ${year}`
}
