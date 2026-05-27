/* installer.js — PAOS Node 安裝精靈前端邏輯 (v3) */
"use strict";

// ── 狀態 ─────────────────────────────────────────────────────────
const state = {
  currentStep: 1,
  installDir:  null,   // 安裝目錄（Step 2 確認）
  vault:       null,   // Vault 根目錄（Step 3 確認）
  name:        null,
  email:       null,
  token:       null,
  gptCount:    0,
  gptNames:    [],     // GPT 助理名稱清單（Step 4 登入後取得）
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
  btnNext.hidden   = (n === 6);
  btnFinish.hidden = (n !== 6);
  btnNext.disabled = true;

  state.currentStep = n;

  // 觸發各步驟進入邏輯
  if (n === 1) enterStep1();
  if (n === 2) enterStep2();
  if (n === 3) checkObsidianStatus();  // 進入記憶庫步驟時自動檢查 Obsidian
  if (n === 5) enterStep5();
  if (n === 6) enterStep6();
}

// ── 工具 ─────────────────────────────────────────────────────────
function api(method, ...args) {
  return window.pywebview.api[method](...args);
}

function openExternal(url) {
  api("open_url", url);
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
  ["env-python", "env-cloudflared", "env-port"].forEach(id => {
    const el = $(`#${id}`);
    el.className = "env-item loading";
    el.querySelector(".env-icon").textContent   = "⏳";
    el.querySelector(".env-detail").textContent = "檢查中…";
  });
  ["python-guide", "cloudflared-guide", "env-hint"].forEach(id => {
    const el = $(`#${id}`);
    if (el) el.hidden = true;
  });
  // 重置進度條
  ["py-progress", "cf-progress"].forEach(id => {
    const el = $(`#${id}`);
    if (el) el.hidden = true;
  });
  ["py-progress-bar", "cf-progress-bar"].forEach(id => {
    const el = $(`#${id}`);
    if (el) { el.style.width = "0%"; el.style.background = "var(--purple)"; }
  });
  // 重新啟用自動安裝按鈕（避免上次錯誤後按鈕仍停用）
  ["btn-auto-install-py", "btn-auto-install-cf"].forEach(id => {
    const el = $(`#${id}`);
    if (el) el.disabled = false;
  });
  // 重置進度標籤
  ["py-progress-label", "cf-progress-label"].forEach(id => {
    const el = $(`#${id}`);
    if (el) { el.textContent = "準備中…"; el.style.color = ""; }
  });
  btnNext.disabled = true;

  api("check_environment").then(r => {
    setEnvItem("env-python",
      r.python.ok,
      r.python.ok ? `Python ${r.python.version}` : (r.python.note || "不可用"));
    setEnvItem("env-cloudflared",
      r.cloudflared.ok,
      r.cloudflared.ok
        ? r.cloudflared.version.split(" ").slice(0, 3).join(" ")
        : (r.cloudflared.note || "未安裝"));
    setEnvItem("env-port",
      r.port.ok,
      r.port.note);

    if (!r.python.ok)     { $("#python-guide").hidden = false; }
    if (!r.cloudflared.ok){ $("#cloudflared-guide").hidden = false; }

    if (!r.all_ok) {
      const hint = $("#env-hint");
      hint.hidden = false;
      hint.textContent = "請修正上方紅色項目後點「重新檢查」。所有項目都需為最新版本才能繼續。";
    } else {
      btnNext.disabled = false;
    }
  }).catch(err => {
    const hint = $("#env-hint");
    hint.hidden = false;
    hint.textContent = `環境偵測失敗：${err}`;
  });
}

// ── Step 1 按鈕事件 ──────────────────────────────────────────────

// 重新檢查按鈕（Step 1）
["btn-recheck-py", "btn-recheck-cf"].forEach(id => {
  const el = $(`#${id}`);
  if (el) el.addEventListener("click", () => enterStep1());
});

