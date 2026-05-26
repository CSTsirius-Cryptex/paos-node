/* installer.js — PAOS Node 安裝精靈前端邏輯 */
"use strict";

// ── 狀態 ─────────────────────────────────────────────────────────
const state = {
  currentStep: 1,
  vault:     null,   // 選擇的 Vault 路徑
  name:      null,
  email:     null,
  token:     null,
  gptCount:  0,
};

// ── DOM 捷徑 ─────────────────────────────────────────────────────
const $  = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => (root || document).querySelectorAll(sel);

const btnBack   = $("#btn-back");
const btnNext   = $("#btn-next");
const btnFinish = $("#btn-finish");

// ── 步驟導航 ─────────────────────────────────────────────────────
function goTo(n) {
  // 隱藏舊步驟
  $$(".inst-step").forEach(s => s.classList.remove("active"));
  $(`#step-${n}`).classList.add("active");

  // 更新步驟指示器
  $$(".step-item").forEach(item => {
    const num = parseInt(item.dataset.step);
    item.classList.remove("active", "done");
    if (num < n)  item.classList.add("done");
    if (num === n) item.classList.add("active");
  });

  // 更新按鈕顯示
  btnBack.hidden   = (n === 1);
  btnNext.hidden   = (n === 5);
  btnFinish.hidden = (n !== 5);
  btnNext.disabled = true;

  state.currentStep = n;

  // 觸發各步驟進入邏輯
  if (n === 1) enterStep1();
  if (n === 4) enterStep4();
  if (n === 5) enterStep5();
}

// ── 工具 ─────────────────────────────────────────────────────────
function api(method, ...args) {
  return window.pywebview.api[method](...args);
}

function setHint(el, msg, type) {
  el.textContent = msg;
  el.className = "field-hint" + (type ? " " + type : "");
}

// ── Step 1：環境確認 ──────────────────────────────────────────────
function setEnvItem(id, ok, detail) {
  const el = $(`#${id}`);
  el.classList.remove("loading", "ok", "error");
  el.classList.add(ok ? "ok" : "error");
  el.querySelector(".env-icon").textContent  = ok ? "✅" : "❌";
  el.querySelector(".env-detail").textContent = detail;
}

function enterStep1() {
  // 重置所有為 loading
  ["env-python","env-cloudflared","env-port","env-dir"].forEach(id => {
    const el = $(`#${id}`);
    el.className = "env-item loading";
    el.querySelector(".env-icon").textContent  = "⏳";
    el.querySelector(".env-detail").textContent = "檢查中…";
  });
  $("#cloudflared-guide").hidden = true;
  $("#env-hint").hidden = true;
  btnNext.disabled = true;

  api("check_environment").then(r => {
    setEnvItem("env-python",      r.python.ok,       r.python.ok ? `Python ${r.python.version}` : r.python.note || "不可用");
    setEnvItem("env-cloudflared", r.cloudflared.ok,  r.cloudflared.ok ? r.cloudflared.version.split(" ").slice(0,3).join(" ") : (r.cloudflared.note || "未安裝"));
    setEnvItem("env-port",        r.port.ok,         r.port.note);
    setEnvItem("env-dir",         r.install_dir.ok,  r.install_dir.ok ? r.install_dir.path : (r.install_dir.note || r.install_dir.path));

    if (!r.cloudflared.ok) {
      $("#cloudflared-guide").hidden = false;
    }
    if (!r.all_ok) {
      const hint = $("#env-hint");
      hint.hidden = false;
      hint.textContent = "請修正上方紅色項目後點「重新檢查」。";
    } else {
      btnNext.disabled = false;
    }
  }).catch(err => {
    const hint = $("#env-hint");
    hint.hidden = false;
    hint.textContent = `環境偵測失敗：${err}`;
  });
}

// 重新檢查
$("#btn-recheck").addEventListener("click", () => enterStep1());

