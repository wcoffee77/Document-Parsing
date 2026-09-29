// doc2report 웹 화면 — 외부 라이브러리 없이 (사내망에서 CDN이 막혀 있어도 동작하도록).
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const STORE_KEY = "doc2report.options.v1";

const state = {
  inputs: [],      // {type, url|upload_id|text, name, title, detail, error}
  profiles: {},    // name -> profile_info
  schema: null,
  status: null,
  polling: null,
};

// ── 서버 호출 ────────────────────────────────────────────────────────────

async function api(path, body, extraHeaders) {
  const init = body === undefined ? {} : {
    method: "POST",
    headers: Object.assign({ "X-Doc2Report": "1" },
      body instanceof Blob ? {} : { "Content-Type": "application/json" }, extraHeaders || {}),
    body: body instanceof Blob ? body : JSON.stringify(body),
  };
  const res = await fetch(path, init);
  let data;
  try { data = await res.json(); } catch (e) { data = { ok: false, error: `응답 오류 (${res.status})` }; }
  if (!res.ok || data.ok === false) throw new Error(data.error || `요청 실패 (${res.status})`);
  return data;
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(message, bad) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), bad ? 6000 : 2500);
}

// ── 상태 표시 ────────────────────────────────────────────────────────────

async function loadStatus() {
  const st = await api("/api/status");
  state.status = st;
  const cf = $("#st-confluence");
  cf.textContent = st.confluence.configured ? "Confluence 연결 설정됨" : "Confluence 미설정";
  cf.className = "chip " + (st.confluence.configured ? "ok" : "warn");
  cf.title = st.confluence.configured
    ? `${st.confluence.url} · ${st.confluence.auth} · 전송 ${st.confluence.transport}`
    : "CONFLUENCE_URL / CONFLUENCE_API_TOKEN 환경변수가 없습니다 — scripts\\confluence_env.ps1 을 채우고 start_webapp 으로 다시 켜세요";
  const llm = $("#st-llm");
  llm.textContent = st.llm.configured ? `LLM: ${st.llm.model || st.llm.backend}` : "LLM 미설정";
  llm.className = "chip " + (st.llm.configured ? "ok" : "warn");
  llm.title = st.llm.configured ? `${st.llm.backend} ${st.llm.endpoint}` :
    "DOC2REPORT_LLM_BASE_URL / DOC2REPORT_MODEL 이 없습니다 — scripts\\onprem_env.ps1";
  const pdf = $("#st-pdf");
  pdf.textContent = st.pdf.available ? `PDF: ${st.pdf.engine}` : "PDF 변환기 없음";
  pdf.className = "chip " + (st.pdf.available ? "ok" : "bad");
  pdf.title = st.pdf.available ? "" : "MS Word 또는 LibreOffice가 있어야 PDF를 만들 수 있습니다";
  $("#out-pdf").disabled = !st.pdf.available;
  $("#out-dir").textContent = st.output_dir;
  if (!st.llm.configured) {
    $("#allow-llm").closest("label").classList.add("disabled");
  }
}

// ── 프로파일·옵션 ────────────────────────────────────────────────────────

