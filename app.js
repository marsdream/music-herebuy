/* === app.js — Music Herebuy frontend === */

// Fetch the latest available date from the charts table
async function getLatestDate() {
  try {
    const data = await supabaseGet('charts', '?select=date&order=date.desc&limit=1');
    return data.length ? data[0].date : null;
  } catch (e) {
    console.warn('getLatestDate failed:', e);
    return null;
  }
}

// Format a date string (YYYY-MM-DD) to human-readable
function fmtDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}


const API = CONFIG.SUPABASE_REST;

const headers = () => ({
  'apikey': CONFIG.SUPABASE_ANON_KEY,
  'Authorization': `Bearer ${CONFIG.SUPABASE_ANON_KEY}`,
  'Content-Type': 'application/json',
});

// Fetch JSON from Supabase REST
async function supabaseGet(table, qs = '', opts = {}) {
  const url = `${API}/${table}${qs}`;
  const resp = await fetch(url, {
    ...opts,
    headers: { ...headers(), 'Accept-Profile': 'public' },
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`${table} ${resp.status}: ${err.slice(0, 200)}`);
  }
  return resp.json();
}

// ── index.html (home) ──
function renderHome() {
  const wrap = document.getElementById('content');
  wrap.innerHTML = `
    <div class="page-title">
      <h1>🎵 Daily Top Charts</h1>
      <p>Today's music that's moving the world</p>
      <span class="date-badge" id="today-badge"></span>
    </div>
    <div class="tab-bar">
      <button data-source="lastfm" class="active">Last.fm Top 50</button>
      <button data-source="billboard">Billboard Hot 100</button>
    </div>
    <div class="track-list" id="track-list"></div>
    <footer>
      <div class="tag-cloud" id="tag-cloud"></div>
      <p>Powered by Last.fm · Billboard · MusicBrainz · Spotify · Supabase</p>
      <p style="margin-top:6px">music.herebuy.us · built with ❤️ by Yuki</p>
    </footer>
  `;

  // today-badge set dynamically after fetching latest date

  document.querySelectorAll('[data-source]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-source]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadTracks(btn.dataset.source);
    });
  });

  // Fetch latest date and set badge, then load
  const latestDate = await getLatestDate();
  if (latestDate) {
    document.getElementById('today-badge').textContent = `📅 ${fmtDate(latestDate)}`;
  }
  loadTracks('lastfm');
}

async function loadTracks(source) {
  const el = document.getElementById('track-list');
  el.innerHTML = '<div class="loading">Loading tracks</div>';
  try {
    const latestDate = await getLatestDate();
    if (!latestDate) { el.innerHTML = '<div class="empty">No chart data available.</div>'; return; }
    const data = await supabaseGet(
      'charts',
      `?date=eq.${latestDate}&source=eq.${source}&order=rank.asc&limit=50`
    );
    if (!data.length) {
      el.innerHTML = '<div class="empty">No chart data for today yet.</div>';
      return;
    }
    el.innerHTML = data.map((t, i) => {
      const rank = t.rank || (i + 1);
      const hasSp = (t.spotify_url || '').length > 0;
      return `
        <div class="track-row">
          <span class="rank ${rank <= 3 ? 'top3' : ''}">#${rank}</span>
          <div class="info">
            <div class="title">${escHtml(t.track_name)}</div>
            <div class="artist">${escHtml(t.artist)}</div>
            <div class="meta">
              ${t.playcount ? `<span class="playcount">▶ ${fmtCount(t.playcount)}</span>` : ''}
            </div>
          </div>
          ${hasSp ? `<a class="sp-link" href="${escHtml(t.spotify_url)}" target="_blank" rel="noopener">Spotify ↗</a>` : ''}
        </div>
      `;
    }).join('');
  } catch (e) {
    console.error(e);
    el.innerHTML = `<div class="error">⚠ Failed to load ${source}: ${escHtml(e.message)}</div>`;
  }
}

// ── ideas.html ──
async function renderIdeas() {
  const wrap = document.getElementById('content');
  wrap.innerHTML = `
    <div class="page-title">
      <h1>💡 AI Music Ideas</h1>
      <p>Prompts distilled from today's top charts</p>
      <span class="date-badge" id="today-badge"></span>
    </div>
    <div class="ideas-grid" id="ideas-grid"><div class="loading">Loading ideas</div></div>
    <footer>
      <p style="margin-top:30px">music.herebuy.us · built with ❤️ by Yuki</p>
    </footer>
  `;
  // today-badge set dynamically after fetching latest date

  const grid = document.getElementById('ideas-grid');
  try {
    const ideas = await supabaseGet(
      'music_ideas',
      `const latestDate = await getLatestDate(); if (!latestDate) { grid.innerHTML = '<div class=\"empty\">No chart data available.</div>'; return; }
      `?date=eq.${latestDate}&created_at=desc``
    );

    // Fetch generation records
    const genResp = await fetch(`${API}/music_generations?select=*, idea_id&status=eq.success`, {
      headers: { ...headers(), 'Accept-Profile': 'public' },
    });
    const gens = genResp.ok ? await genResp.json() : [];
    const genByIdea = {};
    for (const g of gens) {
      if (!genByIdea[g.idea_id]) genByIdea[g.idea_id] = [];
      genByIdea[g.idea_id].push(g);
    }

    if (!ideas.length) {
      grid.innerHTML = '<div class="empty">No AI ideas for today yet.</div>';
      return;
    }

    grid.innerHTML = ideas.map(idea => {
      const gensForThis = genByIdea[idea.id] || [];
      return `
        <div class="idea-card">
          <div class="header">
            <span class="mood">${escHtml(idea.mood || 'unknown')}</span>
            <span class="style-hint">${escHtml(idea.style_hint || '')}</span>
          </div>
          <div class="prompt">${escHtml(idea.prompt)}</div>
          ${gensForThis.length ? gensForThis.map(g => `
            <div class="generated">
              <span class="dot ready"></span>
              <span class="state">✅ Generated · <em>${escHtml(g.provider || 'music-2.6')}</em> · <em>${escHtml(g.created_at ? g.created_at.slice(0,10) : '')}</em></span>
              <audio controls preload="metadata">
                <source src="${escHtml(g.s3_mp3_url)}" type="audio/mpeg">
              </audio>
            </div>
          `).join('') : `
            <div class="generated">
              <span class="dot empty"></span>
              <span class="state">⏳ Not yet generated</span>
            </div>
          `}
        </div>
      `;
    }).join('');
  } catch (e) {
    console.error(e);
    grid.innerHTML = `<div class="error">⚠ Failed to load ideas: ${escHtml(e.message)}</div>`;
  }
}