// ── Step 2：記憶庫路徑 ────────────────────────────────────────────
$("#btn-browse").addEventListener("click", () => {
  api("browse_folder").then(path => {
    if (!path) return;
    const input = $("#vault-path");
    input.value = path;

    api("validate_vault", path).then(r => {
      const hint = $("#vault-hint");
      if (r.ok) {
        setHint(hint, "✅ 路徑有效，可讀寫", "ok");
        state.vault = path;

        // 預覽子路徑
        const preview = $("#path-preview");
        preview.hidden = false;
        const slash = path.endsWith("/") ? "" : "/";
        $("#preview-notes").textContent       = path + slash + "PAOS/notes/";
        $("#preview-attachments").textContent = path + slash + "PAOS/attachments/";
        $("#preview-agents").textContent      = path + slash + "agents/";

        btnNext.disabled = false;
      } else {
        setHint(hint, `❌ ${r.note}`, "error");
        state.vault = null;
        $("#path-preview").hidden = true;
        btnNext.disabled = true;
      }
    });
  });
});

// ── Step 3：OTP 登入 ──────────────────────────────────────────────
let _otpEmail = null;

$("#btn-send-otp").addEventListener("click", () => {
  const email = $("#otp-email").value.trim();
  const name  = $("#otp-name").value.trim();
  if (!email) {
    setHint($("#otp-hint"), "❌ 請輸入 Email", "error");
    return;
  }

  $("#btn-send-otp").disabled = true;
  setHint($("#otp-hint"), "發送中…", "");

  api("request_otp", email, name).then(r => {
    if (r.ok) {
      _otpEmail   = email;
      state.email = email;
      state.name  = name;
      $("#otp-group").hidden = false;
      setHint($("#otp-hint"), "✅ 驗證碼已寄出，請查看信箱", "ok");
      $("#otp-code").focus();
    } else {
      setHint($("#otp-hint"), `❌ ${r.note}`, "error");
    }
  }).catch(e => {
    setHint($("#otp-hint"), `❌ ${e}`, "error");
  }).finally(() => {
    $("#btn-send-otp").disabled = false;
  });
});

$("#btn-verify-otp").addEventListener("click", () => {
  const otp = $("#otp-code").value.trim();
  if (!otp || !_otpEmail) return;

  $("#btn-verify-otp").disabled = true;
  setHint($("#otp-hint"), "驗證中…", "");

  api("verify_otp", _otpEmail, otp).then(r => {
    if (r.ok) {
      state.token    = r.token;
      state.email    = r.email;
      state.gptCount = r.gpt_count || 0;

      $("#login-success").hidden = false;
      $("#login-gpt-count").textContent =
        state.gptCount > 0 ? `你目前有 ${state.gptCount} 個 GPT 助理` : "";
      setHint($("#otp-hint"), "", "");
      btnNext.disabled = false;
    } else {
      setHint($("#otp-hint"), `❌ ${r.note}`, "error");
      $("#btn-verify-otp").disabled = false;
    }
  }).catch(e => {
    setHint($("#otp-hint"), `❌ ${e}`, "error");
    $("#btn-verify-otp").disabled = false;
  });
});

// ── Step 4：建立通道 ──────────────────────────────────────────────
function setTStep(id, status, label) {
  // status: 'waiting' | 'running' | 'ok' | 'error'
  const el = $(`#${id}`);
  el.classList.remove("ok", "error", "running");
  if (status !== "waiting") el.classList.add(status);

  const icons = { waiting: "⏸", running: "⏳", ok: "✅", error: "❌" };
  el.querySelector(".tstep-icon").textContent = icons[status] || "⏸";
  if (label) el.querySelector(".tstep-label").textContent = label;
}