// 自動安裝 Python
$("#btn-auto-install-py").addEventListener("click", () => {
  const btn     = $("#btn-auto-install-py");
  const progress = $("#py-progress");
  const bar     = $("#py-progress-bar");
  const label   = $("#py-progress-label");

  btn.disabled    = true;
  progress.hidden = false;
  bar.style.width = "5%";
  bar.style.background = "var(--purple)";
  label.style.color    = "";
  label.textContent    = "正在透過 winget 安裝 Python…（約 1–3 分鐘，請稍候）";

  let fakePct = 5;
  const ticker = setInterval(() => {
    if (fakePct < 85) {
      fakePct += Math.random() * 0.8;
      bar.style.width = fakePct + "%";
    }
  }, 1500);

  api("download_python").then(r => {
    clearInterval(ticker);
    if (r.ok) {
      bar.style.width   = "100%";
      label.textContent = "✅ Python 安裝完成！正在重新檢查環境…";
      label.style.color = "#15803d";
      setTimeout(() => enterStep1(), 1500);
    } else {
      bar.style.width      = "100%";
      bar.style.background = "var(--red)";
      label.textContent    = "❌ " + (r.note || "安裝失敗，請手動安裝 Python");
      label.style.color    = "var(--red)";
      btn.disabled = false;
    }
  }).catch(e => {
    clearInterval(ticker);
    bar.style.background = "var(--red)";
    label.textContent    = "❌ " + String(e);
    label.style.color    = "var(--red)";
    btn.disabled = false;
  });
});

// 自動安裝 cloudflared
$("#btn-auto-install-cf").addEventListener("click", () => {
  const btn      = $("#btn-auto-install-cf");
  const progress = $("#cf-progress");
  const bar      = $("#cf-progress-bar");
  const label    = $("#cf-progress-label");

  btn.disabled    = true;
  progress.hidden = false;
  bar.style.width = "5%";
  bar.style.background = "var(--purple)";
  label.style.color    = "";
  label.textContent    = "連線中…";

  let fakePct = 5;
  const ticker = setInterval(() => {
    if (fakePct < 88) {
      fakePct += Math.random() * 3;
      bar.style.width = fakePct + "%";
    }
  }, 500);

  api("download_cloudflared").then(r => {
    clearInterval(ticker);
    if (r.ok) {
      bar.style.width   = "100%";
      bar.style.background = "var(--purple)";
      label.textContent = "✅ 安裝成功！正在重新檢查環境…";
      label.style.color = "#15803d";
      setTimeout(() => enterStep1(), 1200);
    } else {
      bar.style.width      = "100%";
      bar.style.background = "var(--red)";
      label.textContent    = "❌ " + (r.note || "下載失敗，請嘗試手動安裝");
      label.style.color    = "var(--red)";
      btn.disabled = false;
    }
  }).catch(e => {
    clearInterval(ticker);
    bar.style.background = "var(--red)";
    label.textContent    = "❌ " + String(e);
    label.style.color    = "var(--red)";
    btn.disabled = false;
  });
});

// ── Obsidian 推薦區塊（Step 3）────────────────────────────────────
function checkObsidianStatus() {
  const icon    = $("#obsidian-rec-icon");
  const sub     = $("#obsidian-rec-sub");
  const section = $("#obsidian-install-section");

  icon.textContent = "⏳";
  sub.textContent  = "（檢查中…）";
  sub.style.color  = "";

  api("check_obsidian").then(r => {
    if (r.installed) {
      icon.textContent = "✅";
      sub.textContent  = `（${r.note}）`;
      sub.style.color  = "#15803d";
      section.hidden   = true;
    } else {
      icon.textContent = "💡";
      sub.textContent  = "（尚未安裝）";
      sub.style.color  = "#b45309";
      section.hidden   = false;
    }
  }).catch(() => {
    icon.textContent = "💡";
    sub.textContent  = "（無法檢查）";
    section.hidden   = false;
  });
}

$("#btn-recheck-ob").addEventListener("click", () => checkObsidianStatus());

// 自動安裝 Obsidian（Step 3 推薦區塊）
$("#btn-auto-install-ob").addEventListener("click", () => {
  const btn      = $("#btn-auto-install-ob");
  const progress = $("#ob-progress");
  const bar      = $("#ob-progress-bar");
  const label    = $("#ob-progress-label");

  btn.disabled    = true;
  progress.hidden = false;
  bar.style.width = "5%";
  bar.style.background = "var(--purple)";
  label.style.color    = "";
  label.textContent    = "正在下載 Obsidian…（約 1–3 分鐘，請稍候）";

  let fakePct = 5;
  const ticker = setInterval(() => {
    if (fakePct < 82) { fakePct += Math.random() * 1.2; bar.style.width = fakePct + "%"; }
  }, 800);

  api("download_obsidian").then(r => {
    clearInterval(ticker);
    if (r.ok) {
      bar.style.width      = "100%";
      bar.style.background = "var(--purple)";
      label.textContent    = `✅ Obsidian 安裝完成！`;
      label.style.color    = "#15803d";
      setTimeout(() => checkObsidianStatus(), 1000);
    } else {
      bar.style.width      = "100%";
      bar.style.background = "var(--red)";
      label.textContent    = "❌ " + (r.note || "安裝失敗，請手動安裝");
      label.style.color    = "var(--red)";
      btn.disabled = false;
    }
  }).catch(e => {
    clearInterval(ticker);
    bar.style.background = "var(--red)";
    label.textContent    = "❌ " + String(e);
    label.style.color    = "var(--red)";
    btn.disabled = false;
  });
});

