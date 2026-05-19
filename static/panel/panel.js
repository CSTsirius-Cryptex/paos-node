/**
 * panel.js — PAOS Node 控制台前端骨架
 * fetch 邏輯 + tab 切換 + 基本渲染
 * 視覺樣式等 Claude Design 設計稿後補（panel.css）
 */

const API = '/panel/api';

// ── Tab 切換 ──────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(s => s.hidden = true);
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name);
    b.setAttribute('aria-selected', b.dataset.tab === name ? 'true' : 'false');
  });
  const target = document.getElementById(`tab-${name}`);
  if (target) target.hidden = false;

  // 切換到 Tab 時自動載入資料
  if (name === 'status')   loadStatus();
  if (name === 'gpts')     loadGpts();
  if (name === 'settings') loadSettings();
  if (name === 'logs')     loadLogs();
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ── 自動刷新 ─────────────────────────────────────────────────────
let refreshTimer = null;
function setRefreshInterval(seconds) {
  clearInterval(refreshTimer);
  if (seconds > 0) {
    refreshTimer = setInterval(loadStatus, seconds * 1000);
  }
}

document.getElementById('refresh-interval').addEventListener('change', e => {
  const sec = parseInt(e.target.value);
  setRefreshInterval(sec);
  // 同步到設定（非同步，不等待）
  apiFetch('PUT', '/settings', { refresh_interval_seconds: sec }).catch(() => {});
});

// ── 狀態燈輔助 ───────────────────────────────────────────────────
function setDot(key, state) {
  const dot = document.querySelector(`.status-item[data-key="${key}"] .status-dot`);
  if (dot) dot.dataset.state = state; // ok | error | unknown
}
function setMeta(metaKey, text) {
  const el = document.querySelector(`[data-meta="${metaKey}"]`);
  if (el) el.textContent = text || '';
}