async function loadProfiles() {
  const data = await api("/api/profiles");
  state.schema = data.schema;
  for (const p of data.profiles) state.profiles[p.name] = p;
  const presets = data.schema.presets.filter((n) => state.profiles[n]);
  const label = (n) => state.profiles[n].label;

  $("#preset-radios").innerHTML = presets.concat(["custom"]).map((n) =>
    `<label><input type="radio" name="preset" value="${esc(n)}"><span>${
      esc(n === "custom" ? "사용자 설정" : label(n))}</span></label>`).join("");
  const opts = presets.map((n) => `<option value="${esc(n)}">${esc(label(n))}</option>`).join("");
  $("#rules-base").innerHTML = opts;
  $("#cu-base").innerHTML = opts;

  renderChecks("#polish-rules", data.schema.polish);
  renderChecks("#marker-rules", data.schema.markers);
  renderChecks("#table-rules", data.schema.tables);
  $("#tbl-align").innerHTML = data.schema.table_align.map((o) =>
    `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  const auto = data.schema.auto;
  $("#auto-heavy").textContent = `${auto.chars.toLocaleString()}자·표 ${auto.tables}개·입력 2개 이상`;
}

function renderChecks(target, rows) {
  $(target).innerHTML = rows.map((r) =>
    `<label class="check"><input type="checkbox" data-rule="${esc(r.key)}"> ${esc(r.label)}` +
    (r.help ? `<span class="hint">${esc(r.help)}</span>` : "") + `</label>`).join("");
}

// 직접 선택 모드의 체크박스를 한 서식의 기본 규칙으로 채운다.
function applyRules(name) {
  const p = state.profiles[name];
  if (!p) return;
  $("#rules-base").value = name;
  for (const box of $$("[data-rule]")) box.checked = !!p.text[box.dataset.rule];
  setRadio("polish", p.polish);
  $("#tbl-landscape").checked = !!p.tables.allow_landscape;
  $("#tbl-align").value = p.tables.align;
}

const CUSTOM_KEYS = ["font", "title_size", "size", "line_spacing", "table_size",
  "margin_top", "margin_bottom", "margin_left", "margin_right"];

// 사용자 설정 칸을 출발 서식의 값으로 채운다(자유롭게 고쳐 쓰는 출발점).
function fillCustom(base) {
  const p = state.profiles[base];
  if (!p) return;
  $("#cu-base").value = base;
  for (const k of CUSTOM_KEYS) $(`#cu-${k}`).value = p.format[k] || "";
  for (const k of ["font", "title_size", "size", "line_spacing", "table_size"]) {
    const values = Array.from(new Set([p.format[k], ...((p.choices || {})[k] || [])].filter(Boolean)));
    $(`#dl-${k}`).innerHTML = values.map((v) => `<option value="${esc(v)}">`).join("");
  }
}

function syncPreset() {
  const preset = radio("preset");
  const custom = preset === "custom";
  $("#custom-panel").classList.toggle("hidden", !custom);
  const p = state.profiles[custom ? $("#cu-base").value : preset];
  $("#preset-summary").textContent = custom ? "출발 서식에서 바꾸고 싶은 값만 고치세요 (단위: pt, 배, cm)"
    : (p ? `${p.summary}` : "");
  const hasConfluence = state.inputs.some((i) => i.type === "confluence");
  const suggest = hasConfluence && preset === "default" && state.profiles.confluence;
  const hint = $("#preset-hint");
  hint.classList.toggle("hidden", !suggest);
  if (suggest) {
    hint.innerHTML = `Confluence 입력이 있습니다 — '${esc(state.profiles.confluence.label)}' 서식이 맞을 수 있습니다
      <button class="btn tiny" id="use-confluence">바꾸기</button>`;
  }
}

document.addEventListener("click", (ev) => {
  if (ev.target.id === "use-confluence") { setRadio("preset", "confluence"); syncPreset(); }
});

function setRadio(name, value) {
  const el = $(`input[name="${name}"][value="${value}"]`);
  if (el) el.checked = true;
}
const radio = (name) => ($(`input[name="${name}"]:checked`) || {}).value;

function collectOptions() {
  const mode = radio("mode");
  const dateMode = radio("date");
  const text = {};
  for (const box of $$("[data-rule]")) text[box.dataset.rule] = box.checked;
  const formats = ["docx"];
  if ($("#out-pdf").checked && !$("#out-pdf").disabled) formats.push("pdf");
  if ($("#out-md").checked) formats.push("md");
  const custom = { base: $("#cu-base").value };
  for (const k of CUSTOM_KEYS) custom[k] = $(`#cu-${k}`).value.trim();
  return {
    mode,
    allow_llm: $("#allow-llm").checked,
    preset: radio("preset") || "default",
    custom,
    rules_base: $("#rules-base").value,
    polish: radio("polish"),
    text,
    tables: { allow_landscape: $("#tbl-landscape").checked, align: $("#tbl-align").value },
    section_titles: $("#section-titles").checked,
    page_breaks: $("#page-breaks").checked,
    title: $("#doc-title").value.trim(),
    date: dateMode === "pick" ? $("#date-pick").value : dateMode,
    date_mode: dateMode,
    formats,
    report: $("#out-report").checked,
  };
}

function saveOptions() {
  try {
    const o = collectOptions();
    delete o.title;
    localStorage.setItem(STORE_KEY, JSON.stringify(o));
  } catch (e) { /* 저장 못 해도 동작에는 지장 없음 */ }
}

function restoreOptions() {
  let o = null;
  try { o = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (e) { o = null; }
  const presets = state.schema.presets;
  const first = presets.includes("default") ? "default" : presets[0];
  const known = (n) => n && state.profiles[n] && presets.includes(n);
  setRadio("preset", o && (o.preset === "custom" || known(o.preset)) ? o.preset : first);
  fillCustom(o && o.custom && known(o.custom.base) ? o.custom.base : first);
  applyRules(o && known(o.rules_base) ? o.rules_base : first);
  if (!o) { syncPreset(); return syncMode(); }
  if (o.custom) for (const k of CUSTOM_KEYS) if (o.custom[k]) $(`#cu-${k}`).value = o.custom[k];
  setRadio("mode", o.mode || "auto");
  $("#allow-llm").checked = !!o.allow_llm;
  if (o.polish) setRadio("polish", o.polish);
  for (const box of $$("[data-rule]")) if (o.text && box.dataset.rule in o.text) box.checked = o.text[box.dataset.rule];
  if (o.tables) { $("#tbl-landscape").checked = !!o.tables.allow_landscape; if (o.tables.align) $("#tbl-align").value = o.tables.align; }
  $("#section-titles").checked = o.section_titles !== false;
  $("#page-breaks").checked = !!o.page_breaks;
  setRadio("date", o.date_mode ?? "");
  if (o.date_mode === "pick" && o.date) $("#date-pick").value = o.date;
  $("#out-pdf").checked = (o.formats || []).includes("pdf");
  $("#out-md").checked = (o.formats || []).includes("md");
  $("#out-report").checked = o.report !== false;
  syncPreset();
  syncMode();
}

function syncMode() {
  const manual = radio("mode") === "manual";
  $("#auto-panel").classList.toggle("hidden", manual);
  $("#manual-panel").classList.toggle("hidden", !manual);
  const polish = radio("polish");
  $("#polish-rules").classList.toggle("disabled", polish === "none");
  for (const box of $$("#polish-rules input")) box.disabled = polish === "none";
  $("#date-pick").classList.toggle("hidden", radio("date") !== "pick");
}

// ── 입력 목록 ────────────────────────────────────────────────────────────

const KIND_LABEL = { confluence: "Confluence", docx: "Word", text: "글" };

function renderInputs() {
  if (state.schema) syncPreset();
  const list = $("#input-list");
  $("#input-empty").classList.toggle("hidden", state.inputs.length > 0);
  list.innerHTML = state.inputs.map((item, i) => {
    const title = item.title || item.name;
    const detail = item.error ? `<small class="bad">${esc(item.error)}</small>`
      : `<small>${esc(item.detail || "")}</small>`;
    return `<li>
      <span class="kind ${item.type}">${KIND_LABEL[item.type]}</span>
      <span class="name"><b title="${esc(title)}">${esc(title)}</b>${detail}</span>
      <span class="ops">
        <button class="btn tiny" data-op="up" data-i="${i}" ${i === 0 ? "disabled" : ""} title="위로">↑</button>
        <button class="btn tiny" data-op="down" data-i="${i}" ${i === state.inputs.length - 1 ? "disabled" : ""} title="아래로">↓</button>
        <button class="btn tiny" data-op="del" data-i="${i}" title="빼기">✕</button>
      </span></li>`;
  }).join("");
}

$("#input-list").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-op]");
  if (!btn) return;
  const i = Number(btn.dataset.i);
  const items = state.inputs;
  if (btn.dataset.op === "del") items.splice(i, 1);
  if (btn.dataset.op === "up" && i > 0) [items[i - 1], items[i]] = [items[i], items[i - 1]];
  if (btn.dataset.op === "down" && i < items.length - 1) [items[i + 1], items[i]] = [items[i], items[i + 1]];
  renderInputs();
});