// ── Step 2：安裝目錄 ──────────────────────────────────────────────
function enterStep2() {
  btnNext.disabled = true;
  const input = $("#install-path");

  // 若已有值（例如從 Step 3 返回），重新驗證現有路徑
  if (input.value.trim()) {
    validateInstallDir(input.value.trim());
    return;
  }

  // 首次進入：載入預設路徑
  api("get_default_install_dir").then(defaultPath => {
    input.value = defaultPath;
    validateInstallDir(defaultPath);
  }).catch(() => {
    btnNext.disabled = true;
  });
}

function validateInstallDir(path) {
  const hint    = $("#install-hint");
  const preview = $("#install-preview");
  setHint(hint, "驗證中…", "");

  api("validate_install_dir", path).then(r => {
    if (r.ok) {
      setHint(hint, "✅ 路徑有效，可讀寫", "ok");
      state.installDir = r.path || path;

      // 預覽子路徑
      const slash = r.path.endsWith("/") ? "" : "/";
      const p = r.path;
      $("#preview-install-root").textContent = p + slash;
      $("#preview-install-venv").textContent = p + slash + "venv/";
      $("#preview-install-src").textContent  = p + slash + "src/";
      preview.hidden = false;

      btnNext.disabled = false;
    } else {
      setHint(hint, `❌ ${r.note}`, "error");
      state.installDir = null;
      preview.hidden = true;
      btnNext.disabled = true;
    }
  });
}

$("#install-path").addEventListener("blur", function() {
  const v = this.value.trim();
  if (v) validateInstallDir(v);
});

$("#btn-install-browse").addEventListener("click", () => {
  api("browse_install_dir").then(path => {
    if (!path) return;
    $("#install-path").value = path;
    validateInstallDir(path);
  });
});

// ── Step 3：記憶庫路徑 ────────────────────────────────────────────
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

// ── Step 4：帳號登入 ──────────────────────────────────────────────
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
      state.gptNames = r.gpt_names  || [];

      // 顯示登入成功
      $("#login-success").hidden = false;
      $("#login-gpt-count").textContent =
        state.gptCount > 0 ? `你目前有 ${state.gptCount} 個 GPT 助理` : "";
      setHint($("#otp-hint"), "", "");

      // 顯示 GPT 清單
      if (state.gptNames.length > 0) {
        const listEl = $("#gpt-list");
        listEl.innerHTML = state.gptNames
          .map(n => `<div class="gpt-item">🤖 ${n}</div>`)
          .join("");
        $("#gpt-list-section").hidden = false;
      }

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

// ── Step 5：建立通道 ──────────────────────────────────────────────
function setTStep(id, status, label) {
  const el = $(`#${id}`);
  el.classList.remove("ok", "error", "running");
  if (status !== "waiting") el.classList.add(status);

  const icons = { waiting: "⏸", running: "⏳", ok: "✅", error: "❌" };
  el.querySelector(".tstep-icon").textContent = icons[status] || "⏸";
  if (label) el.querySelector(".tstep-label").textContent = label;
}

function enterStep5() {
  setTStep("tstep-start",    "running", "啟動 cloudflared…");
  setTStep("tstep-url",      "waiting", "取得公開 URL");
  setTStep("tstep-register", "waiting", "向 Central 登錄");
  $("#tunnel-url-display").hidden = true;
  $("#tunnel-hint").textContent = "";

  api("start_tunnel", state.token).then(r => {
    if (r.ok) {
      setTStep("tstep-start",    "ok", "cloudflared 已啟動");
      setTStep("tstep-url",      "ok", `URL 取得：${r.url}`);
      setTStep("tstep-register", "ok", "已向 Central 登錄");

      const disp = $("#tunnel-url-display");
      disp.hidden = false;
      $("#tunnel-url-value").textContent = r.url;

      btnNext.disabled = false;
    } else {
      setTStep("tstep-start",    "error", "啟動失敗");
      setTStep("tstep-url",      "error", "");
      setTStep("tstep-register", "error", "");
      $("#tunnel-hint").textContent = r.note || "未知錯誤";
    }
  }).catch(e => {
    setTStep("tstep-start", "error", String(e));
  });
}