// ── API 呼叫輔助 ─────────────────────────────────────────────────
async function apiFetch(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(API + path, opts);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// ── CP-1：載入狀態 ────────────────────────────────────────────────
async function loadStatus() {
  try {
    const data = await apiFetch('GET', '/status');
    // scheduler
    setDot('scheduler', data.scheduler?.status === 'running' ? 'ok' : 'error');
    // node
    setDot('node', data.node?.status === 'ok' ? 'ok' : 'error');
    setMeta('node-latency', data.node?.latency_ms != null ? `${data.node.latency_ms}ms` : '');
    // vault
    setDot('vault', data.vault?.status === 'ok' ? 'ok' : 'error');
    // tunnel
    const tunnelOk = data.tunnel?.status === 'connected';
    setDot('tunnel', tunnelOk ? 'ok' : 'error');
    const tunnelEl = document.querySelector('[data-meta="tunnel-url"]');
    if (tunnelEl) {
      tunnelEl.textContent = tunnelOk ? data.tunnel.url : '';
      tunnelEl.style.display = tunnelOk ? '' : 'none';
    }
    // central
    setDot('central', data.central?.status === 'ok' ? 'ok' : 'error');
    setMeta('central-latency', data.central?.latency_ms != null ? `${data.central.latency_ms}ms` : '');
    // registered
    setDot('registered', data.registered?.status === 'ok' ? 'ok' : 'error');
  } catch (e) {
    console.error('[loadStatus]', e);
  }
}

// 複製 Tunnel URL
document.querySelector('[data-meta="tunnel-url"]')?.addEventListener('click', function () {
  if (this.textContent) navigator.clipboard.writeText(this.textContent);
});

// CP-1 按鈕
document.getElementById('btn-refresh-status').addEventListener('click', loadStatus);

document.getElementById('btn-diagnose').addEventListener('click', async () => {
  const resultDiv = document.getElementById('diagnose-result');
  const stepsList = document.getElementById('diagnose-steps');
  resultDiv.hidden = false;
  stepsList.innerHTML = '<li class="diagnosing">診斷中…</li>';

  try {
    const data = await apiFetch('GET', '/diagnose');
    stepsList.innerHTML = '';
    data.steps.forEach(s => {
      const li = document.createElement('li');
      li.className = `diagnose-step step-${s.status}`;
      const icon = s.status === 'ok' ? '✅' : '❌';
      const detail = s.detail || s.url || s.node_url || '';
      const latency = s.latency_ms != null ? ` (${s.latency_ms}ms)` : '';
      li.textContent = `${icon} ${s.name}${latency}  ${detail}`;
      stepsList.appendChild(li);
    });
  } catch (e) {
    stepsList.innerHTML = `<li class="step-error">診斷失敗：${e.message}</li>`;
  }
});

document.getElementById('btn-start-node').addEventListener('click', () => {
  apiFetch('POST', '/node/start', {}).catch(() => {});
});
document.getElementById('btn-restart-node').addEventListener('click', () => {
  showConfirm('確定要重啟 Node 嗎？', () => {
    apiFetch('POST', '/node/restart', {}).catch(() => {});
  });
});
document.getElementById('btn-repair').addEventListener('click', () => {
  apiFetch('POST', '/node/repair', {}).catch(() => {});
});

// ── CP-2：載入 GPT 清單 ───────────────────────────────────────────
async function loadGpts() {
  const list  = document.getElementById('gpt-list');
  const empty = document.getElementById('gpts-empty');
  const error = document.getElementById('gpts-error');
  const errMsg = document.getElementById('gpts-error-msg');

  list.innerHTML = '';
  empty.hidden = true;
  error.hidden = true;

  try {
    const data = await apiFetch('GET', '/gpts');
    if (data.note) {
      errMsg.textContent = data.note;
      error.hidden = false;
      return;
    }
    const gpts = data.gpts || [];
    if (!gpts.length) { empty.hidden = false; return; }

    gpts.forEach(g => {
      const card = document.createElement('article');
      card.className = 'gpt-card' + (g.has_access === false ? ' gpt-card--disabled' : '');

      const expires = g.expires_at
        ? `授權至：${new Date(g.expires_at).toLocaleDateString('zh-TW')}`
        : '授權至：永久';
      const owner = g.owner_name ? `擁有者：${g.owner_name}` : '';

      card.innerHTML = `
        <h3 class="gpt-name">${g.name}</h3>
        <p class="gpt-desc">${g.description || ''}</p>
        <div class="gpt-meta">
          <span>${owner}</span>
          <span>${expires}</span>
        </div>
        <div class="gpt-actions">
          ${g.has_access !== false && g.chatgpt_url
            ? `<a class="btn-open-gpt" href="${g.chatgpt_url}" target="_blank">開啟助理 →</a>`
            : `<span class="gpt-disabled-badge">已停用</span>${g.owner_email ? `<span class="gpt-owner-contact">${g.owner_email}</span>` : ''}`
          }
        </div>
      `;
      list.appendChild(card);
    });
  } catch (e) {
    errMsg.textContent = `載入失敗：${e.message}`;
    error.hidden = false;
  }
}

document.getElementById('btn-refresh-gpts').addEventListener('click', loadGpts);

// ── CP-3：載入設定 ────────────────────────────────────────────────
async function loadSettings() {
  try {
    const d = await apiFetch('GET', '/settings');

    document.getElementById('setting-vault-path').value = d.vault_path || '';
    document.getElementById('setting-attachment-path').textContent =
      d.vault_path && d.attachment_default_path
        ? `${d.vault_path}/${d.attachment_default_path}`
        : d.attachment_default_path || '';
    document.getElementById('setting-auto-start').checked = !!d.auto_start;
    document.getElementById('setting-tunnel-url').textContent = d.tunnel_url || '（未取得）';
    document.getElementById('setting-email').textContent = d.owner_email || '—';

    // 刷新間隔同步
    const selSetting = document.getElementById('setting-refresh-interval');
    selSetting.value = String(d.refresh_interval_seconds ?? 30);
    document.getElementById('refresh-interval').value = String(d.refresh_interval_seconds ?? 30);
    setRefreshInterval(d.refresh_interval_seconds ?? 30);

    // Token 狀態
    const tokenEl = document.getElementById('setting-token-status');
    if (d.token_days_remaining != null) {
      tokenEl.textContent = d.token_days_remaining > 0
        ? `✅ 有效（剩 ${d.token_days_remaining} 天）`
        : '❌ 已過期，請重新登入';
      tokenEl.className = 'setting-readonly-text ' +
        (d.token_days_remaining > 0 ? 'token-ok' : 'token-expired');
    } else {
      tokenEl.textContent = '⚠️ 未設定';
      tokenEl.className = 'setting-readonly-text token-missing';
    }

    // reauth email 預填
    if (d.owner_email) document.getElementById('reauth-email').value = d.owner_email;
  } catch (e) {
    console.error('[loadSettings]', e);
  }
}

// 儲存設定
document.getElementById('btn-save-settings').addEventListener('click', async () => {
  const status = document.getElementById('save-status');
  status.textContent = '儲存中…';
  try {
    const body = {
      auto_start: document.getElementById('setting-auto-start').checked,
      refresh_interval_seconds: parseInt(document.getElementById('setting-refresh-interval').value),
    };
    const result = await apiFetch('PUT', '/settings', body);
    status.textContent = result.restart_required ? '✅ 已儲存（部分設定需重啟生效）' : '✅ 已儲存';
  } catch (e) {
    status.textContent = `❌ 儲存失敗：${e.message}`;
  }
  setTimeout(() => { status.textContent = ''; }, 4000);
});

// 複製 Tunnel URL
document.getElementById('btn-copy-tunnel-url').addEventListener('click', () => {
  const url = document.getElementById('setting-tunnel-url').textContent;
  if (url && url !== '（未取得）') navigator.clipboard.writeText(url);
});

// 重新建立 Tunnel
document.getElementById('btn-renew-tunnel').addEventListener('click', () => {
  showConfirm('確定要重新建立 Tunnel 並重新登錄 Central 嗎？\n（目前 Tunnel URL 將會改變）', () => {
    apiFetch('POST', '/node/renew-tunnel', {}).catch(() => {});
  });
});

// 重新登入：顯示/隱藏表單
document.getElementById('btn-reauth').addEventListener('click', () => {
  const form = document.getElementById('reauth-form');
  form.hidden = !form.hidden;
});

// 發送 OTP
document.getElementById('btn-send-otp').addEventListener('click', async () => {
  const email = document.getElementById('reauth-email').value.trim();
  const hint  = document.getElementById('reauth-hint');
  if (!email) { hint.textContent = '請輸入 Email'; return; }
  hint.textContent = '發送中…';
  try {
    await apiFetch('POST', '/reauth/request', { email });
    hint.textContent = '✅ 驗證碼已發送，請檢查信箱';
    document.getElementById('otp-row').hidden = false;
  } catch (e) {
    hint.textContent = `❌ 發送失敗：${e.message}`;
  }
});

// 驗證 OTP
document.getElementById('btn-verify-otp').addEventListener('click', async () => {
  const email = document.getElementById('reauth-email').value.trim();
  const otp   = document.getElementById('reauth-otp').value.trim();
  const hint  = document.getElementById('reauth-hint');
  if (!otp) { hint.textContent = '請輸入驗證碼'; return; }
  hint.textContent = '驗證中…';
  try {
    const result = await apiFetch('POST', '/reauth/verify', { email, otp });
    hint.textContent = `✅ 登入成功！Token 有效期剩 ${result.token_days_remaining ?? '?'} 天`;
    document.getElementById('reauth-form').hidden = true;
    document.getElementById('otp-row').hidden = true;
    document.getElementById('reauth-otp').value = '';
    loadSettings(); // 重新載入顯示新 token 狀態
  } catch (e) {
    hint.textContent = `❌ 驗證失敗：${e.message}`;
  }
});

// 登出
document.getElementById('btn-logout').addEventListener('click', () => {
  showConfirm('確定要登出嗎？\n（CENTRAL_OWNER_TOKEN 將被清除，Node 重啟後無法自動登錄 Central）', () => {
    apiFetch('PUT', '/settings', {}).catch(() => {});
    // 清除 token（透過 reauth/verify 的反向操作——直接寫空值）
    fetch(API + '/reauth/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: '', otp: '__logout__' }) }).catch(() => {});
  });
});

// ── CP-4：執行記錄 ────────────────────────────────────────────────
let logsAutoScroll = true;

async function loadLogs() {
  try {
    const data = await apiFetch('GET', '/logs?lines=200');
    const pre  = document.getElementById('log-content');
    pre.textContent = data.lines.join('\n');
    if (logsAutoScroll) {
      const output = document.getElementById('log-output');
      output.scrollTop = output.scrollHeight;
    }
  } catch (e) {
    console.error('[loadLogs]', e);
  }
}

document.getElementById('log-auto-scroll').addEventListener('change', e => {
  logsAutoScroll = e.target.checked;
});

document.getElementById('btn-refresh-logs').addEventListener('click', loadLogs);

document.getElementById('btn-clear-logs').addEventListener('click', () => {
  document.getElementById('log-content').textContent = '';
});

// ── 確認對話框 ────────────────────────────────────────────────────
function showConfirm(message, onOk) {
  const dialog = document.getElementById('confirm-dialog');
  document.getElementById('confirm-message').textContent = message;
  dialog.showModal();
  document.getElementById('confirm-ok').onclick = () => { dialog.close(); onOk(); };
  document.getElementById('confirm-cancel').onclick = () => dialog.close();
}

// ── 啟動 ─────────────────────────────────────────────────────────
switchTab('status');
setRefreshInterval(30); // 初始刷新間隔，loadSettings 後會更新