$("#cf-add").addEventListener("click", async () => {
  const urls = $("#cf-urls").value.split(/\s+/).map((u) => u.trim()).filter(Boolean);
  if (!urls.length) return toast("Confluence 페이지 주소를 넣어 주세요", true);
  $("#cf-urls").value = "";
  const added = urls.map((url) => ({ type: "confluence", url, name: url, detail: "제목 확인 중…" }));
  state.inputs.push(...added);
  renderInputs();
  await Promise.all(added.map(async (item) => {
    if (!state.status || !state.status.confluence.configured) {
      item.detail = url_short(item.url) + " · 연결 설정이 없어 제목 확인 못 함";
      return;
    }
    try {
      const r = await api("/api/confluence/check", { url: item.url });
      item.title = r.title;
      item.detail = `페이지 ${r.page_id}`;
    } catch (e) {
      item.error = "확인 실패: " + e.message;
    }
    renderInputs();
  }));
  renderInputs();
});

function url_short(url) { return url.length > 60 ? url.slice(0, 57) + "…" : url; }

async function addFiles(files) {
  for (const file of files) {
    if (!/\.docx$/i.test(file.name)) { toast(`${file.name}: Word(.docx) 파일만 올릴 수 있습니다`, true); continue; }
    const item = { type: "docx", name: file.name, title: file.name.replace(/\.docx$/i, ""), detail: "올리는 중…" };
    state.inputs.push(item);
    renderInputs();
    try {
      const r = await api("/api/upload", file, { "X-Filename": encodeURIComponent(file.name) });
      item.upload_id = r.upload_id;
      item.detail = `${file.name} · ${(r.size / 1024).toFixed(0)}KB`;
    } catch (e) {
      item.error = e.message;
    }
    renderInputs();
  }
}