// ── Step 6：完成安裝 ──────────────────────────────────────────────
function setFItem(id, ok, text) {
  const el = $(`#${id}`);
  el.classList.remove("ok", "error");
  el.classList.add(ok ? "ok" : "error");
  el.textContent = (ok ? "✅ " : "❌ ") + text;
}

function enterStep6() {
  // 重置 finish items
  [
    ["fitem-deploy",     "Node 檔案部署"],
    ["fitem-venv",       "Python 套件安裝（venv）"],
    ["fitem-vault-init", "Agent Vault 初始化"],
    ["fitem-env",        "環境設定檔（.env）"],
    ["fitem-node-task",  "PAOS-Node 排程工作"],
    ["fitem-panel-task", "PAOS-Node-控制台 排程工作"],
    ["fitem-shortcut",   "桌面捷徑"],
  ].forEach(([id, label]) => {
    const el = $(`#${id}`);
    el.className = "finish-item";
    el.textContent = `⏳ ${label}`;
  });
  $("#finish-note").hidden  = true;
  $("#finish-hint").hidden  = true;
  btnFinish.disabled = true;

  api("run_setup", state.vault, state.token, state.email, state.gptNames).then(r => {
    const deployOk   = r.steps?.deploy?.ok ?? false;
    const venvOk     = r.steps?.venv?.ok   ?? false;
    const vaultOk    = r.steps?.vault_init?.ok ?? false;
    const envOk      = r.steps?.env?.ok    ?? false;
    const nodeTask   = r.steps?.tasks?.tasks?.["PAOS-Node"]?.ok          ?? false;
    const panelTask  = r.steps?.tasks?.tasks?.["PAOS-Node-控制台"]?.ok   ?? false;
    const shortcut   = r.steps?.shortcut?.ok ?? false;

    setFItem("fitem-deploy",     deployOk,  "Node 檔案部署");
    setFItem("fitem-venv",       venvOk,    "Python 套件安裝（venv）");
    setFItem("fitem-vault-init", vaultOk,   "Agent Vault 初始化");
    setFItem("fitem-env",        envOk,     "環境設定檔（.env）");
    setFItem("fitem-node-task",  nodeTask,  "PAOS-Node 排程工作");
    setFItem("fitem-panel-task", panelTask, "PAOS-Node-控制台 排程工作");
    setFItem("fitem-shortcut",   shortcut,  "桌面捷徑");

    if (!r.ok) {
      const note = $("#finish-note");
      note.hidden = false;
      const errors = [];
      if (!deployOk)  errors.push("• 檔案部署失敗：" + (r.steps?.deploy?.note   || ""));
      if (!venvOk)    errors.push("• venv 安裝失敗：" + (r.steps?.venv?.note    || ""));
      if (!vaultOk)   errors.push("• Vault 初始化失敗："  + (r.steps?.vault_init?.errors?.join(", ") || ""));
      if (!envOk)     errors.push("• .env 寫入失敗："  + (r.steps?.env?.note    || ""));
      if (!nodeTask)  errors.push("• PAOS-Node 排程失敗：" +
          (r.steps?.tasks?.tasks?.["PAOS-Node"]?.note          || ""));
      if (!panelTask) errors.push("• 控制台排程失敗：" +
          (r.steps?.tasks?.tasks?.["PAOS-Node-控制台"]?.note   || ""));
      if (!shortcut)  errors.push("• 桌面捷徑失敗："   + (r.steps?.shortcut?.note || "（可手動右鍵 launch-panel.vbs → 傳送到桌面）"));
      $("#finish-error-detail").textContent = errors.join("\n");
    }

    $("#finish-hint").hidden = false;
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
  const next = state.currentStep + 1;
  if (next > 6) return;

  // Step 2 → Step 3：確認安裝目錄
  if (state.currentStep === 2) {
    const path = $("#install-path").value.trim();
    if (!path) return;
    api("set_install_dir", path).then(() => goTo(next));
    return;
  }

  goTo(next);
});

btnFinish.addEventListener("click", () => {
  if (window.pywebview?.api?.launch_panel) {
    api("launch_panel").finally(() => window.close());
  } else {
    window.close();
  }
});

// ── 初始化 ───────────────────────────────────────────────────────
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