// ── track.html ──
async function renderTrack() {
  const wrap = document.getElementById('content');
  const params = new URLSearchParams(location.search);
  const trackId = params.get('track');

  if (!trackId) {
    wrap.innerHTML = `
      <div class="page-title"><h1>🎵 Track</h1></div>
      <div class="empty">No track id provided. Use ?track=&lt;id&gt;.</div>
    `;
    return;
  }

  wrap.innerHTML = `
    <div class="page-title"><h1>🎵 Track Detail</h1></div>
    <div class="track-detail"><div class="loading">Loading track</div></div>
  `;

  try {
    // Look up in charts by id
    const charts = await supabaseGet(`charts?id=eq.${trackId}`);
    const t = charts[0];
    if (!t) {
      wrap.innerHTML += `<div class="error">Track not found</div>`;
      return;
    }

    // Look up in generations (our own AI tracks)
    const genResp = await fetch(`${API}/music_generations?id=eq.${trackId}&select=*,idea!inner(id,mood,prompt,style_hint)`, {
      headers: { ...headers(), 'Accept-Profile': 'public' },
    });
    const gens = genResp.ok ? await genResp.json() : [];

    if (gens.length) {
      const g = gens[0];
      const idea = g.idea;
      wrap.innerHTML = `
        <div class="page-title"><h1>🎵 AI Track</h1><span class="date-badge">${g.created_at ? g.created_at.slice(0,10) : ''}</span></div>
        <div class="track-detail">
          <div class="cover">🎛️</div>
          <h2>${escHtml(idea.mood || 'Untitled')} Track</h2>
          <div class="artist">${escHtml(idea.style_hint || '')} · ${escHtml(g.provider || '')}</div>
          <div style="color:var(--text-dim);font-size:13px;margin-bottom:14px">${escHtml(idea.prompt || '')}</div>
          <audio controls style="width:100%" preload="metadata">
            <source src="${escHtml(g.s3_mp3_url || '')}" type="audio/mpeg">
          </audio>
          <div class="meta-grid">
            <div class="meta-item"><span class="label">Provider</span><span class="value">${escHtml(g.provider || '')}</span></div>
            <div class="meta-item"><span class="label">Status</span><span class="value">${escHtml(g.status || '')}</span></div>
            <div class="meta-item"><span class="label">S3 URL</span><span class="value">${escHtml(g.s3_mp3_url || '')}</span></div>
            <div class="meta-item"><span class="label">Mood</span><span class="value">${escHtml(idea.mood || '')}</span></div>
          </div>
        </div>
      `;
    } else {
      wrap.innerHTML = `
        <div class="page-title"><h1>🎵 Track</h1></div>
        <div class="track-detail">
          <div class="cover">🎧</div>
          <h2>${escHtml(t.track_name)}</h2>
          <div class="artist">${escHtml(t.artist)}</div>
          <div class="meta-grid">
            <div class="meta-item"><span class="label">Source</span><span class="value">${escHtml(t.source || '')}</span></div>
            <div class="meta-item"><span class="label">Rank</span><span class="value">#${t.rank || '-'}</span></div>
            <div class="meta-item"><span class="label">Playcount</span><span class="value">${t.playcount ? fmtCount(t.playcount) : '-'}</span></div>
            <div class="meta-item"><span class="label">Date</span><span class="value">${escHtml(t.date || '')}</span></div>
          </div>
          <div class="meta-item" style="margin-top:12px">
            <span class="label">MBID</span>
            <span class="value">${escHtml(t.mbid || 'not available')}</span>
          </div>
          <a class="sp-link-big" href="${escHtml(t.spotify_url || '')}" target="_blank" rel="noopener">
            ${t.spotify_url ? '▶ Listen on Spotify ↗' : 'No Spotify link'}
          </a>
        </div>
      `;
    }
  } catch (e) {
    console.error(e);
    wrap.innerHTML += `<div class="error">⚠ ${escHtml(e.message)}</div>`;
  }
}

// ── utilities ──
function escHtml(s) {
  if (s == null) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function fmtCount(n) {
  const num = parseInt(n, 10);
  if (isNaN(num)) return n;
  if (num >= 1e6) return (num / 1e6).toFixed(1) + 'M';
  if (num >= 1e3) return (num / 1e3).toFixed(1) + 'K';
  return num.toString();
}

// ── init ──
function main() {
  const page = document.querySelector('meta[name="page"]').content;
  console.log('[music-herebuy] page:', page, '| key present:', !!CONFIG.SUPABASE_ANON_KEY);
  if (page === 'home') renderHome();
  else if (page === 'ideas') renderIdeas();
  else if (page === 'track') renderTrack();
}

document.addEventListener('DOMContentLoaded', main);