$("#file-input").addEventListener("change", (ev) => { addFiles(ev.target.files); ev.target.value = ""; });
const drop = $("#drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (ev) => addFiles(ev.dataTransfer.files));

$("#tx-add").addEventListener("click", () => {
  const text = $("#tx-body").value;
  if (!text.trim()) return toast("붙여 넣을 글이 없습니다", true);
  const title = $("#tx-title").value.trim();
  const first = text.trim().split("\n")[0].slice(0, 40);
  const lines = text.trim().split("\n").length;
  state.inputs.push({ type: "text", text, title, name: title || first, detail: `${lines}줄 · ${text.length.toLocaleString()}자` });
  $("#tx-body").value = ""; $("#tx-title").value = "";
  renderInputs();
});

$$(".tab").forEach((tab) => tab.addEventListener("click", () => {
  $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  $$(".panel").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== tab.dataset.tab));
}));

// ── 변환 ─────────────────────────────────────────────────────────────────

$("#convert").addEventListener("click", async () => {
  const bad = state.inputs.find((i) => i.type === "docx" && !i.upload_id);
  if (!state.inputs.length) return toast("입력을 하나 이상 추가해 주세요", true);
  if (bad) return toast(`${bad.name}: 파일이 아직 올라가지 않았거나 실패했습니다`, true);
  const options = collectOptions();
  if (options.date_mode === "pick" && !options.date) return toast("날짜를 골라 주세요", true);
  saveOptions();
  const inputs = state.inputs.map((i) => ({ type: i.type, url: i.url, upload_id: i.upload_id, name: i.name, text: i.text, title: i.title }));

  $("#convert").disabled = true;
  $("#result").classList.add("hidden");
  $("#progress").classList.remove("hidden");
  $("#progress-log").innerHTML = "<li>시작</li>";
  try {
    const { job } = await api("/api/convert", { inputs, options });
    poll(job);
  } catch (e) {
    finish({ state: "error", error: e.message });
  }
});

function poll(id) {
  clearTimeout(state.polling);
  state.polling = setTimeout(async () => {
    let job;
    try { job = await api(`/api/jobs/${id}`); } catch (e) { return finish({ state: "error", error: e.message }); }
    $("#progress-log").innerHTML = job.messages.slice(-6).map((m) => `<li>${esc(m)}</li>`).join("");
    if (job.state === "running") poll(id); else finish(job);
  }, 600);
}