function enterStep4() {
  setTStep("tstep-start",    "running", "啟動 cloudflared…");
  setTStep("tstep-url",      "waiting", "取得公開 URL");
  setTStep("tstep-register", "waiting", "向 Central 登錄");
  $("#tunnel-url-display").hidden = true;
  $("#tunnel-hint").textContent = "";

  api("start_tunnel", state.token).then(r => {
    if (r.ok) {
      setTStep("tstep-start",    "ok",      "cloudflared 已啟動");
      setTStep("tstep-url",      "ok",      `URL 取得：${r.url}`);
      setTStep("tstep-register", "ok",      "已向 Central 登錄");

      const disp = $("#tunnel-url-display");
      disp.hidden = false;
      $("#tunnel-url-value").textContent = r.url;

      btnNext.disabled = false;
    } else {
      setTStep("tstep-start", "error", "啟動失敗");
      setTStep("tstep-url",   "error", "");
      setTStep("tstep-register", "error", "");
      $("#tunnel-hint").textContent = r.note || "未知錯誤";
    }
  }).catch(e => {
    setTStep("tstep-start", "error", String(e));
  });
}

// ── Step 5：完成安裝 ──────────────────────────────────────────────
function setFItem(id, ok, text) {
  const el = $(`#${id}`);
  el.classList.remove("ok", "error");
  el.classList.add(ok ? "ok" : "error");
  el.textContent = (ok ? "✅ " : "❌ ") + text;
}

function enterStep5() {
  // 重置 finish items
  [["fitem-env","環境設定檔（.env）"],
   ["fitem-node-task","PAOS-Node 排程工作"],
   ["fitem-panel-task","PAOS-Node-控制台 排程工作"],
   ["fitem-shortcut","桌面捷徑"]].forEach(([id, label]) => {
    const el = $(`#${id}`);
    el.className = "finish-item";
    el.textContent = `⏳ ${label}`;
  });
  $("#finish-note").hidden = true;
  btnFinish.disabled = true;

  api("run_setup", state.vault, state.token, state.email).then(r => {
    const envOk     = r.steps?.env?.ok ?? false;
    const tasksData = r.steps?.tasks ?? {};
    const nodeTask  = tasksData.tasks?.["PAOS-Node"]?.ok ?? false;
    const panelTask = tasksData.tasks?.["PAOS-Node-控制台"]?.ok ?? false;
    const shortcut  = r.steps?.shortcut?.ok ?? false;

    setFItem("fitem-env",        envOk,     "環境設定檔（.env）");
    setFItem("fitem-node-task",  nodeTask,  "PAOS-Node 排程工作");
    setFItem("fitem-panel-task", panelTask, "PAOS-Node-控制台 排程工作");
    setFItem("fitem-shortcut",   shortcut,  "桌面捷徑");

    if (!r.ok) {
      const note = $("#finish-note");
      note.hidden = false;
      const errors = [];
      if (!envOk)    errors.push("• .env 寫入失敗：" + (r.steps?.env?.note || ""));
      if (!nodeTask) errors.push("• PAOS-Node 排程工作安裝失敗");
      if (!panelTask) errors.push("• 控制台排程工作安裝失敗");
      if (!shortcut) errors.push("• 桌面捷徑建立失敗（可手動右鍵 launch-panel.vbs → 傳送到桌面）");
      $("#finish-error-detail").textContent = errors.join("\n");
    }

    btnFinish.disabled = false;
  }).catch(e => {
    $("#finish-note").hidden = false;
    $("#finish-error-detail").textContent = String(e);
    btnFinish.disabled = false;
  });
}

// ── 底部按鈕事件 ──────────────────────────────────────────────────
btnBack.addEventListener("click", () => {
  if (state.currentStep > 1) goTo(state.currentStep - 1);
});

btnNext.addEventListener("click", () => {
  if (state.currentStep < 5) goTo(state.currentStep + 1);
});

btnFinish.addEventListener("click", () => {
  // 嘗試啟動 Node + 關閉安裝視窗
  if (window.pywebview?.api?.launch_panel) {
    api("launch_panel").finally(() => window.close());
  } else {
    window.close();
  }
});

// ── 初始化 ───────────────────────────────────────────────────────
// pywebview 在 window.onload 後 API 才就緒，稍作等待
function waitForApi(cb, tries = 0) {
  if (window.pywebview?.api) {
    cb();
  } else if (tries < 30) {
    setTimeout(() => waitForApi(cb, tries + 1), 100);
  }
}

waitForApi(() => {
  goTo(1);
});
