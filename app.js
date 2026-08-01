/* === app.js — Music Herebuy frontend === */

const API = CONFIG.SUPABASE_REST;

const headers = () => ({
  'apikey': CONFIG.SUPABASE_ANON_KEY,
  'Authorization': `Bearer ${CONFIG.SUPABASE_ANON_KEY}`,
  'Content-Type': 'application/json',
});

async function supabaseGet(table, qs = '', opts = {}) {
  const url = `${API}/${table}${qs}`;
  const resp = await fetch(url, { ...opts, headers: { ...headers(), 'Accept-Profile': 'public' } });
  if (!resp.ok) throw new Error(`${table} ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
  return resp.json();
}

async function getAllDates() {
  try {
    const data = await supabaseGet('charts', '?select=date&order=date.desc&limit=500');
    const seen = new Set();
    return data.filter(d => { if (seen.has(d.date)) return false; seen.add(d.date); return true; }).map(d => d.date);
  } catch { return []; }
}

function getPrevDate(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr + 'T00:00:00');
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

function fmtDate(dateStr) {
  if (!dateStr) return '—';
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

function escHtml(s) { if (s == null) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function fmtCount(n) { const num = parseInt(n, 10); if (isNaN(num)) return n; if (num >= 1e6) return (num/1e6).toFixed(1)+'M'; if (num >= 1e3) return (num/1e3).toFixed(1)+'K'; return num.toString(); }

async function renderHome() {
  const wrap = document.getElementById('content');
  wrap.innerHTML = `
    <div class="page-title">
      <h1>🎵 Daily Top Charts</h1>
      <p>Today's music that's moving the world</p>
      <div class="date-row">
        <select id="date-select" class="date-select"></select>
        <span id="date-hint" class="date-hint"></span>
      </div>
    </div>
    <div class="tab-bar">
      <button data-source="lastfm" class="active">Last.fm Top 50</button>
      <button data-source="billboard">Billboard Hot 100</button>
    </div>
    <div class="track-list" id="track-list"></div>
    <footer>
      <p>Powered by Last.fm · Billboard · MusicBrainz · Spotify · Supabase</p>
      <p style="margin-top:6px">music.herebuy.us · built with ❤️ by Yuki</p>
    </footer>
  `;

  const dates = await getAllDates();
  const select = document.getElementById('date-select');
  const hint = document.getElementById('date-hint');

  if (!dates.length) { select.innerHTML = '<option value="">No data</option>'; return; }

  select.innerHTML = dates.map(d => `<option value="${d}">${fmtDate(d)}</option>`).join('');
  select.value = dates[0];
  hint.textContent = `${dates.length} dates available · ↑↓ = change vs last week`;

  let currentSource = 'lastfm';

  async function loadWithDate(source, date) {
    const el = document.getElementById('track-list');
    el.innerHTML = '<div class="loading">Loading tracks</div>';
    const prevDate = getPrevDate(date);
    const [currData, prevData] = await Promise.all([
      supabaseGet('charts', `?date=eq.${date}&source=eq.${source}&order=rank.asc&limit=100`),
      prevDate ? supabaseGet('charts', `?date=eq.${prevDate}&source=eq.${source}&order=rank.asc&limit=100`).catch(() => []) : Promise.resolve([]),
    ]);
    const prevMap = {};
    for (const t of prevData) prevMap[`${t.track_name}::${t.artist}`] = t.rank;

    if (!currData.length) { el.innerHTML = '<div class="empty">No chart data for this date.</div>'; return; }

    el.innerHTML = currData.map((t, i) => {
      const rank = t.rank || (i + 1);
      const hasSp = !!(t.spotify_url && t.spotify_url.length > 0);
      const key = `${t.track_name}::${t.artist}`;
      const prevRank = prevMap[key];
      let trendHtml = '';
      if (prevRank !== undefined) {
        const diff = prevRank - rank;
        if (diff > 0) trendHtml = `<span class="trend up" title="Up ${diff} from #${prevRank}">▲ ${diff}</span>`;
        else if (diff < 0) trendHtml = `<span class="trend down" title="Down ${Math.abs(diff)} from #${prevRank}">▼ ${Math.abs(diff)}</span>`;
        else trendHtml = `<span class="trend same" title="Same as #${prevRank}">—</span>`;
      } else {
        trendHtml = `<span class="trend new" title="New entry this week">NEW</span>`;
      }
      return `<div class="track-row">
        <span class="rank ${rank <= 3 ? 'top3' : ''}">#${rank}</span>
        ${trendHtml}
        <div class="info">
          <div class="title">${escHtml(t.track_name)}</div>
          <div class="artist">${escHtml(t.artist)}</div>
          <div class="meta">${t.playcount ? `<span class="playcount">▶ ${fmtCount(t.playcount)}</span>` : ''}</div>
        </div>
        ${hasSp ? `<a class="sp-link" href="${escHtml(t.spotify_url)}" target="_blank" rel="noopener">Spotify ↗</a>` : ''}
      </div>`;
    }).join('');
  }

  document.querySelectorAll('[data-source]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-source]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentSource = btn.dataset.source;
      loadWithDate(currentSource, select.value);
    });
  });

  select.addEventListener('change', () => loadWithDate(currentSource, select.value));

  loadWithDate('lastfm', dates[0]);
}

async function renderIdeas() {
  const wrap = document.getElementById('content');
  wrap.innerHTML = `
    <div class="page-title"><h1>💡 AI Music Ideas</h1><p>Prompts distilled from today's top charts</p><span class="date-badge" id="today-badge"></span></div>
    <div class="ideas-grid" id="ideas-grid"><div class="loading">Loading ideas</div></div>
    <footer><p style="margin-top:30px">music.herebuy.us · built with ❤️ by Yuki</p></footer>
  `;
  const dates = await getAllDates();
  const latestDate = dates[0] || null;
  if (latestDate) document.getElementById('today-badge').textContent = `📅 ${fmtDate(latestDate)}`;
  const grid = document.getElementById('ideas-grid');
  if (!latestDate) { grid.innerHTML = '<div class="empty">No chart data available.</div>'; return; }
  try {
    const ideas = await supabaseGet('music_ideas', `?date=eq.${latestDate}&order=created_at.desc`);
    const genResp = await fetch(`${API}/music_generations?select=*,idea_id&status=eq.success`, { headers: { ...headers(), 'Accept-Profile': 'public' } });
    const gens = genResp.ok ? await genResp.json() : [];
    const genByIdea = {};
    for (const g of gens) { if (!genByIdea[g.idea_id]) genByIdea[g.idea_id] = []; genByIdea[g.idea_id].push(g); }
    if (!ideas.length) { grid.innerHTML = '<div class="empty">No AI ideas for today yet.</div>'; return; }
    grid.innerHTML = ideas.map(idea => {
      const gs = genByIdea[idea.id] || [];
      return `<div class="idea-card">
        <div class="header"><span class="mood">${escHtml(idea.mood||'unknown')}</span><span class="style-hint">${escHtml(idea.style_hint||'')}</span></div>
        <div class="prompt">${escHtml(idea.prompt)}</div>
        ${gs.length ? gs.map(g => `<div class="generated"><span class="dot ready"></span><span class="state">✅ Generated · <em>${escHtml(g.provider||'music-2.6')}</em> · <em>${escHtml(g.created_at?g.created_at.slice(0,10):'')}</em></span><audio controls preload="metadata"><source src="${escHtml(g.s3_mp3_url)}" type="audio/mpeg"></audio></div>`).join('') : `<div class="generated"><span class="dot empty"></span><span class="state">⏳ Not yet generated</span></div>`}
      </div>`;
    }).join('');
  } catch(e) { grid.innerHTML = `<div class="error">⚠ Failed: ${escHtml(e.message)}</div>`; }
}

async function renderTrack() {
  const wrap = document.getElementById('content');
  const params = new URLSearchParams(location.search);
  const trackId = params.get('track');
  if (!trackId) { wrap.innerHTML = '<div class="page-title"><h1>🎵 Track</h1></div><div class="empty">No track id provided.</div>'; return; }
  wrap.innerHTML = '<div class="page-title"><h1>🎵 Track Detail</h1></div><div class="track-detail"><div class="loading">Loading</div></div>';
  try {
    const charts = await supabaseGet(`charts?id=eq.${trackId}`);
    const t = charts[0];
    if (!t) { wrap.innerHTML += '<div class="error">Track not found</div>'; return; }
    const genResp = await fetch(`${API}/music_generations?id=eq.${trackId}&select=*,idea!inner(id,mood,prompt,style_hint)`, { headers: { ...headers(), 'Accept-Profile': 'public' } });
    const gens = genResp.ok ? await genResp.json() : [];
    if (gens.length) {
      const g = gens[0], idea = g.idea;
      wrap.innerHTML = `<div class="page-title"><h1>🎵 AI Track</h1><span class="date-badge">${(g.created_at||'').slice(0,10)}</span></div><div class="track-detail"><div class="cover">🎛️</div><h2>${escHtml(idea.mood||'Untitled')}</h2><div class="artist">${escHtml(idea.style_hint||'')} · ${escHtml(g.provider||'')}</div><div style="color:var(--text-dim);font-size:13px;margin-bottom:14px">${escHtml(idea.prompt||'')}</div><audio controls style="width:100%"><source src="${escHtml(g.s3_mp3_url||'')}" type="audio/mpeg"></audio><div class="meta-grid"><div class="meta-item"><span class="label">Provider</span><span class="value">${escHtml(g.provider||'')}</span></div><div class="meta-item"><span class="label">Status</span><span class="value">${escHtml(g.status||'')}</span></div><div class="meta-item"><span class="label">S3 URL</span><span class="value">${escHtml(g.s3_mp3_url||'')}</span></div><div class="meta-item"><span class="label">Mood</span><span class="value">${escHtml(idea.mood||'')}</span></div></div></div>`;
    } else {
      wrap.innerHTML = `<div class="page-title"><h1>🎵 Track</h1></div><div class="track-detail"><div class="cover">🎧</div><h2>${escHtml(t.track_name)}</h2><div class="artist">${escHtml(t.artist)}</div><div class="meta-grid"><div class="meta-item"><span class="label">Source</span><span class="value">${escHtml(t.source||'')}</span></div><div class="meta-item"><span class="label">Rank</span><span class="value">#${t.rank||'-'}</span></div><div class="meta-item"><span class="label">Playcount</span><span class="value">${t.playcount?fmtCount(t.playcount):'-'}</span></div><div class="meta-item"><span class="label">Date</span><span class="value">${escHtml(t.date||'')}</span></div></div><div class="meta-item" style="margin-top:12px"><span class="label">MBID</span><span class="value">${escHtml(t.mbid||'not available')}</span></div><a class="sp-link-big" href="${escHtml(t.spotify_url||'')}" target="_blank">${t.spotify_url?'▶ Listen on Spotify ↗':'No Spotify link'}</a></div>`;
    }
  } catch(e) { wrap.innerHTML += `<div class="error">⚠ ${escHtml(e.message)}</div>`; }
}

function main() {
  const page = document.querySelector('meta[name="page"]').content;
  if (page === 'home') renderHome();
  else if (page === 'ideas') renderIdeas();
  else if (page === 'track') renderTrack();
}
document.addEventListener('DOMContentLoaded', main);
