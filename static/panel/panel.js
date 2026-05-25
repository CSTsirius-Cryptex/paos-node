/* =====================================================================
   panel.js — PAOS Node 控制台
   設計：Claude Design 視覺規格 + 真實 API 連線
   ===================================================================== */

const API = '/panel/api';

/* ── State ──────────────────────────────────────────────────────────── */
const state = {
  tab: 'status',
  statusData: null,
  diagRunning: false,
  diagResults: null,
  diagTime: null,
  autoRefresh: 30,
  refreshTimer: null,
  autoScroll: true,
  vaultDirty: false,
  settingsData: null,
  gptCount: 0,
  logLineCount: 0
};

/* ── Helpers ────────────────────────────────────────────────────────── */
const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];

async function apiFetch(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(API + path, opts);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function fmtTime(d = new Date()) {
  return d.toTimeString().slice(0,8);
}

/* ── Op Banner ──────────────────────────────────────────────────────── */
function opShow(msg, kind = 'running') {
  const banner = $('#op-banner');
  const msgEl  = $('#op-banner-msg');
  banner.className = 'op-banner' + (kind === 'ok' ? ' op-ok' : kind === 'err' ? ' op-err' : '');
  msgEl.textContent = msg;
  banner.hidden = false;
}
function opClear() { $('#op-banner').hidden = true; }
$('#op-banner-dismiss').addEventListener('click', opClear);

/* Auto-dismiss ok/err after 5s */
let opTimer = null;
function opShowAuto(msg, kind) {
  clearTimeout(opTimer);
  opShow(msg, kind);
  if (kind !== 'running') {
    opTimer = setTimeout(opClear, 5000);
  }
}

/* ── Tab switcher ───────────────────────────────────────────────────── */
$$('#tabbar .tab').forEach(t => {
  t.addEventListener('click', () => switchTab(t.dataset.tab));
});

function switchTab(name) {
  state.tab = name;
  $$('#tabbar .tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  render();
}

/* ── Auto-refresh ───────────────────────────────────────────────────── */
function setRefreshInterval(seconds) {
  clearInterval(state.refreshTimer);
  state.autoRefresh = seconds;
  if (seconds > 0) {
    state.refreshTimer = setInterval(() => {
      if (state.tab === 'status') loadStatusAndRender();
    }, seconds * 1000);
  }
}

/* ── Master render ──────────────────────────────────────────────────── */
function render() {
  const content = $('#content');
  if (state.tab === 'status')   { content.innerHTML = renderStatus();   wireTab(); loadStatusAndRender(); }
  else if (state.tab === 'gpts')     { content.innerHTML = renderGpts();    wireTab(); loadGptsAndRender(); }
  else if (state.tab === 'settings') { content.innerHTML = renderSettings(); wireTab(); loadSettingsAndRender(); }
  else if (state.tab === 'logs')     { content.innerHTML = renderLogs();   wireTab(); loadLogsAndRender(); }
}

/* ====================================================================
   TAB 1 · 狀態總覽
   ==================================================================== */

const LABEL_LIST = ['排程工作','Node 服務','Vault 存取','Tunnel','Central 連線','已向 Central 登錄'];

function buildStatusCardsFromData(data) {
  if (!data) return LABEL_LIST.map((l,i)=>({id:i+1,label:l,state:'unk',detail:'載入中…'}));

  const tunnelOk = data.tunnel?.status === 'connected';
  return [
    {id:1,label:'排程工作', state:data.scheduler?.status==='ok'?'ok':'bad',
     detail:data.scheduler?.status==='ok'?'PAOS-Node 排程執行中':(data.scheduler?.error||'未找到排程工作')},
    {id:2,label:'Node 服務', state:data.node?.status==='ok'?'ok':'bad',
     detail:data.node?.latency_ms!=null?`本機 FastAPI 回應 · ${data.node.latency_ms}ms`:(data.node?.error||'Node 無回應')},
    {id:3,label:'Vault 存取', state:data.vault?.status==='ok'?'ok':'bad',
     detail:data.vault?.status==='ok'?'路徑存在且可讀寫':(data.vault?.error||'Vault 無法存取')},
    {id:4,label:'Tunnel', state:tunnelOk?'ok':'bad',
     detail:tunnelOk?(data.tunnel?.url||''):(data.tunnel?.error||'Tunnel 未連線'), url:tunnelOk},
    {id:5,label:'Central 連線', state:data.central?.status==='ok'?'ok':'bad',
     detail:data.central?.latency_ms!=null?`Central 可達 · ${data.central.latency_ms}ms`:(data.central?.error||'Central 無法連線')},
    {id:6,label:'已向 Central 登錄',
     state:data.registered?.status==='ok'?'ok':(data.central?.status!=='ok'?'unk':'bad'),
     detail:data.registered?.status==='ok'?'Central 識別此 Node'
       :(data.central?.status!=='ok'?'等待 Central 連線後檢查':(data.registered?.error||'尚未登錄'))}
  ];
}

async function loadStatusAndRender() {
  try {
    const data = await apiFetch('GET', '/status');
    state.statusData = data;
  } catch(e) {
    state.statusData = null;
  }
  if (state.tab === 'status') {
    $('#content').innerHTML = renderStatus();
    wireTab();
  }
}

function renderStatus() {
  const cards = buildStatusCardsFromData(state.statusData);
  const okCount = cards.filter(c => c.state === 'ok').length;
  const anyBad  = cards.some(c => c.state === 'bad');
  const pillCls = anyBad ? 'pill warn' : 'pill';
  const pillTxt = anyBad ? `部分異常 · ${okCount}/6` : `全部正常 · ${okCount}/6`;
  const lastCheck = state.statusData ? `最後檢查 ${fmtTime()}` : '尚未載入';

  const diagWhen = state.diagRunning ? '進行中…'
    : state.diagTime ? `完成於 ${state.diagTime}`
    : '尚未執行';

  return `
    <div class="panel-page active">
      <header class="summary-head">
        <div class="summary-title">
          <h1>狀態總覽</h1>
          <div class="sub">
            <span class="${pillCls}"><span class="pdot"></span>${pillTxt}</span>
            <span style="color:var(--text-mute)">·</span>
            <span style="font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11.5px;color:var(--text-faint)">${lastCheck}</span>
          </div>
        </div>
        <div class="summary-actions">
          <button class="icon-btn" data-act="refresh" title="重新整理">
            <svg viewBox="0 0 16 16" fill="none"><path d="M13 8a5 5 0 11-1.5-3.5L13 6M13 3v3h-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button class="btn btn-sm btn-ghost" data-act="start">啟動 Node</button>
          <button class="btn btn-sm btn-ghost" data-act="restart">重啟 Node</button>
          <button class="btn btn-sm btn-ghost" data-act="repair">修復</button>
          <button class="btn" data-act="diagnose">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/><path d="M8 5v3.5l2 1.2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            連線診斷
          </button>
        </div>
      </header>

      <div class="status-grid">
        ${cards.map(lightCard).join('')}
      </div>

      <div class="control-row">
        <div class="left">
          <span style="font-size:11.5px;color:var(--text-faint)">輔助設定</span>
        </div>
        <div class="right">
          <span>自動刷新</span>
          <select class="select" id="sel-refresh">
            ${[10,30,60,120,0].map(v=>`<option value="${v}" ${state.autoRefresh==v?'selected':''}>${v?'每 '+v+' 秒':'關閉'}</option>`).join('')}
          </select>
        </div>
      </div>

      <div class="diag">
        <div class="diag-h">
          <h3>連線診斷結果</h3>
          <span class="when">${diagWhen}</span>
        </div>
        <div class="diag-rows" id="diag-rows">${renderDiagRows()}</div>
      </div>
    </div>
  `;
}

function lightCard(s) {
  let descHtml;
  if (s.url && s.state === 'ok') {
    descHtml = `<a class="copy-link" data-copy="${s.detail}" title="點擊複製">${s.detail}</a>`;
  } else if (s.state === 'bad') {
    descHtml = `<span style="color:#fca5a5">${s.detail}</span>`;
  } else if (s.state === 'unk') {
    descHtml = `<span style="color:var(--text-mute)">${s.detail}</span>`;
  } else {
    descHtml = `<span style="color:var(--text-dim)">${s.detail}</span>`;
  }
  return `
    <div class="light-card" data-state="${s.state}">
      <div class="ldot"></div>
      <div class="lbody">
        <div class="ltitle">${s.label}<span class="lnum">${String(s.id).padStart(2,'0')}</span></div>
        <p class="ldesc">${descHtml}</p>
      </div>
    </div>
  `;
}

function renderDiagRows() {
  if (!state.diagResults) {
    return `<div class="diag-empty">點上方「連線診斷」開始檢查六個服務的連線狀態。</div>`;
  }
  const icons = {
    ok:   `<svg width="9" height="9" viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    bad:  `<svg width="9" height="9" viewBox="0 0 12 12" fill="none"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
    skip: `<svg width="9" height="9" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="4" stroke="currentColor" stroke-width="1.4"/></svg>`,
    run:  ''
  };
  return state.diagResults.map(r => `
    <div class="diag-row" data-r="${r.r}">
      <div class="di">${icons[r.r] || ''}</div>
      <div class="dlabel">${r.label}</div>
      <div class="dmsg">${r.msg}</div>
    </div>
  `).join('');
}

async function runDiagnose() {
  if (state.diagRunning) return;
  state.diagRunning = true;
  state.diagResults = LABEL_LIST.map(l => ({ label:l, r:'run', msg:'檢查中…' }));
  if (state.tab === 'status') { $('#content').innerHTML = renderStatus(); wireTab(); }

  try {
    const data = await apiFetch('GET', '/diagnose');
    // Animate steps sequentially (step.step is 1-based)
    for (const step of (data.steps || [])) {
      await new Promise(r => setTimeout(r, step.status === 'ok' ? 450 : 800));
      const idx = (step.step || 1) - 1;
      if (idx >= 0 && idx < state.diagResults.length) {
        const detail = step.detail || step.url || step.node_url || step.error || '';
        const latency = step.latency_ms != null ? ` · ${step.latency_ms}ms` : '';
        // Treat "上一步失敗，跳過" messages as skip
        const isSkip = detail.includes('跳過') || detail.includes('上一步');
        state.diagResults[idx] = {
          label: LABEL_LIST[idx],
          r: isSkip ? 'skip' : step.status === 'ok' ? 'ok' : 'bad',
          msg: detail + latency
        };
        if (state.tab === 'status') {
          const rowsEl = $('#diag-rows');
          if (rowsEl) rowsEl.innerHTML = renderDiagRows();
        }
      }
    }
  } catch(e) {
    state.diagResults = [{label:'診斷失敗', r:'bad', msg: e.message}];
  }

  state.diagRunning = false;
  state.diagTime = fmtTime();
  if (state.tab === 'status') {
    $('#content').innerHTML = renderStatus();
    wireTab();
  }
}

/* ====================================================================
   TAB 2 · 我的助理
   ==================================================================== */
async function loadGptsAndRender() {
  try {
    const data = await apiFetch('GET', '/gpts');
    state.gptData = data;
  } catch(e) {
    state.gptData = { error: e.message };
  }
  if (state.tab === 'gpts') { $('#content').innerHTML = renderGpts(); wireTab(); }
}

function renderGpts() {
  const data = state.gptData;
  let cards = '';
  let count = 0;

  if (!data) {
    cards = `<div class="gpt-empty"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.4"/><circle cx="9" cy="12" r="1.5" fill="currentColor"/><circle cx="15" cy="12" r="1.5" fill="currentColor"/><path d="M12 2v3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg><h3>載入中…</h3><p>正在取得助理清單</p></div>`;
  } else if (data.error) {
    cards = `<div class="gpt-empty"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.4"/></svg><h3>載入失敗</h3><p>${data.error}</p></div>`;
  } else if (data.note) {
    cards = `<div class="gpt-empty"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.4"/></svg><h3>尚未設定</h3><p>${data.note}</p></div>`;
  } else {
    const gpts = data.gpts || [];
    count = gpts.length;
    if (!gpts.length) {
      cards = `<div class="gpt-empty"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.4"/><circle cx="9" cy="12" r="1.5" fill="currentColor"/><circle cx="15" cy="12" r="1.5" fill="currentColor"/><path d="M12 2v3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg><h3>目前沒有可用的助理</h3><p>請聯絡管理員為你開通 GPT 授權。</p></div>`;
    } else {
      cards = gpts.map(gptCard).join('');
    }
  }

  // update tab badge
  const gptTab = document.querySelector('[data-tab="gpts"]');
  const badge = gptTab?.querySelector('.badge');
  if (count > 0) {
    if (!badge) {
      const b = document.createElement('span');
      b.className = 'badge';
      b.textContent = count;
      gptTab?.appendChild(b);
    } else {
      badge.textContent = count;
    }
  } else if (badge) {
    badge.remove();
  }

  return `
    <div class="panel-page active">
      <header class="gpt-toolbar">
        <div>
          <h1>我的助理</h1>
          <div class="sub">你目前可使用的 GPT${count ? ` · 共 ${count} 個` : ''}</div>
        </div>
        <div class="right">
          <button class="icon-btn" data-act="refresh-gpts" title="重新整理">
            <svg viewBox="0 0 16 16" fill="none"><path d="M13 8a5 5 0 11-1.5-3.5L13 6M13 3v3h-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </header>
      <div class="gpt-grid">${cards}</div>
    </div>
  `;
}

function gptCard(g) {
  const disabled = g.has_access === false;
  const emoji = (g.name || '?').slice(0,1);
  const expires = g.expires_at
    ? `<span><strong>授權至：</strong><span style="font-family:'JetBrains Mono',ui-monospace,monospace">${new Date(g.expires_at).toLocaleDateString('zh-TW')}</span></span>`
    : `<span><strong>授權至：</strong>永久</span>`;
  const ownerTxt = g.owner_name
    ? `<span><strong>擁有者：</strong>${g.owner_name}</span>`
    : '';

  const foot = disabled
    ? `<div class="foot"><div class="lock-msg">已停用${g.owner_email?` · <span class="lk">${g.owner_email}</span>`:''}</div><span class="stub-badge expired">已停用</span></div>`
    : `<div class="foot"><span></span>${g.chatgpt_url
        ? `<button class="btn btn-sm" data-act="open-gpt" data-url="${g.chatgpt_url}">開啟助理 <svg width="11" height="11" viewBox="0 0 16 16" fill="none"><path d="M6 3h7v7M13 3L4 12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>`
        : `<span class="stub-badge">無連結</span>`}</div>`;

  return `
    <div class="gpt-card ${disabled?'disabled':''}">
      <div class="head">
        <div class="avatar">${emoji}</div>
        <div class="htext">
          <h3>${g.name}</h3>
          <p class="desc">${g.description || ''}</p>
        </div>
      </div>
      <div class="meta">${ownerTxt}${expires}</div>
      ${foot}
    </div>
  `;
}

/* ====================================================================
   TAB 3 · 設定
   ==================================================================== */
async function loadSettingsAndRender() {
  try {
    const data = await apiFetch('GET', '/settings');
    state.settingsData = data;
  } catch(e) {
    state.settingsData = null;
  }
  if (state.tab === 'settings') { $('#content').innerHTML = renderSettings(); wireTab(); }
  // Also update auto-refresh timer from settings
  if (state.settingsData?.refresh_interval_seconds != null) {
    setRefreshInterval(state.settingsData.refresh_interval_seconds);
  }
}

function renderSettings() {
  const d = state.settingsData;
  const vaultPath = d?.vault_path || '';
  const archivePath = d?.attachment_default_path ? `${vaultPath}/${d.attachment_default_path}` : '';
  const tunnelUrl  = d?.tunnel_url || '（未取得）';
  const email      = d?.owner_email || '—';
  const autoStart  = !!d?.auto_start;
  const ri         = d?.refresh_interval_seconds ?? 30;

  let tokenHtml = '<span class="token-missing">⚠️ 未設定</span>';
  if (d?.token_days_remaining != null) {
    tokenHtml = d.token_days_remaining > 0
      ? `<span class="token-ok">✅ 有效（剩 ${d.token_days_remaining} 天）</span>`
      : `<span class="token-expired">❌ 已過期，請重新登入</span>`;
  }

  const dirtyWarn = state.vaultDirty ? `
    <div style="padding:0 16px 12px;">
      <div class="inline-warn">
        <svg viewBox="0 0 16 16" fill="none"><path d="M8 1.5L1.5 13h13L8 1.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6v3M8 11v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
        修改將於重啟 Node 後生效
      </div>
    </div>` : '';

  return `
    <div class="panel-page active">
      <header class="settings-h">
        <h1>設定</h1>
        <div class="sub">管理 Node 本機設定 · 帳號資訊唯讀</div>
      </header>

      <!-- G1: 記憶庫 -->
      <section class="setgroup">
        <div class="setgroup-h"><span class="gnum">G1</span><span>記憶庫</span></div>
        <div class="set-card">
          <div class="set-row">
            <div class="skey">Vault 路徑<span class="shint">Obsidian Vault 的所在資料夾</span></div>
            <div class="sval" title="${vaultPath}">${vaultPath || '—'}</div>
            <div class="saction">
              <button class="btn btn-sm btn-ghost" data-act="pick-vault">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M2 5v8a1 1 0 001 1h10a1 1 0 001-1V6a1 1 0 00-1-1H8L6 3H3a1 1 0 00-1 1v1z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
                選擇資料夾
              </button>
            </div>
          </div>
          ${dirtyWarn}
          <div class="set-row">
            <div class="skey">歸檔預設路徑<span class="shint">未指定專案時，GPT 產出的檔案存放於此</span></div>
            <div class="sval" title="${archivePath}">${archivePath || '—'}</div>
            <div class="saction" style="color:var(--text-faint);font-size:11px">唯讀</div>
          </div>
        </div>
      </section>

      <!-- G2: 系統 -->
      <section class="setgroup">
        <div class="setgroup-h"><span class="gnum">G2</span><span>系統</span></div>
        <div class="set-card">
          <div class="set-row">
            <div class="skey">開機自動啟動<span class="shint">登入 Windows 時自動啟動 Node 背景服務</span></div>
            <div class="sval"></div>
            <div class="saction">
              <input type="checkbox" class="toggle" id="toggle-autostart" ${autoStart?'checked':''} />
            </div>
          </div>
          <div class="set-row">
            <div class="skey">自動刷新間隔<span class="shint">狀態總覽的自動刷新頻率</span></div>
            <div class="sval"></div>
            <div class="saction">
              <select class="select" id="sel-refresh-settings" style="width:130px">
                ${[10,30,60,120,0].map(v=>`<option value="${v}" ${ri==v?'selected':''}>${v?'每 '+v+' 秒':'關閉'}</option>`).join('')}
              </select>
            </div>
          </div>
        </div>
      </section>

      <!-- G3: Tunnel -->
      <section class="setgroup">
        <div class="setgroup-h"><span class="gnum">G3</span><span>Tunnel</span></div>
        <div class="set-card">
          <div class="set-row">
            <div class="skey">目前 URL<span class="shint">cloudflared 產生的對外位址</span></div>
            <div class="sval" style="color:var(--info)" id="settings-tunnel-url">${tunnelUrl}</div>
            <div class="saction">
              <button class="icon-btn" id="btn-copy-tunnel" title="複製">
                <svg viewBox="0 0 16 16" fill="none"><rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.4"/><path d="M3 11V3a1 1 0 011-1h7" stroke="currentColor" stroke-width="1.4"/></svg>
              </button>
            </div>
          </div>
          <div class="set-row">
            <div class="skey">重新建立 Tunnel<span class="shint">產生新的對外 URL 並重新登錄 Central</span></div>
            <div class="sval"></div>
            <div class="saction">
              <button class="btn btn-sm btn-ghost" data-act="rebuild-tunnel">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M13 8a5 5 0 11-1.5-3.5L13 6M13 3v3h-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
                重新建立
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- G4: 帳號 -->
      <section class="setgroup" style="margin-bottom:8px">
        <div class="setgroup-h"><span class="gnum">G4</span><span>帳號</span></div>
        <div class="set-card" style="margin-bottom:10px">
          <div class="set-row">
            <div class="skey">Email</div>
            <div class="sval">${email}</div>
            <div class="saction" style="color:var(--text-faint);font-size:11px">已驗證</div>
          </div>
          <div class="set-row">
            <div class="skey">Token 狀態</div>
            <div class="sval">${tokenHtml}</div>
            <div class="saction">
              <button class="btn btn-sm btn-ghost" data-act="show-reauth" id="btn-toggle-reauth">重新登入</button>
            </div>
          </div>
        </div>

        <!-- Reauth form (hidden by default) -->
        <div id="reauth-form" hidden>
          <div class="reauth-card">
            <div class="reauth-row">
              <span class="skey">Email</span>
              <input type="email" class="input" id="reauth-email" placeholder="輸入 email" value="${email !== '—' ? email : ''}" style="flex:1">
              <button class="btn btn-sm" data-act="send-otp">發送驗證碼</button>
            </div>
            <div class="reauth-row" id="otp-row" hidden>
              <span class="skey">驗證碼</span>
              <input type="text" class="input" id="reauth-otp" placeholder="6 位數字" maxlength="6" style="flex:1">
              <button class="btn btn-sm" data-act="verify-otp">確認登入</button>
            </div>
            <div class="reauth-hint" id="reauth-hint"></div>
          </div>
        </div>

        <div class="danger-row">
          <div class="text">
            <strong>登出此 Node</strong>
            <div style="margin-top:2px;font-size:11.5px;color:var(--text-faint)">登出後此 Node 將需重新驗證 email 才能繼續同步</div>
          </div>
          <button class="btn btn-sm btn-danger" data-act="logout">登出</button>
        </div>
      </section>

      <!-- Save -->
      <div style="display:flex;align-items:center;gap:12px;margin-top:16px;margin-bottom:24px">
        <button class="btn" data-act="save-settings">儲存設定</button>
        <span id="save-status" style="font-size:12.5px;color:var(--ok-2)"></span>
      </div>
    </div>
  `;
}

/* ====================================================================
   TAB 4 · 執行記錄
   ==================================================================== */
async function loadLogsAndRender() {
  try {
    const data = await apiFetch('GET', '/logs?lines=200');
    state.logsData = data;
  } catch(e) {
    state.logsData = null;
  }
  if (state.tab === 'logs') { $('#content').innerHTML = renderLogs(); wireTab(); }
}

function renderLogs() {
  const lines = state.logsData?.lines || [];
  state.logLineCount = lines.length;

  // Parse log lines: "HH:MM:SS LEVEL message"
  const rendered = lines.map(raw => {
    const m = raw.match(/^(\d{2}:\d{2}:\d{2})\s+(INFO|WARNING|ERROR|DEBUG|OK|WARN)\s+(.*)$/i);
    if (m) {
      const lvlRaw = m[2].toLowerCase().replace('warning','warn');
      const msg = m[3]
        .replace(/\[([^\]]+)\]/g, '<span class="tag">[$1]</span>')
        .replace(/(https?:\/\/[^\s]+)/g, '<span class="url">$1</span>');
      return `<div class="log-line"><span class="log-time">${m[1]}</span><span class="log-lvl ${lvlRaw}">${lvlRaw}</span><span class="log-msg">${msg}</span></div>`;
    }
    return `<div class="log-line"><span class="log-time"></span><span class="log-lvl debug">—</span><span class="log-msg">${raw}</span></div>`;
  }).join('');

  return `
    <div class="panel-page active log-page">
      <div class="log-toolbar">
        <div class="left">
          <span><strong style="color:var(--text)">執行記錄</strong></span>
          <span class="mono-meta">${lines.length} 行</span>
        </div>
        <div class="right">
          <label class="toggle-inline">
            <input type="checkbox" class="toggle" id="toggle-autoscroll" ${state.autoScroll?'checked':''} />
            <span>自動捲動</span>
          </label>
          <button class="btn btn-sm btn-ghost" data-act="refresh-logs">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M13 8a5 5 0 11-1.5-3.5L13 6M13 3v3h-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
            重新整理
          </button>
          <button class="btn btn-sm btn-ghost" data-act="clear-logs">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 5h10M6 5V3.5A1 1 0 017 2.5h2a1 1 0 011 1V5M5 5l1 8a1 1 0 001 1h2a1 1 0 001-1l1-8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
            清除顯示
          </button>
        </div>
      </div>
      <div class="log-stream" id="log-stream">
        ${rendered}
        <div class="log-line">
          <span class="log-time">${fmtTime()}</span>
          <span class="log-lvl info">info</span>
          <span class="log-msg">awaiting next event<span class="log-cursor"></span></span>
        </div>
      </div>
    </div>
  `;
}

/* ====================================================================
   Wire tab interactions
   ==================================================================== */
function wireTab() {
  // copy links
  $$('[data-copy]').forEach(el => {
    el.addEventListener('click', e => {
      e.preventDefault();
      const v = el.dataset.copy;
      navigator.clipboard?.writeText(v);
      toast(`已複製 · ${v.length > 40 ? v.slice(0,40)+'…' : v}`);
    });
  });

  // action buttons
  $$('[data-act]').forEach(b => {
    b.addEventListener('click', () => handleAction(b.dataset.act, b));
  });

  // auto-refresh select (Tab 1)
  const selRefresh = $('#sel-refresh');
  if (selRefresh) {
    selRefresh.addEventListener('change', e => {
      setRefreshInterval(parseInt(e.target.value));
      apiFetch('PUT', '/settings', { refresh_interval_seconds: parseInt(e.target.value) }).catch(()=>{});
    });
  }

  // auto-scroll toggle (Tab 4)
  const toggleScroll = $('#toggle-autoscroll');
  if (toggleScroll) {
    toggleScroll.addEventListener('change', e => {
      state.autoScroll = e.target.checked;
      if (state.autoScroll) scrollLogToBottom();
    });
    if (state.autoScroll) scrollLogToBottom();
  }

  // copy tunnel btn (Tab 3)
  $('#btn-copy-tunnel')?.addEventListener('click', () => {
    const url = $('#settings-tunnel-url')?.textContent;
    if (url && url !== '（未取得）') {
      navigator.clipboard?.writeText(url);
      toast(`已複製 · ${url}`);
    }
  });

  // reauth form toggle
  $('#btn-toggle-reauth')?.addEventListener('click', () => {
    const form = $('#reauth-form');
    if (form) form.hidden = !form.hidden;
  });
}

function scrollLogToBottom() {
  const s = $('#log-stream');
  if (s) s.scrollTop = s.scrollHeight;
}

/* ====================================================================
   Action handlers
   ==================================================================== */
function handleAction(act, btn) {
  switch(act) {
    case 'diagnose': runDiagnose(); break;
    case 'refresh':  loadStatusAndRender(); break;
    case 'refresh-gpts': loadGptsAndRender(); break;
    case 'refresh-logs': loadLogsAndRender(); break;

    case 'start':
      opShow('啟動中…請稍候約 30 秒', 'running');
      apiFetch('POST', '/node/start', {}).then(() => {
        pollUntilNodeUp('Node 已啟動');
      }).catch(e => opShowAuto('❌ 啟動失敗：' + e.message, 'err'));
      break;

    case 'restart':
      showConfirm({
        kind: 'warn', title: '重啟 Node？',
        body: '重啟期間（約 30 秒）Node 服務會中斷，所有 GPT 助理暫時無法存取記憶庫。',
        confirm: '確認重啟',
        onConfirm: () => {
          opShow('重啟中…約 30 秒', 'running');
          apiFetch('POST', '/node/restart', {}).then(() => {
            pollUntilNodeUp('✅ Node 已重啟完成');
          }).catch(e => opShowAuto('❌ 重啟失敗：' + e.message, 'err'));
        }
      });
      break;

    case 'repair':
      showConfirm({
        kind: 'warn', title: '嘗試自動修復？',
        body: '將強制終止 Node 進程並重新啟動，包含重建 Tunnel。整個過程約需 30–60 秒。',
        confirm: '開始修復',
        onConfirm: () => {
          opShow('修復中…約 30–60 秒', 'running');
          apiFetch('POST', '/node/repair', {}).then(() => {
            pollUntilNodeUp('✅ 修復完成，Node 已上線');
          }).catch(e => opShowAuto('❌ 修復失敗：' + e.message, 'err'));
        }
      });
      break;

    case 'rebuild-tunnel':
      showConfirm({
        kind: 'warn', title: '重新建立 Tunnel？',
        body: '將產生新的對外 URL，並重新登錄 Central。已連線的 GPT 助理在新 URL 同步前可能短暫斷線。',
        confirm: '確認重建',
        onConfirm: () => {
          opShow('重建 Tunnel 中…約 30 秒', 'running');
          apiFetch('POST', '/node/renew-tunnel', {}).then(() => {
            pollUntilNodeUp('✅ Tunnel 已重建，新 URL 已同步');
          }).catch(e => opShowAuto('❌ 重建失敗：' + e.message, 'err'));
        }
      });
      break;

    case 'pick-vault': {
      // 優先使用 pywebview 原生對話框（從視窗本身生成，天然置頂，無 Z-order 問題）
      // 開發環境不在 pywebview 裡時，回退到 HTTP API
      const initial = state.settingsData?.vault_path || '';
      const applyPath = path => {
        opClear();
        if (path) {
          if (!state.settingsData) state.settingsData = {};
          state.settingsData.vault_path = path;
          state.vaultDirty = true;
          if (state.tab === 'settings') { $('#content').innerHTML = renderSettings(); wireTab(); }
          toast('已選擇新路徑，請點「儲存設定」確認');
        }
      };
      opShow('正在開啟資料夾選擇視窗…', 'running');
      if (window.pywebview?.api?.pick_folder) {
        // pywebview 環境：使用 js_api 橋接，對話框由視窗自己開啟
        window.pywebview.api.pick_folder(initial)
          .then(path => applyPath(path))
          .catch(e => { opClear(); toast('❌ 開啟對話框失敗：' + e.message); });
      } else {
        // 非 pywebview 環境（瀏覽器直接開啟）：回退到 HTTP API
        apiFetch('POST', '/settings/pick-vault', {})
          .then(result => applyPath(result.ok ? (result.path || '') : ''))
          .catch(e => { opClear(); toast('❌ 開啟對話框失敗：' + e.message); });
      }
      break;
    }

    case 'open-gpt':
      if (btn.dataset.url) window.open(btn.dataset.url, '_blank');
      break;

    case 'show-reauth':
      // handled in wireTab
      break;

    case 'send-otp': {
      const email = $('#reauth-email')?.value?.trim();
      const hint  = $('#reauth-hint');
      if (!email) { if(hint) hint.textContent = '請輸入 Email'; return; }
      if(hint) hint.textContent = '發送中…';
      apiFetch('POST', '/reauth/request', { email }).then(() => {
        if(hint) hint.textContent = '✅ 驗證碼已發送，請檢查信箱';
        const otpRow = $('#otp-row');
        if(otpRow) otpRow.hidden = false;
      }).catch(e => { if(hint) hint.textContent = '❌ 發送失敗：' + e.message; });
      break;
    }

    case 'verify-otp': {
      const email = $('#reauth-email')?.value?.trim();
      const otp   = $('#reauth-otp')?.value?.trim();
      const hint  = $('#reauth-hint');
      if (!otp) { if(hint) hint.textContent = '請輸入驗證碼'; return; }
      if(hint) hint.textContent = '驗證中…';
      apiFetch('POST', '/reauth/verify', { email, otp }).then(result => {
        if(hint) hint.textContent = `✅ 登入成功！Token 有效期剩 ${result.token_days_remaining ?? '?'} 天`;
        const form = $('#reauth-form');
        if(form) form.hidden = true;
        loadSettingsAndRender();
      }).catch(e => { if(hint) hint.textContent = '❌ 驗證失敗：' + e.message; });
      break;
    }

    case 'save-settings': {
      const statusEl = $('#save-status');
      if(statusEl) statusEl.textContent = '儲存中…';
      const body = {
        auto_start: $('#toggle-autostart')?.checked ?? false,
        refresh_interval_seconds: parseInt($('#sel-refresh-settings')?.value ?? 30)
      };
      // 如果使用者剛剛選擇了新的 vault 路徑，一起儲存
      if (state.vaultDirty && state.settingsData?.vault_path) {
        body.vault_path = state.settingsData.vault_path;
      }
      apiFetch('PUT', '/settings', body).then(result => {
        state.vaultDirty = false;
        if(statusEl) statusEl.textContent = result.restart_required ? '✅ 已儲存（重啟 Node 後生效）' : '✅ 已儲存';
        setRefreshInterval(body.refresh_interval_seconds);
        // 更新設定顯示（清除 dirty 警告）
        if (state.tab === 'settings') { $('#content').innerHTML = renderSettings(); wireTab(); }
        setTimeout(() => { if($('#save-status')) $('#save-status').textContent = ''; }, 4000);
      }).catch(e => {
        if(statusEl) statusEl.textContent = '❌ 儲存失敗：' + e.message;
      });
      break;
    }

    case 'logout':
      showConfirm({
        kind: 'danger', title: '登出此 Node？',
        body: '將清除本機儲存的存取權杖。下次啟動 Node 時需要重新驗證 email 才能繼續同步。',
        confirm: '確認登出',
        onConfirm: () => {
          apiFetch('POST', '/logout', {})
            .then(() => { toast('已登出 · 請重新驗證'); setTimeout(loadSettingsAndRender, 500); })
            .catch(e => toast('❌ 登出失敗：' + e.message));
        }
      });
      break;

    case 'clear-logs': {
      const stream = $('#log-stream');
      if(stream) stream.innerHTML = `<div style="color:var(--text-mute);font-size:11px;padding:6px 0">— 顯示已清除（log 檔保留）—</div>`;
      break;
    }
  }
}

/* ── Poll until Node is back online ─────────────────────────────────── */
function pollUntilNodeUp(successMsg, maxMs = 90000) {
  const start = Date.now();
  const tick = () => {
    if (Date.now() - start > maxMs) {
      opShowAuto('❌ 等待逾時，Node 可能仍在重啟中', 'err');
      return;
    }
    apiFetch('GET', '/status').then(data => {
      if (data.node?.status === 'ok') {
        state.statusData = data;
        opShowAuto(successMsg, 'ok');
        if (state.tab === 'status') { $('#content').innerHTML = renderStatus(); wireTab(); }
      } else {
        setTimeout(tick, 3000);
      }
    }).catch(() => setTimeout(tick, 3000));
  };
  // first check after 8s (Node needs time to restart)
  setTimeout(tick, 8000);
}

/* ====================================================================
   Confirm dialog
   ==================================================================== */
function showConfirm({ kind='warn', title, body, confirm='確認', onConfirm }) {
  const veil = document.createElement('div');
  veil.className = 'veil';
  veil.innerHTML = `
    <div class="dialog" role="dialog">
      <div class="dh">
        <div class="dhi ${kind==='danger'?'danger':''}">
          ${kind==='danger'
            ? `<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.4"/><path d="M8 5v3.5M8 11v.3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`
            : `<svg viewBox="0 0 16 16" fill="none"><path d="M8 1.5L1.5 13h13L8 1.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6v3M8 11v.3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`}
        </div>
        <h3>${title}</h3>
      </div>
      <p class="dbody">${body}</p>
      <div class="dfoot">
        <button class="btn btn-sm btn-ghost" data-cancel>取消</button>
        <button class="btn btn-sm ${kind==='danger'?'btn-danger':''}" data-confirm>${confirm}</button>
      </div>
    </div>
  `;
  $('#window').appendChild(veil);
  const close = () => veil.remove();
  veil.addEventListener('click', e => {
    if (e.target === veil || e.target.closest('[data-cancel]')) close();
    if (e.target.closest('[data-confirm]')) { close(); onConfirm?.(); }
  });
  const esc = e => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); } };
  document.addEventListener('keydown', esc);
}

/* ====================================================================
   Toast
   ==================================================================== */
function toast(msg) {
  $$('.toast').forEach(t => t.remove());
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<span class="tk"><svg width="11" height="11" viewBox="0 0 16 16" fill="none"><path d="M3 8l3 3 7-7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span>${msg}</span>`;
  $('#window').appendChild(t);
  setTimeout(() => { t.style.transition = 'opacity .2s, transform .2s'; t.style.opacity = '0'; t.style.transform = 'translate(-50%, 8px)'; }, 1800);
  setTimeout(() => t.remove(), 2100);
}

/* ====================================================================
   Boot
   ==================================================================== */
render();
setRefreshInterval(30);