function finish(job) {
  $("#convert").disabled = false;
  $("#progress").classList.add("hidden");
  const box = $("#result");
  box.classList.remove("hidden", "error");
  if (job.state !== "done") {
    box.classList.add("error");
    box.innerHTML = `<h3>변환 실패</h3><p>${esc(job.error)}</p>`;
    return;
  }
  const r = job.result;
  const files = r.files.map(fileRow).join("");
  const decision = r.decision ? `<div class="decision"><b>자동 판단 결과</b><ul>${
    r.decision.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
  const notes = r.notes.filter((n) => !n.startsWith("자동 판단:"));
  const polishName = { none: "안 함", rules: "파이썬 규칙", llm: "규칙 + LLM" }[r.polish] || r.polish;
  box.innerHTML = `
    <h3>완료 — ${esc(r.title || r.stem)} <span class="hint">(${job.elapsed}초)</span></h3>
    <p class="hint">서식 ${esc(r.profile)} · 문장 다듬기 ${esc(polishName)} · 표 ${r.tables}개 · 문구 수정 ${r.change_count}건</p>
    <div class="files">${files}</div>
    ${decision}
    ${notes.length ? `<details open><summary>레이아웃·입력 메모 (${notes.length})</summary><ul class="notes">${
      notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></details>` : ""}
    ${r.changes.length ? `<details><summary>문구 수정 내역 (${r.change_count}건)</summary>
      <table class="changes"><tr><th>원문</th><th>수정</th><th>규칙</th></tr>${
      r.changes.map((c) => `<tr><td>${esc(c.before)}</td><td>${esc(c.after)}</td><td class="rule">${esc(c.rule)}</td></tr>`).join("")}</table></details>` : ""}`;
  loadHistory();
}

const KIND_NAME = { docx: "Word", pdf: "PDF", md: "MD", report: "변경내역" };

function fileRow(f) {
  const href = `/files/${encodeURIComponent(f.name)}`;
  const view = f.kind === "pdf" || f.kind === "md" || f.kind === "report"
    ? `<a class="btn tiny" href="${href}" target="_blank" rel="noopener">브라우저로 보기</a>` : "";
  return `<div class="file"><span class="badge ${f.kind}">${KIND_NAME[f.kind] || f.kind}</span>
    <span class="fname">${esc(f.name)}</span>
    <button class="btn tiny" data-open="${esc(f.name)}">열기</button>${view}
    <a class="btn tiny" href="${href}?download=1" download>내려받기</a>
    <button class="btn tiny" data-folder="${esc(f.name)}" title="탐색기에서 이 파일 위치 열기">폴더</button></div>`;
}

document.addEventListener("click", async (ev) => {
  const open = ev.target.closest("[data-open]");
  const folder = ev.target.closest("[data-folder]");
  if (!open && !folder) return;
  try {
    await api("/api/open", open ? { name: open.dataset.open } : { name: folder.dataset.folder, folder: true });
    toast(open ? "여는 중… (Word·PDF 뷰어 창을 확인하세요)" : "폴더를 여는 중…");
  } catch (e) {
    toast(e.message, true);
  }
});

$("#open-folder").addEventListener("click", async () => {
  try { await api("/api/open", { folder: true }); toast("폴더를 여는 중…"); } catch (e) { toast(e.message, true); }
});

// ── 최근 결과 ────────────────────────────────────────────────────────────

async function loadHistory() {
  const { items } = await api("/api/history");
  $("#history-empty").classList.toggle("hidden", items.length > 0);
  $("#history").innerHTML = items.map((g) => `<li>
    <div class="hname">${esc(g.stem)}</div><div class="htime">${esc(g.time)}</div>
    <div class="hfiles">${g.files.map((f) =>
      `<button class="btn tiny" data-open="${esc(f.name)}" title="${esc(f.name)}">${KIND_NAME[f.kind] || f.kind} 열기</button>`).join("")}
    </div></li>`).join("");
}
$("#history-refresh").addEventListener("click", loadHistory);

// ── LLM 시험 ─────────────────────────────────────────────────────────────

$("#llm-test").addEventListener("click", async () => {
  const out = $("#llm-test-out");
  out.textContent = "시험 중…";
  try {
    const r = await api("/api/llm/test", {});
    out.textContent = `성공: "${r.before}" → "${r.after}"`;
  } catch (e) {
    out.textContent = "실패: " + e.message;
  }
});

// ── 시작 ─────────────────────────────────────────────────────────────────

$("#rules-base").addEventListener("change", (ev) => { applyRules(ev.target.value); syncMode(); });
$("#cu-base").addEventListener("change", (ev) => { fillCustom(ev.target.value); syncPreset(); });
document.addEventListener("change", (ev) => {
  if (ev.target.name === "mode" || ev.target.name === "polish" || ev.target.name === "date") syncMode();
  if (ev.target.name === "preset") syncPreset();
});

(async function init() {
  renderInputs();
  try {
    await Promise.all([loadStatus(), loadProfiles()]);
    restoreOptions();
    await loadHistory();
  } catch (e) {
    toast("서버와 연결하지 못했습니다: " + e.message, true);
  }
})();
