"use strict";

// Test console for the parltopics API. Same origin as the API, so no keys live here.

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const LANG_NAMES = { de: "German", fr: "French", it: "Italian", rm: "Romansh", en: "English" };
const KIND_LABEL = {
  multi_label: "Several can apply",
  single_label: "Exactly one applies",
  binary: "Yes or no",
};
const SECTION_LABEL = {
  title: "Title",
  lead: "Lead",
  submitted_text: "Submitted text",
  reasoning: "Reasoning",
  answer: "Federal Council answer",
  document: "Document",
};
const MAX_SECTION_CHARS = 6000; // matches max_section_chars in config.py

const state = {
  parliaments: {},
  taxonomies: [],
  health: null,
  classification: null,
  labels: {},
  similar: null,
  aps: null, // the editable APS label set, see "APS label set" below
  apsSent: null, // the APS topics as sent with the last classification, by id
  editing: null, // the label whose topic is being changed
  allChapters: false,
  mapOpen: false, // the chapter map stays folded until someone opens it
  domainFilter: null, // selected domain index in the legend, or null for all
  lang: "de", // label language: de, fr or it
};
const APS = "aps_topics";

// ---------- helpers ----------

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const fmt = (p) => (p == null ? "–" : Number(p).toFixed(2));
const clampInt = (value, min, max, fallback) => {
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
};

function errorText(data) {
  if (!data || !data.detail) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((d) => String(d.msg || "").replace(/^Value error, /, "")).join(" ");
  }
  return JSON.stringify(data.detail);
}

async function api(path, { json, form } = {}) {
  const init = { method: json || form ? "POST" : "GET", headers: {} };
  if (json) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  }
  if (form) init.body = form;
  const started = performance.now();
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("The service is not reachable. Check that the server is running.");
  }
  const ms = performance.now() - started;
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* not JSON */
  }
  if (!response.ok) throw new Error(errorText(data) || `The service answered with status ${response.status}.`);
  return { data, ms };
}

function parliamentName(key) {
  if (key === "CHE") return "Federal Assembly";
  const p = state.parliaments[key];
  if (!p) return key || "–";
  if (p.type === "city" || p.type === "municipality") return `${p.name} (city${p.canton ? ", " + p.canton : ""})`;
  return p.name;
}

function bestTitle(titles, prefer) {
  const order = [...prefer, "de", "fr", "it", "rm", "en"];
  for (const lang of order) if (titles && titles[lang]) return { text: titles[lang], lang };
  const first = Object.entries(titles || {})[0];
  return first ? { text: first[1], lang: first[0] } : { text: "(no title)", lang: "" };
}

const icon = (name, cls = "i sm") => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const loading = (text) =>
  `<div class="loading" role="status"><div class="loading-line"><span class="spinner" aria-hidden="true"></span>${esc(text)}</div>` +
  `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>`;
const errorBox = (text) => `<div class="error" role="alert">${icon("alert", "i")}<span>${esc(text)}</span></div>`;
const rawJson = (data) =>
  `<details class="raw"><summary>Raw response</summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>`;

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
  ($(".label", button) || button).textContent = label;
}

// Pick the label in the current UI language, falling back to German then any language.
function label(names, fallback = "") {
  if (!names) return fallback;
  return names[state.lang] || names.de || Object.values(names)[0] || fallback;
}

// ---------- language switch ----------
$$(".lang-btn").forEach((btn) =>
  btn.addEventListener("click", () => {
    state.lang = btn.dataset.lang;
    $$(".lang-btn").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    try {
      localStorage.setItem("console-lang", state.lang);
    } catch {
      /* storage is optional */
    }
    if (state.aps) {
      updateApsSummary();
      renderChapterOptions();
      renderApsEditor();
      refreshLabels();
    }
  })
);
try {
  const saved = localStorage.getItem("console-lang");
  if (saved && ["de", "fr", "it"].includes(saved)) {
    state.lang = saved;
    $$(".lang-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === saved)));
  }
} catch {
  /* storage is optional */
}

// ---------- tabs ----------

function selectTab(name) {
  for (const tab of ["search", "classify"]) {
    const on = tab === name;
    $(`#tab-${tab}`).setAttribute("aria-selected", String(on));
    $(`#panel-${tab}`).hidden = !on;
  }
  try {
    localStorage.setItem("console-tab", name);
  } catch {
    /* storage is optional */
  }
}
$("#tab-search").addEventListener("click", () => selectTab("search"));
$("#theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try {
    localStorage.setItem("console-theme", root.dataset.theme);
  } catch {
    /* storage is optional */
  }
});
$("#tab-classify").addEventListener("click", () => selectTab("classify"));

// ---------- startup data ----------

async function loadHealth() {
  const box = $("#status");
  const pill = (ok, label, hint) =>
    `<span class="pill ${ok ? "good" : "bad"}" title="${esc(hint)}">${esc(label)}</span>`;
  try {
    const { data } = await api("/health");
    state.health = data;
    box.innerHTML =
      pill(data.search, `Search · ${data.apertus_model}`, data.search ? "Apertus is configured" : "APERTUS_API_KEY is missing") +
      pill(data.classification, `Classify · ${data.jev_model}`, data.classification ? "Jev is configured" : "TYPESAFE_API_KEY is missing");
  } catch (error) {
    box.innerHTML = `<span class="pill bad">${esc(error.message)}</span>`;
  }
}

async function loadTaxonomies() {
  try {
    const [{ data: list }, { data: aps }] = await Promise.all([api("/taxonomies"), api(`/taxonomies/${APS}`)]);
    state.taxonomies = list;
    initAps(aps);
  } catch (error) {
    $("#aps-summary").innerHTML = errorBox(error.message);
  }
}

async function loadParliaments() {
  try {
    const { data } = await api("/parliaments");
    state.parliaments = data || {};
    const rank = { country: 0, canton: 1, city: 2, municipality: 3 };
    $("#parliament-list").innerHTML = Object.entries(state.parliaments)
      .sort(([ka, a], [kb, b]) => (rank[a.type] ?? 9) - (rank[b.type] ?? 9) || String(a.name).localeCompare(String(b.name)))
      .map(([key]) => `<option value="${esc(key)}">${esc(parliamentName(key))}</option>`)
      .join("");
  } catch {
    /* names are a convenience */
  }
}

// ---------- search ----------

$$("#search-form [data-q]").forEach((chip) =>
  chip.addEventListener("click", () => {
    $("#q").value = chip.dataset.q;
    $("#search-form").requestSubmit();
  })
);

$("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const out = $("#search-out");
  const query = $("#q").value.trim();
  const languages = $$('input[name="lang"]:checked').map((input) => input.value);
  if (query.length < 2) {
    out.innerHTML = errorBox("Write at least two characters.");
    return;
  }
  if (!languages.length) {
    out.innerHTML = errorBox("Pick at least one language under Options.");
    return;
  }
  const body = {
    query,
    languages,
    scope: $('input[name="scope"]:checked').value,
    rank: $("#rank").checked,
    body_keys: $("#bodies").value.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean),
    variants_per_language: clampInt($("#variants").value, 1, 5, 3),
    max_results: clampInt($("#max").value, 1, 300, 40),
  };
  const button = $("#search-submit");
  setBusy(button, true, "Searching…");
  out.innerHTML = loading(body.rank ? "Writing queries, searching every language, ranking with Jev…" : "Writing queries and searching every language…");
  try {
    const { data, ms } = await api("/search", { json: body });
    renderSearch(data, ms);
  } catch (error) {
    out.innerHTML = errorBox(error.message);
  } finally {
    setBusy(button, false, "Search");
  }
});

function renderSearch(result, ms) {
  const languages = new Set(result.hits.flatMap((h) => h.matched_by.map((m) => m.language)));
  const bodies = new Set(result.hits.map((h) => h.affair.body_key));
  const parts = [
    `<div class="stats">
      <div class="stat"><b>${result.unique_affairs}</b><span>affairs found</span></div>
      <div class="stat"><b>${result.hits.length}</b><span>shown</span></div>
      <div class="stat"><b>${bodies.size}</b><span>parliaments</span></div>
      <div class="stat"><b>${languages.size}</b><span>languages matched</span></div>
      <div class="stat"><b>${(ms / 1000).toFixed(1)}<small> s</small></b><span>response time</span></div>
    </div>
    <div class="summary">
      <span>Matched in ${esc([...languages].map((l) => LANG_NAMES[l] || l).join(", ") || "no language")}</span>
      <span>${result.ranked ? "Ranked by Jev relevance" : "Ordered by number of matching queries, then date"}</span>
    </div>`,
    ...result.warnings.map((w) => `<div class="warning">${esc(w)}</div>`),
    `<div class="card queries"><h3>Queries Apertus wrote</h3>${result.queries
      .map(
        (q) => `<div class="query-line"><span class="lang">${esc(q.language)}</span><div>${q.queries
          .map((text) => `<span class="qchip">${esc(text)}</span>`)
          .join("")}</div></div>`
      )
      .join("")}</div>`,
  ];
  if (!result.hits.length) {
    parts.push(
      `<div class="empty"><h2>No affairs matched</h2><p>Try a broader request or more languages, or switch to Full search under Search options.</p></div>`
    );
  } else {
    parts.push(`<ol class="hits">${result.hits.map(hitHtml).join("")}</ol>`);
  }
  parts.push(rawJson(result));
  $("#search-out").innerHTML = parts.join("");
}

function hitHtml(hit) {
  const affair = hit.affair;
  const matchedLanguages = [...new Set(hit.matched_by.map((m) => m.language))];
  const title = bestTitle(affair.title, matchedLanguages);
  const type = (affair.type && (affair.type.en || affair.type.de)) || "";
  const relevance =
    hit.relevance == null
      ? ""
      : `<div class="relevance" title="Jev probability that this affair matches the request">
          <span class="track"><span class="fill" style="width:${(hit.relevance * 100).toFixed(1)}%"></span></span>${fmt(hit.relevance)}
        </div>`;
  const matched = hit.matched_by.map((m) => `${m.language} “${m.query}”`).join(" · ");
  return `<li class="card hit">
    <div class="hit-meta">
      <span class="body">${esc(parliamentName(affair.body_key))}</span>
      ${type ? `<span>${esc(type)}</span>` : ""}
      ${affair.number ? `<span class="mono">${esc(affair.number)}</span>` : ""}
      ${affair.begin_date ? `<span>${esc(affair.begin_date)}</span>` : ""}
    </div>
    <div class="hit-side">
      ${relevance}
      <div class="hit-actions">
        <a class="ghost" href="${esc(affair.url)}" target="_blank" rel="noopener">Open${icon("external")}</a>
        <button type="button" class="ghost go" data-classify="${esc(affair.url)}">Classify${icon("arrow")}</button>
      </div>
    </div>
    <div class="hit-title">${esc(title.text)}<span class="tl">${esc(title.lang)}</span></div>
    <div class="hit-matched">Matched by ${esc(matched)}</div>
  </li>`;
}

// Hand a search hit over to the classifier.
$("#search-out").addEventListener("click", (event) => {
  const button = event.target.closest("[data-classify]");
  if (!button) return;
  setMode("link");
  $("#ref").value = button.dataset.classify;
  selectTab("classify");
  $("#classify-form").requestSubmit();
});

// ---------- classify form ----------

function setMode(mode) {
  $$('input[name="mode"]').forEach((input) => (input.checked = input.value === mode));
  $$("#classify-form .mode").forEach((block) => (block.hidden = block.dataset.mode !== mode));
}
$$('input[name="mode"]').forEach((input) => input.addEventListener("change", () => setMode(input.value)));

$$("#classify-form [data-ref]").forEach((chip) =>
  chip.addEventListener("click", () => {
    $("#ref").value = chip.dataset.ref;
    $("#classify-form").requestSubmit();
  })
);

// ---------- APS label set ----------
// The 165 APS topics in 22 chapters (8 domains). People can rename, describe, delete or add topics in the
// page; an edited set is sent with the request as `aps_topics` and replaces the stored one for that call.

const OWN_CHAPTER = "Your topics";
let topicCounter = 0;

function initAps(taxonomy) {
  const chapters = new Map();
  const domains = [];
  const topics = taxonomy.topics.map((t) => {
    const code = t.code || t.id;
    const [domainCode, chapterCode] = code.split(".");
    const domain = (/domain (.*?) \(/.exec(t.description || "") || [])[1] || "";
    if (!domains.some((d) => d.code === domainCode))
      domains.push({ code: domainCode, name: domain, names: t.domain_names || {} });
    const domainIndex = domains.findIndex((d) => d.code === domainCode) + 1;
    if (!chapters.has(t.group))
      chapters.set(t.group, { name: t.group, code: `${domainCode}.${chapterCode}`, domainIndex, names: t.group_names || {} });
    return {
      uid: `t${++topicCounter}`,
      id: t.id,
      code,
      name: t.name,
      names: t.names || {},
      description: "",
      baseDescription: t.description,
      group: t.group,
    };
  });
  chapters.set(OWN_CHAPTER, { name: OWN_CHAPTER, code: "", domainIndex: 0, names: {} });
  state.aps = { threshold: taxonomy.default_threshold, chapters, domains, original: topics.map((t) => ({ ...t })), topics, open: new Set() };
  renderChapterOptions();
  updateApsSummary();
}

function renderChapterOptions() {
  if (!state.aps) return;
  $("#new-topic-chapter").innerHTML = [...state.aps.chapters.values()]
    .map((c) => {
      const chapterLabel = label(c.names, c.name);
      return `<option value="${esc(c.name)}"${c.name === OWN_CHAPTER ? " selected" : ""}>${esc(c.code ? `${c.code} ${chapterLabel}` : `${chapterLabel} (new chapter)`)}</option>`;
    })
    .join("");
}

function apsChanges() {
  const aps = state.aps;
  const before = new Map(aps.original.map((t) => [t.uid, t]));
  const now = new Set(aps.topics.map((t) => t.uid));
  let added = 0, changed = 0;
  for (const t of aps.topics) {
    const o = before.get(t.uid);
    if (!o) added++;
    else if (o.name !== t.name || o.description !== t.description || o.group !== t.group) changed++;
  }
  const removed = aps.original.filter((t) => !now.has(t.uid)).length;
  return { added, changed, removed, any: added + changed + removed > 0 };
}

function updateApsSummary() {
  const aps = state.aps;
  if (!aps) return;
  const groups = new Set(aps.topics.map((t) => t.group));
  $("#aps-summary").textContent = `${aps.topics.length} topics in ${groups.size} chapters`;
  const c = apsChanges();
  const badge = $("#aps-edited");
  badge.hidden = !c.any;
  badge.textContent = [c.added && `${c.added} added`, c.changed && `${c.changed} changed`, c.removed && `${c.removed} deleted`]
    .filter(Boolean)
    .join(" · ");
}

function chapterOf(group) {
  return (state.aps && state.aps.chapters.get(group)) || { name: group, code: "", domainIndex: 0, names: {} };
}
const hue = (group) => `var(--d${chapterOf(group).domainIndex})`;

// Translated topic name: look up the APS topic's names dict, fall back to the given name.
function topicName(topicId, fallback) {
  const t = state.aps && state.aps.topics.find((x) => x.id === topicId);
  return t ? label(t.names, t.name) : fallback;
}

function renderApsEditor() {
  const aps = state.aps;
  if (!aps) return;
  const filter = $("#aps-filter").value.trim().toLowerCase();
  const byChapter = new Map([...aps.chapters.keys()].map((name) => [name, []]));
  for (const t of aps.topics) {
    if (!byChapter.has(t.group)) byChapter.set(t.group, []);
    byChapter.get(t.group).push(t);
  }
  $("#aps-editor-list").innerHTML = [...byChapter.entries()]
    .map(([name, topics]) => {
      const shown = filter
        ? topics.filter((t) => `${name} ${t.name} ${t.description}`.toLowerCase().includes(filter))
        : topics;
      if (!shown.length && (filter || name === OWN_CHAPTER)) return "";
      const chapter = chapterOf(name);
      const rows = shown
        .map(
          (t) => `<div class="ed-row" data-uid="${t.uid}">
            <input class="ed-name" value="${esc(t.name)}" aria-label="Topic name" maxlength="200">
            <input class="ed-desc" value="${esc(t.description)}" placeholder="Description (optional)" aria-label="What ${esc(t.name)} covers" maxlength="1000">
            <button type="button" class="icon" data-del="${t.uid}" aria-label="Delete ${esc(t.name)}">${icon("x", "i")}</button>
          </div>`
        )
        .join("");
      const open = filter || aps.open.has(name) ? " open" : "";
      const chapterLabel = label(chapter.names, name);
      return `<details class="ed-chapter" data-chapter="${esc(name)}" style="--hue:${hue(name)}"${open}>
        <summary><span class="swatch"></span><span class="ed-chapter-name">${esc(chapter.code ? `${chapter.code} ${chapterLabel}` : chapterLabel)}</span><span class="muted">${topics.length}</span></summary>
        <div class="ed-rows">${rows || `<p class="hint">No topics left in this chapter.</p>`}</div>
      </details>`;
    })
    .join("");
}

function addApsTopic(name, description = "", group = OWN_CHAPTER) {
  const aps = state.aps;
  name = String(name || "").trim();
  if (!aps || !name) return false;
  if (aps.topics.some((t) => t.name.toLowerCase() === name.toLowerCase())) return false;
  aps.topics.push({ uid: `t${++topicCounter}`, id: null, code: "", name, description: String(description || "").trim(), baseDescription: null, group });
  aps.open.add(group);
  updateApsSummary();
  if (!$("#aps-editor").hidden) renderApsEditor();
  return true;
}

function apsRequest() {
  // Unedited: the stored label set. Edited: the whole list, so deletions and renames count.
  const aps = state.aps;
  let n = 0;
  const topics = aps.topics.map((t) => ({
    id: t.id || `own-${++n}`,
    name: t.name.trim() || t.id || "Untitled topic",
    description: t.description.trim() || t.baseDescription || null,
    group: t.group,
  }));
  state.apsSent = new Map(topics.map((t) => [t.id, t]));
  return apsChanges().any ? { taxonomies: [], aps_topics: topics } : { taxonomies: [APS], aps_topics: null };
}

$("#aps-toggle").addEventListener("click", () => {
  const editor = $("#aps-editor");
  editor.hidden = !editor.hidden;
  $("#aps-toggle").setAttribute("aria-expanded", String(!editor.hidden));
  $("#aps-toggle .label").textContent = editor.hidden ? "Edit topics" : "Close editor";
  if (!editor.hidden) renderApsEditor();
});
$("#aps-filter").addEventListener("input", renderApsEditor);
$("#aps-editor").addEventListener("toggle", (event) => {
  const details = event.target.closest && event.target.closest("details.ed-chapter");
  if (details && !$("#aps-filter").value) state.aps.open[details.open ? "add" : "delete"](details.dataset.chapter);
}, true);
$("#aps-editor").addEventListener("input", (event) => {
  const row = event.target.closest(".ed-row");
  if (!row) return;
  const topic = state.aps.topics.find((t) => t.uid === row.dataset.uid);
  if (!topic) return;
  if (event.target.classList.contains("ed-name")) topic.name = event.target.value;
  if (event.target.classList.contains("ed-desc")) topic.description = event.target.value;
  updateApsSummary();
});
$("#aps-editor").addEventListener("click", (event) => {
  const del = event.target.closest("[data-del]");
  if (!del) return;
  state.aps.topics = state.aps.topics.filter((t) => t.uid !== del.dataset.del);
  updateApsSummary();
  renderApsEditor();
});
// Enter inside the editor must not submit the classify form.
$("#aps-editor").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.target.tagName === "TEXTAREA") return;
  event.preventDefault();
  if (event.target.id === "new-topic-name" || event.target.id === "new-topic-desc") $("#new-topic-add").click();
});
$("#new-topic-add").addEventListener("click", () => {
  const name = $("#new-topic-name").value.trim();
  const message = $("#new-topic-msg");
  const group = $("#new-topic-chapter").value;
  if (!name) {
    message.textContent = "Write a topic name first.";
    $("#new-topic-name").focus();
    return;
  }
  const existing = state.aps.topics.find((t) => t.name.toLowerCase() === name.toLowerCase());
  if (existing) {
    // already in the set: show it in the list so it can be described or renamed there
    message.textContent = `"${existing.name}" is already a topic in ${existing.group}. It is shown below: add a description there.`;
    $("#aps-filter").value = existing.name;
    renderApsEditor();
    return;
  }
  addApsTopic(name, $("#new-topic-desc").value, group);
  message.textContent = `Added "${name}" to ${group}. Classify to score it.`;
  $("#new-topic-name").value = "";
  $("#new-topic-desc").value = "";
  $("#new-topic-name").focus();
});
$("#aps-json-add").addEventListener("click", () => {
  const message = $("#aps-json-msg");
  let parsed;
  try {
    parsed = JSON.parse($("#aps-json").value);
  } catch {
    message.textContent = 'Not valid JSON. Write it as {"topic": "description", ...}.';
    return;
  }
  const entries = Array.isArray(parsed)
    ? parsed.map((t) => (typeof t === "string" ? [t, ""] : [t.name || t.topic, t.description || ""]))
    : Object.entries(parsed || {});
  const added = entries.filter(([name, description]) => addApsTopic(name, typeof description === "string" ? description : "")).length;
  message.textContent = `${added} ${added === 1 ? "topic" : "topics"} added to "${OWN_CHAPTER}".`;
  if (added) $("#aps-json").value = "";
});
$("#aps-reset").addEventListener("click", () => {
  state.aps.topics = state.aps.original.map((t) => ({ ...t }));
  updateApsSummary();
  renderApsEditor();
});

$("#override").addEventListener("change", () => ($("#threshold").disabled = !$("#override").checked));
$("#threshold").addEventListener("input", () => ($("#threshold-out").textContent = Number($("#threshold").value).toFixed(2)));

const fileInput = $("#file");
const drop = $("#drop");
function showFileName() {
  const file = fileInput.files[0];
  $("#file-label").innerHTML = file
    ? `<strong>${esc(file.name)}</strong><br><span class="muted">${(file.size / 1024).toFixed(0)} KB · click to change</span>`
    : `<strong>Choose a file</strong> or drop it here<br><span class="muted">PDF, DOCX, HTML or text, up to 25 MB</span>`;
}
fileInput.addEventListener("change", showFileName);
["dragenter", "dragover"].forEach((type) =>
  drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.add("over");
  })
);
["dragleave", "drop"].forEach((type) => drop.addEventListener(type, () => drop.classList.remove("over")));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  if (event.dataTransfer.files.length) {
    fileInput.files = event.dataTransfer.files;
    showFileName();
  }
});

$("#classify-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const out = $("#classify-out");
  const mode = $('input[name="mode"]:checked').value;
  if (!state.aps) {
    out.innerHTML = errorBox("The topics are still loading. Try again in a moment.");
    return;
  }
  if (!state.aps.topics.length) {
    out.innerHTML = errorBox("The label set is empty. Add a topic or reset to the original 165.");
    return;
  }
  const { taxonomies, aps_topics } = apsRequest();
  const customTopics = [];
  const threshold = $("#override").checked ? Number($("#threshold").value) : null;

  let request;
  let similarInput; // the same document, for /similar
  if (mode === "link") {
    const reference = $("#ref").value.trim();
    if (!reference) {
      out.innerHTML = errorBox("Paste a link or an affair id, or pick an example.");
      return;
    }
    request = api("/classify", {
      json: {
        reference,
        taxonomies,
        custom_topics: customTopics,
        aps_topics,
        language: $("#language").value || null,
        include_answer: $("#include-answer").checked,
        threshold,
      },
    });
    similarInput = { json: { reference, language: $("#language").value || null, include_answer: $("#include-answer").checked } };
  } else if (mode === "text") {
    const text = $("#text").value.trim();
    if (!text) {
      out.innerHTML = errorBox("Paste the text to classify.");
      return;
    }
    request = api("/classify", {
      json: { text, title: $("#title").value.trim() || null, taxonomies, custom_topics: customTopics, aps_topics, threshold },
    });
    similarInput = { json: { text, title: $("#title").value.trim() || null } };
  } else {
    const file = fileInput.files[0];
    if (!file) {
      out.innerHTML = errorBox("Choose a file first.");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("taxonomies", taxonomies.join(","));
    form.append("custom_topics", JSON.stringify(customTopics));
    if (aps_topics) form.append("aps_topics", JSON.stringify(aps_topics));
    const title = $("#file-title").value.trim();
    if (title) form.append("title", title);
    if (threshold != null) form.append("threshold", String(threshold));
    request = api("/classify/upload", { form });
    const similarForm = new FormData();
    similarForm.append("file", file);
    if (title) similarForm.append("title", title);
    similarInput = { form: similarForm };
  }

  const similar = startSimilar(similarInput); // runs while Jev classifies
  const button = $("#classify-submit");
  setBusy(button, true, "Classifying…");
  out.innerHTML = loading("Reading the document and asking Jev…");
  try {
    const { data, ms } = await request;
    renderClassification(data, ms);
    afterClassification(data, similar);
  } catch (error) {
    out.innerHTML = errorBox(error.message);
  } finally {
    setBusy(button, false, "Classify");
  }
});

// ---------- classify results ----------

function documentCard(doc, ms) {
  const affair = doc.affair;
  const kind = { affair: "Affair", doc: "Document", file: "File", upload: "Uploaded file", text: "Pasted text" }[doc.kind] || doc.kind;
  const meta = [
    `<span class="body">${esc(kind)}</span>`,
    doc.body_key ? `<span>${esc(parliamentName(doc.body_key))}</span>` : "",
    affair && affair.type && (affair.type.en || affair.type.de) ? `<span>${esc(affair.type.en || affair.type.de)}</span>` : "",
    affair && affair.number ? `<span class="mono">${esc(affair.number)}</span>` : "",
    affair && affair.begin_date ? `<span>${esc(affair.begin_date)}</span>` : "",
    doc.language ? `<span>${esc(LANG_NAMES[doc.language] || doc.language)} text</span>` : "",
    `<span>${(ms / 1000).toFixed(1)} s</span>`,
  ].join("");
  const sections = Object.entries(doc.sections || {});
  const cut = sections.some(([, chars]) => chars > MAX_SECTION_CHARS);
  const label = (name) =>
    SECTION_LABEL[name] || (name.startsWith("document_") ? `Document ${name.slice(9)}` : name.replace(/_/g, " "));
  return `<div class="card doc">
    <div class="hit-meta">${meta}</div>
    <div class="doc-title">${esc(doc.title || doc.reference || "Untitled")}</div>
    <div class="sections">${sections
      .map(([name, chars]) => `<span>${esc(label(name))} · ${chars.toLocaleString("en-US")} characters</span>`)
      .join("")}</div>
    ${cut ? `<p class="hint">Long sections are cut to ${MAX_SECTION_CHARS.toLocaleString("en-US")} characters before Jev reads them.</p>` : ""}
    ${affair ? `<div><a class="ghost" href="${esc(affair.url)}" target="_blank" rel="noopener">Open on OpenParlData${icon("external")}</a></div>` : ""}
  </div>`;
}

let barsCounter = 0;
function barsHtml(scores, { threshold, on, limit }) {
  const id = `bars-${++barsCounter}`;
  const rows = scores
    .map((score, index) => {
      const assigned = on.has(score.topic_id);
      const name = topicName(score.topic_id, score.name);
      const marker =
        threshold == null ? "" : `<span class="threshold" style="left:calc(${(threshold * 100).toFixed(1)}% - 1px)"></span>`;
      return `<div class="bar-row${assigned ? " on" : ""}"${index >= limit ? " hidden" : ""} title="${esc(name)}: ${score.probability.toFixed(3)}">
        <span class="name">${esc(name)}</span>
        <span class="track"><span class="fill" style="width:${(score.probability * 100).toFixed(1)}%"></span>${marker}</span>
        <span class="value">${fmt(score.probability)}</span>
      </div>`;
    })
    .join("");
  const more =
    scores.length > limit
      ? `<button type="button" class="ghost more" data-expand="${id}" data-limit="${limit}" data-total="${scores.length}">Show all ${scores.length}</button>`
      : "";
  return `<div class="bars" id="${id}">${rows}</div>${more}`;
}

function classificationCard(c) {
  const taxonomy = state.taxonomies.find((t) => t.id === c.taxonomy_id);
  const name = c.taxonomy_id === "custom" ? "Ad-hoc topics" : (taxonomy && taxonomy.name) || c.taxonomy_id;
  const choice = c.kind === "single_label";
  const byId = Object.fromEntries(c.scores.map((s) => [s.topic_id, s]));
  const assigned = c.predicted.map((id) => byId[id]).filter(Boolean);
  const meta = [
    KIND_LABEL[c.kind] || c.kind,
    `${c.scores.length} ${c.scores.length === 1 ? "topic" : "topics"}`,
    choice ? `confidence ${fmt(c.confidence)}` : `threshold ${fmt(c.threshold)}`,
    c.model,
  ].join(" · ");
  const tags = assigned.length
    ? assigned.map((s) => `<span class="tag">${esc(s.name)} · ${fmt(s.probability)}</span>`).join("")
    : `<span class="none-assigned">${choice ? "No choice" : "No topic reaches the threshold"}</span>`;
  const limit = c.scores.length > 14 ? 12 : c.scores.length;
  const groups = c.groups && c.groups.length
    ? `<div class="subhead">Chapters · highest topic score in each</div>${barsHtml(c.groups, {
        threshold: c.threshold,
        on: new Set(c.groups.filter((g) => g.probability >= c.threshold).map((g) => g.topic_id)),
        limit: 8,
      })}`
    : "";
  const note = choice
    ? "Probabilities compare the options and add up to 1."
    : "Each bar is Jev's probability that the topic applies. Blue bars reach the threshold (dark line) and are assigned.";
  return `<section class="card result">
    <div class="result-head"><h3>${esc(name)}</h3><span class="result-meta">${esc(meta)}</span></div>
    <div class="assigned"><span class="muted">${choice ? "Choice" : "Assigned"}</span>${tags}</div>
    ${barsHtml(c.scores, { threshold: choice ? null : c.threshold, on: new Set(c.predicted), limit })}
    ${groups}
    <p class="hint">${esc(note)}</p>
  </section>`;
}

function allProbabilitiesHtml(c) {
  return `<details class="card allprobs"><summary>All ${c.scores.length} topic probabilities</summary>
    ${barsHtml(c.scores, { threshold: c.threshold, on: new Set(c.predicted), limit: c.scores.length })}
    <p class="hint">Each bar is Jev's probability that the topic applies. Blue bars reach the threshold (dark line).</p>
  </details>`;
}

function renderClassification(result, ms) {
  $("#classify-out").innerHTML = [
    documentCard(result.document, ms),
    ...result.classifications.map((c) => (c.taxonomy_id === APS ? allProbabilitiesHtml(c) : classificationCard(c))),
    rawJson(result),
  ].join("");
}

$("#classify-out").addEventListener("click", (event) => {
  const button = event.target.closest("[data-expand]");
  if (!button) return;
  const rows = $$(".bar-row", document.getElementById(button.dataset.expand));
  const limit = Number(button.dataset.limit);
  const expanding = button.textContent.startsWith("Show all");
  rows.forEach((row, index) => (row.hidden = !expanding && index >= limit));
  button.textContent = expanding ? "Show fewer" : `Show all ${button.dataset.total}`;
});

// ---------- your labels and similar cases ----------
// Jev's assigned topics start the label set. Similar cases, with the labels people gave them, suggest what
// to add or drop. The label set lives in this page only: copy it as JSON.

const ORIGIN_LABEL = { jev: "suggested by Jev", similar: "taken from similar cases", you: "added by you" };
const SUGGESTED_TOP = 5; // the APS evaluation scores the top 5 topics
let similarToken = 0; // ignores answers that arrive after a newer classification

function taxonomyName(id) {
  if (id === "custom") return "Ad-hoc topics";
  const taxonomy = state.taxonomies.find((t) => t.id === id);
  return (taxonomy && taxonomy.name) || id;
}

function startSimilar(input) {
  if (!input || !$("#find-similar").checked || (state.health && state.health.similar === false)) return null;
  const call = input.form ? api("/similar/upload", { form: input.form }) : api("/similar", { json: input.json });
  return call.then((response) => ({ response }), (error) => ({ error })); // never an unhandled rejection
}

function afterClassification(result, similar) {
  state.classification = result;
  state.similar = null;
  state.labels = {};
  state.editing = null;
  state.allChapters = false;
  for (const c of result.classifications) {
    const byId = Object.fromEntries(c.scores.map((s) => [s.topic_id, s]));
    const ids = c.taxonomy_id === APS ? [...new Set([...c.scores.slice(0, SUGGESTED_TOP).map((s) => s.topic_id), ...c.predicted])] : c.predicted;
    state.labels[c.taxonomy_id] = new Map(
      ids.filter((id) => byId[id]).map((id) => [id, { name: byId[id].name, origin: "jev", p: byId[id].probability, status: "suggested" }])
    );
  }
  $("#classify-out .doc").insertAdjacentHTML("afterend", labelsCardHtml());
  watchLabelTree();
  const token = ++similarToken;
  if (!similar) return;
  $("#classify-out > details.raw").insertAdjacentHTML(
    "beforebegin",
    `<section id="similar-out" class="similar-block" aria-live="polite">${loading(
      "Finding similar cases: Apertus picks title words in four languages, OpenParlData searches every parliament, Jev compares each hit with this document…"
    )}</section>`
  );
  similar.then(({ response, error }) => {
    const box = $("#similar-out");
    if (token !== similarToken || !box) return;
    if (error) {
      box.innerHTML = errorBox(`Similar cases: ${error.message}`);
      return;
    }
    state.similar = response.data;
    box.innerHTML = similarHtml(response.data, response.ms);
    refreshLabels();
  });
}

function labelsCardHtml(refresh = false) {
  const result = state.classification;
  if (!result || !result.classifications.length) return "";
  const aps = result.classifications.find((c) => c.taxonomy_id === APS);
  if (aps) return topicMapHtml(aps, refresh);
  const rows = result.classifications
    .map((c) => {
      const set = state.labels[c.taxonomy_id] || new Map();
      const name = taxonomyName(c.taxonomy_id);
      const chips =
        [...set.entries()]
          .map(
            ([id, label]) => `<span class="lchip ${label.origin}" title="${esc(ORIGIN_LABEL[label.origin])}${label.p != null ? ` · Jev ${fmt(label.p)}` : ""}">${esc(label.name)}<button type="button" class="lchip-x" data-remove="${esc(c.taxonomy_id)}" data-topic="${esc(id)}" aria-label="Remove ${esc(label.name)}">${icon("x")}</button></span>`
          )
          .join("") || `<span class="none-assigned">No labels yet</span>`;
      const options = c.scores
        .filter((s) => !set.has(s.topic_id))
        .map((s) => `<option value="${esc(s.topic_id)}">${esc(s.name)} · ${fmt(s.probability)}</option>`)
        .join("");
      const hints = (state.similar ? state.similar.topics : []).filter(
        (h) => h.taxonomy_id === c.taxonomy_id && h.topic_id && !set.has(h.topic_id)
      );
      const hintRow = hints.length
        ? `<div class="hint-row"><span class="muted">Similar cases also carry</span>${hints.map((h) => hintChip(h, c)).join("")}</div>`
        : "";
      return `<div class="label-set">
        <div class="label-set-name">${esc(name)}</div>
        <div class="label-chips">${chips}<select class="label-add" data-taxonomy="${esc(c.taxonomy_id)}" aria-label="Add a topic to ${esc(name)}"><option value="">Add a topic…</option>${options}</select></div>
        ${hintRow}
      </div>`;
    })
    .join("");
  return `<section class="card labels${refresh ? " static" : ""}" id="your-labels">
    <div class="result-head"><h3>Your labels</h3><span class="result-meta">Start from Jev's suggestions, then remove, add or take topics from similar cases</span></div>
    ${rows}
    <div class="label-actions"><button type="button" class="ghost" id="copy-labels">Copy as JSON</button><span class="hint">Kept in this page only.</span></div>
  </section>`;
}

// ---------- topic map: domain colour, chapter blocks, topic tiles shaded by probability ----------

function topicGroup(topicId) {
  const sent = state.apsSent && state.apsSent.get(topicId);
  if (sent) return sent.group;
  const t = state.aps && state.aps.topics.find((x) => x.id === topicId);
  return t ? t.group : OWN_CHAPTER;
}
const pct = (p) => `${Math.round((p || 0) * 100)}%`;

function reviewRowHtml(id, lbl, c) {
  const group = topicGroup(id);
  const chapter = chapterOf(group);
  const groupLabel = label(chapter.names, group);
  const status = lbl.status === "suggested" ? "Suggested" : lbl.origin === "jev" ? "Accepted" : lbl.origin === "similar" ? "From similar cases" : "Added by you";
  const editing = state.editing === id;
  const options = editing
    ? [...new Set(c.scores.map((s) => topicGroup(s.topic_id)))]
        .map((g) => `<optgroup label="${esc(label(chapterOf(g).names, g))}">${c.scores
          .filter((s) => topicGroup(s.topic_id) === g)
          .map((s) => `<option value="${esc(s.topic_id)}"${s.topic_id === id ? " selected" : ""}>${esc(topicName(s.topic_id, s.name))} · ${fmt(s.probability)}</option>`)
          .join("")}</optgroup>`)
        .join("")
    : "";
  const displayName = topicName(id, lbl.name);
  const actions = editing
    ? `<select class="label-edit" data-from="${esc(id)}" aria-label="Replace ${esc(displayName)} with">${options}</select>
       <button type="button" class="icon" data-cancel-edit aria-label="Cancel">${icon("x", "i")}</button>`
    : `${lbl.status === "suggested" ? `<button type="button" class="act accept" data-accept="${esc(id)}" title="Accept">${icon("check")}<span>Accept</span></button>` : ""}
       <button type="button" class="act" data-edit="${esc(id)}" title="Change to another topic">${icon("pencil")}<span>Edit</span></button>
       <button type="button" class="act danger" data-remove="${APS}" data-topic="${esc(id)}" title="Remove this label">${icon("x")}<span>Remove</span></button>`;
  return `<li class="review ${lbl.status}" style="--hue:${hue(group)}">
    <span class="swatch" aria-hidden="true"></span>
    <div class="review-path"><span class="review-chapter">${esc(groupLabel)}</span><strong>${esc(displayName)}</strong></div>
    <div class="review-p"><span class="meter"><span style="width:${pct(lbl.p)}"></span></span><span class="num">${fmt(lbl.p)}</span></div>
    <span class="status-tag">${lbl.status === "suggested" ? "" : icon("check")}${esc(status)}</span>
    <div class="review-actions">${actions}</div>
  </li>`;
}

// ---------- label tree: affair → chapters → topics. Nodes are HTML; the curved links are SVG drawn between them. ----------

function labelTreeHtml(set, chapterP) {
  if (!set.size) return "";
  const groups = [...new Set([...set.keys()].map(topicGroup))].sort((a, b) => (chapterP.get(b) || 0) - (chapterP.get(a) || 0));
  const doc = state.classification && state.classification.document;
  const title = doc ? doc.title || doc.reference || "This affair" : "This affair";
  const short = title.length > 90 ? `${title.slice(0, 88)}…` : title;
  const branches = groups
    .map((g) => {
      const chapter = chapterOf(g);
      const chapterLabel = label(chapter.names, g);
      const domainData = state.aps && chapter.domainIndex ? (state.aps.domains[chapter.domainIndex - 1] || {}) : {};
      const domain = label(domainData.names, domainData.name || "");
      const topics = [...set.entries()]
        .filter(([id]) => topicGroup(id) === g)
        .sort((a, b) => (b[1].p || 0) - (a[1].p || 0))
        .map(([id, l]) => {
          const displayName = topicName(id, l.name);
          return `<div class="tnode topic ${l.status}" data-parent="${esc(g)}" data-d="${chapter.domainIndex}" title="${esc(displayName)} · ${esc(l.status === "suggested" ? "suggested" : "accepted")}">
            ${l.status === "suggested" ? "" : icon("check")}<span class="tname">${esc(displayName)}</span><span class="tp num">${fmt(l.p)}</span>
          </div>`;
        })
        .join("");
      return `<div class="tbranch" style="--hue:${hue(g)}">
        <div class="tnode chapter" data-chapter="${esc(g)}" data-d="${chapter.domainIndex}">
          <span class="swatch" aria-hidden="true"></span>
          <span class="tchapter"><span class="tname">${esc(chapterLabel)}</span>${domain ? `<span class="tdomain">${esc(domain)}</span>` : ""}</span>
          <span class="tp num" title="Highest topic probability in this chapter">${fmt(chapterP.get(g))}</span>
        </div>
        <div class="tleaves">${topics}</div>
      </div>`;
    })
    .join("");
  return `<div class="ltree" id="label-tree" role="group" aria-label="Chapters and topics assigned to this affair">
    <svg class="tlinks" aria-hidden="true"></svg>
    <div class="troot-col"><div class="tnode troot" title="${esc(title)}">${icon("text", "i")}<span>${esc(short)}</span></div></div>
    <div class="tbranches">${branches}</div>
  </div>`;
}

function drawLabelTree() {
  const tree = $("#label-tree");
  if (!tree) return;
  const svg = $(".tlinks", tree);
  if (getComputedStyle(svg).display === "none") return;
  const box = tree.getBoundingClientRect();
  svg.setAttribute("width", box.width);
  svg.setAttribute("height", box.height);
  svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
  const right = (el) => { const r = el.getBoundingClientRect(); return [r.right - box.left, r.top + r.height / 2 - box.top]; };
  const left = (el) => { const r = el.getBoundingClientRect(); return [r.left - box.left, r.top + r.height / 2 - box.top]; };
  const curve = ([x1, y1], [x2, y2], d, dashed) => {
    const dx = Math.max(24, (x2 - x1) / 2);
    return `<path d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}" style="stroke:var(--d${d})"${dashed ? ' class="dashed"' : ""}/>`;
  };
  const root = $(".troot", tree);
  const paths = [];
  for (const branch of $$(".tbranch", tree)) {
    const chapter = $(".tnode.chapter", branch);
    const d = chapter.dataset.d;
    const leaves = $$(".tnode.topic", branch);
    paths.push(curve(right(root), left(chapter), d, leaves.every((n) => n.classList.contains("suggested"))));
    for (const leaf of leaves) paths.push(curve(right(chapter), left(leaf), d, leaf.classList.contains("suggested")));
  }
  svg.innerHTML = paths.join("");
}

let treeObserver = null;
function watchLabelTree() {
  const tree = $("#label-tree");
  if (treeObserver) treeObserver.disconnect();
  if (!tree) return;
  if (!treeObserver) treeObserver = new ResizeObserver(() => requestAnimationFrame(drawLabelTree));
  treeObserver.observe(tree);
  drawLabelTree();
}

function topicMapHtml(c, refresh) {
  const set = state.labels[APS] || new Map();
  const byGroup = new Map();
  for (const s of c.scores) {
    const g = topicGroup(s.topic_id);
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push(s);
  }
  const chapterP = new Map(c.groups.map((g) => [g.name, g.probability]));
  // Sort by probability by default; sort by chapter code when "show all" is on
  const chapters = [...byGroup.keys()].sort((a, b) =>
    state.allChapters
      ? (chapterOf(a).code || "").localeCompare(chapterOf(b).code || "", undefined, { numeric: true })
      : (chapterP.get(b) || 0) - (chapterP.get(a) || 0)
  );
  const labelled = new Set([...set.keys()].map(topicGroup));
  const firstShown = Math.max(6, chapters.filter((g) => labelled.has(g)).length);
  // Filter chapters by the selected domain (legend click)
  const visibleChapters = state.domainFilter == null
    ? chapters
    : chapters.filter((g) => chapterOf(g).domainIndex === state.domainFilter);
  const blocks = visibleChapters
    .map((g, index) => {
      const chapter = chapterOf(g);
      const chapterLabel = label(chapter.names, g);
      const p = chapterP.get(g) || 0;
      const tiles = byGroup
        .get(g)
        .map((s) => {
          const on = set.get(s.topic_id);
          const name = topicName(s.topic_id, s.name);
          return `<button type="button" class="tile${on ? ` on ${on.status}` : ""}" data-tile="${esc(s.topic_id)}" aria-pressed="${on ? "true" : "false"}" style="--p:${pct(s.probability)};--pn:${(s.probability || 0).toFixed(3)}" title="${esc(name)}: ${s.probability.toFixed(3)}${on ? " · in your labels, click to remove" : " · click to add as a label"}">
            <span class="tile-name">${on ? icon("check") : ""}${esc(name)}</span><span class="tile-p num">${fmt(s.probability)}</span><span class="tile-bar"></span>
          </button>`;
        })
        .join("");
      return `<div class="chapter${labelled.has(g) ? " has-labels" : ""}" style="--hue:${hue(g)};--p:${pct(p)}"${index >= firstShown && !state.allChapters ? " hidden" : ""}>
        <div class="chapter-head"><span class="swatch" aria-hidden="true"></span><span class="chapter-name">${esc(chapter.code ? `${chapter.code} ${chapterLabel}` : chapterLabel)}</span><span class="chapter-p num" title="Highest topic probability in this chapter">${fmt(p)}</span></div>
        <div class="tiles">${tiles}</div>
      </div>`;
    })
    .join("");
  const legend = state.aps
    ? state.aps.domains
        .map((d, i) => `<button type="button" class="legend-item${state.domainFilter === i + 1 ? " active" : ""}" data-domain="${i + 1}" aria-pressed="${state.domainFilter === i + 1}"><span class="swatch" style="--hue:var(--d${i + 1})"></span>${esc(label(d.names, d.name))}</button>`)
        .join("") + (byGroup.has(OWN_CHAPTER) ? `<button type="button" class="legend-item${state.domainFilter === 0 ? " active" : ""}" data-domain="0" aria-pressed="${state.domainFilter === 0}"><span class="swatch" style="--hue:var(--d0)"></span>${OWN_CHAPTER}</button>` : "")
    : "";
  const rows = [...set.entries()].sort((a, b) => (b[1].p || 0) - (a[1].p || 0)).map(([id, l]) => reviewRowHtml(id, l, c)).join("");
  const pending = [...set.values()].filter((l) => l.status === "suggested").length;
  const glance = labelTreeHtml(set, chapterP);
  return `<section class="card topicmap${refresh ? " static" : ""}" id="your-labels">
    <div class="result-head"><h3>Where this affair belongs</h3><span class="result-meta">Année Politique Suisse · ${c.scores.length} topics · threshold ${fmt(c.threshold)} · ${esc(c.model)}</span></div>
    ${glance || `<div class="glance"><span class="none-assigned">No labels. Click a topic below to add one.</span></div>`}
    <div class="review-head"><span class="subhead">Your labels</span><span class="hint">${pending ? `${pending} suggested ${pending === 1 ? "label waits" : "labels wait"} for your review: accept, edit or remove.` : "All labels reviewed."}</span>${pending ? `<button type="button" class="ghost tiny" data-accept-all>${icon("check")}Accept all</button>` : ""}</div>
    <ol class="reviews">${rows}</ol>
    <details class="explore" id="explore-map"${state.mapOpen ? " open" : ""}>
      <summary><span>Explore all chapters and topics</span><span class="hint">${visibleChapters.length} of ${chapters.length} chapters · colour = domain, stronger = more likely · click a topic to add or remove it</span></summary>
      <div class="explore-body">
        <div class="legend">${legend}</div>
        <div class="chapters">${blocks}</div>
        ${chapters.length > firstShown ? `<button type="button" class="ghost more" data-all-chapters>${state.allChapters ? "Show fewer chapters" : `Show all ${visibleChapters.length} chapters`}</button>` : ""}
      </div>
    </details>
    <div class="label-actions"><button type="button" class="ghost" id="copy-labels">Copy as JSON</button><span class="hint">Labels are suggestions; nothing is saved outside this page.</span></div>
  </section>`;
}

function hintChip(hint, classification) {
  const score = classification.scores.find((s) => s.topic_id === hint.topic_id);
  const cases = `${hint.cases} similar ${hint.cases === 1 ? "case" : "cases"}`;
  const name = hint.taxonomy_id === APS ? topicName(hint.topic_id, hint.name) : hint.name;
  return `<button type="button" class="chip suggest" data-hint="${esc(hint.taxonomy_id)}" data-topic="${esc(hint.topic_id)}" title="${esc(hint.source)}: ${cases}${score ? ` · Jev ${fmt(score.probability)}` : ""}">${icon("plus")}${esc(name)}<span class="count">${hint.cases}</span></button>`;
}

function similarTopicsHtml(result) {
  if (!result.topics.length) {
    return `<p class="hint">None of these cases has labels in the labelled data, which covers federal affairs, St. Gallen, Thurgau, the city of Zug, Zurich and the PolitMonitor digitalisation tag.</p>`;
  }
  return result.topics
    .map((h) => {
      const set = h.taxonomy_id ? state.labels[h.taxonomy_id] : null;
      let action;
      if (set && h.topic_id && set.has(h.topic_id)) action = `<span class="state">In your labels</span>`;
      else if (set && h.topic_id)
        action = `<button type="button" class="ghost tiny" data-hint="${esc(h.taxonomy_id)}" data-topic="${esc(h.topic_id)}">${icon("plus")}Add</button>`;
      else
        action = `<button type="button" class="ghost tiny" data-adhoc="${esc(h.name)}" title="Adds it to the label set as a new topic; classify again to score it">${icon("plus")}Add to the label set</button>`;
      const displayName = h.taxonomy_id === APS && h.topic_id ? topicName(h.topic_id, h.name) : h.name;
      return `<div class="topic-hint"><span class="topic-hint-name">${esc(displayName)}</span><span class="muted">${h.cases} ${h.cases === 1 ? "case" : "cases"} · ${esc(h.source)}</span>${action}</div>`;
    })
    .join("");
}

function band(p) {
  if (p == null) return "";
  const [cls, text] = p >= 0.7 ? ["same", "Same issue"] : p >= 0.4 ? ["related", "Related"] : ["loose", "Loosely related"];
  return `<span class="band ${cls}">${text}</span>`;
}

function caseHtml(c) {
  const affair = c.affair;
  const languages = [...new Set(c.matched_by.map((m) => m.language))];
  const title = bestTitle(affair.title, languages);
  const type = (affair.type && (affair.type.en || affair.type.de)) || "";
  const similarity =
    c.similarity == null
      ? ""
      : `<div class="relevance" title="Jev probability that this affair deals with the same specific issue">
          <span class="track"><span class="fill" style="width:${(c.similarity * 100).toFixed(1)}%"></span></span>${fmt(c.similarity)}
        </div>${band(c.similarity)}`;
  const labels = c.labels.length
    ? `<div class="case-labels">${c.labels
        .map((l) => `<span class="klabel${l.taxonomy_id ? "" : " text"}" title="${esc(l.source)}">${esc(l.name)}</span>`)
        .join("")}</div>`
    : "";
  const same = c.same_title.length
    ? `<details class="same"><summary>${c.same_title.length} more with the same title</summary>${c.same_title
        .map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.number || s.id)}${s.begin_date ? ` · ${esc(s.begin_date)}` : ""}</a>`)
        .join("")}</details>`
    : "";
  const matched = c.matched_by.map((m) => `${m.language} “${m.query}”`).join(" · ");
  return `<li class="card hit">
    <div class="hit-meta">
      <span class="body">${esc(parliamentName(affair.body_key))}</span>
      ${type ? `<span>${esc(type)}</span>` : ""}
      ${affair.number ? `<span class="mono">${esc(affair.number)}</span>` : ""}
      ${affair.begin_date ? `<span>${esc(affair.begin_date)}</span>` : ""}
    </div>
    <div class="hit-side">
      ${similarity}
      <div class="hit-actions">
        <a class="ghost" href="${esc(affair.url)}" target="_blank" rel="noopener">Open${icon("external")}</a>
        <button type="button" class="ghost go" data-classify="${esc(affair.url)}">Classify${icon("arrow")}</button>
      </div>
    </div>
    <div class="hit-title">${esc(title.text)}<span class="tl">${esc(title.lang)}</span></div>
    ${labels}
    <div class="hit-matched">Found by ${esc(matched)}</div>
    ${same}
  </li>`;
}

function similarHtml(result, ms) {
  const bodies = new Set(result.cases.map((c) => c.affair.body_key));
  const languages = new Set(result.cases.flatMap((c) => c.matched_by.map((m) => m.language)));
  const runs = {};
  for (const q of result.queries) (runs[q.language] ||= []).push(`${q.query} (${q.hits > 60 ? "60+" : q.hits})`);
  const words = Object.entries(result.keywords)
    .filter(([, list]) => list.length)
    .map(
      ([lang, list]) => `<div class="query-line"><span class="lang">${esc(lang)}</span><div>${list
        .map((w) => `<span class="qchip">${esc(w)}</span>`)
        .join("")}<div class="hit-matched">Searched: ${esc((runs[lang] || []).join(" · ") || "no title has these words")}</div></div></div>`
    )
    .join("");
  const parts = [
    `<div class="card similar-head">
      <div class="result-head"><h3>Similar cases</h3><span class="result-meta">${result.cases.length} shown of ${result.candidates} found · ${bodies.size} ${bodies.size === 1 ? "parliament" : "parliaments"} · matched in ${esc([...languages].map((l) => LANG_NAMES[l] || l).join(", ") || "no language")} · ${(ms / 1000).toFixed(1)} s</span></div>
      ${result.subject ? `<p class="similar-subject"><span class="muted">Apertus read the subject as</span> ${esc(result.subject)}</p>` : ""}
      <details class="options"><summary>Words searched in titles</summary><div class="queries-inner">${words}</div>
        <p class="hint">A word that matches at most 60 titles is searched on its own. Broader words are only searched together with another word, except the first two, which name the subject.</p></details>
      <div class="subhead">Labels in these cases</div>
      <div id="similar-topics" class="similar-topics">${similarTopicsHtml(result)}</div>
      <p class="hint">${result.ranked ? "Ordered by Jev's probability that the case deals with the same specific issue." : "Ordered by how specific the matching words are."}</p>
    </div>`,
    ...result.warnings.map((w) => `<div class="warning">${esc(w)}</div>`),
  ];
  parts.push(
    result.cases.length
      ? `<details class="explore similar-list">
          <summary><span>Show the ${result.cases.length} similar ${result.cases.length === 1 ? "case" : "cases"}</span><span class="hint">${[
            result.cases.filter((c) => c.similarity != null && c.similarity >= 0.7).length &&
              `${result.cases.filter((c) => c.similarity != null && c.similarity >= 0.7).length} on the same issue`,
            `${bodies.size} ${bodies.size === 1 ? "parliament" : "parliaments"}`,
            [...languages].map((l) => l.toUpperCase()).join(" · "),
          ]
            .filter(Boolean)
            .join(" · ")}</span></summary>
          <div class="explore-body"><ol class="hits">${result.cases.map(caseHtml).join("")}</ol></div>
        </details>`
      : `<div class="empty"><h2>No similar cases found</h2><p>No title in OpenParlData shares the words this document is about. Pasting a longer text can help.</p></div>`
  );
  return parts.join("");
}

function refreshLabels() {
  const card = $("#your-labels");
  if (card) card.outerHTML = labelsCardHtml(true);
  watchLabelTree();
  const topics = $("#similar-topics");
  if (topics && state.similar) topics.innerHTML = similarTopicsHtml(state.similar);
}

function addLabel(taxonomyId, topicId, origin) {
  const classification = state.classification && state.classification.classifications.find((c) => c.taxonomy_id === taxonomyId);
  const set = state.labels[taxonomyId];
  if (!classification || !set || set.has(topicId)) return;
  const score = classification.scores.find((s) => s.topic_id === topicId);
  set.set(topicId, { name: score ? score.name : topicId, origin, p: score ? score.probability : null, status: "accepted" });
  refreshLabels();
}

async function copyLabels(button) {
  const labels = Object.fromEntries(
    Object.entries(state.labels).map(([id, set]) => [
      id,
      [...set.entries()].map(([topicId, l]) => ({
        topic_id: topicId,
        name: l.name,
        ...(id === APS ? { chapter: topicGroup(topicId) } : {}),
        origin: l.origin,
        status: l.status || "accepted",
        probability: l.p,
      })),
    ])
  );
  try {
    await navigator.clipboard.writeText(JSON.stringify(labels, null, 2));
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy failed";
  }
  setTimeout(() => (button.textContent = "Copy as JSON"), 1600);
}

$("#classify-out").addEventListener("click", (event) => {
  const remove = event.target.closest("[data-remove]");
  if (remove) {
    const set = state.labels[remove.dataset.remove];
    if (set) set.delete(remove.dataset.topic);
    refreshLabels();
    return;
  }
  const hint = event.target.closest("[data-hint]");
  if (hint) return addLabel(hint.dataset.hint, hint.dataset.topic, "similar");
  const adhoc = event.target.closest("[data-adhoc]");
  if (adhoc) {
    addApsTopic(adhoc.dataset.adhoc);
    adhoc.outerHTML = `<span class="state">Added to the label set</span>`;
    return;
  }
  const set = state.labels[APS];
  const accept = event.target.closest("[data-accept]");
  if (accept && set && set.has(accept.dataset.accept)) {
    set.get(accept.dataset.accept).status = "accepted";
    return refreshLabels();
  }
  if (event.target.closest("[data-accept-all]") && set) {
    set.forEach((l) => (l.status = "accepted"));
    return refreshLabels();
  }
  const edit = event.target.closest("[data-edit]");
  if (edit) {
    state.editing = edit.dataset.edit;
    refreshLabels();
    const select = $("#your-labels select.label-edit");
    if (select) select.focus();
    return;
  }
  if (event.target.closest("[data-cancel-edit]")) {
    state.editing = null;
    return refreshLabels();
  }
  const tile = event.target.closest("[data-tile]");
  if (tile && set) {
    const id = tile.dataset.tile;
    if (set.has(id)) {
      set.delete(id);
      refreshLabels();
    } else addLabel(APS, id, "you");
    return;
  }
  if (event.target.closest("[data-all-chapters]")) {
    state.allChapters = !state.allChapters;
    return refreshLabels();
  }
  const domainBtn = event.target.closest("[data-domain]");
  if (domainBtn) {
    const domain = Number(domainBtn.dataset.domain);
    state.domainFilter = state.domainFilter === domain ? null : domain;
    return refreshLabels();
  }
  const classify = event.target.closest("[data-classify]");
  if (classify) {
    setMode("link");
    $("#ref").value = classify.dataset.classify;
    window.scrollTo({ top: 0, behavior: "smooth" });
    $("#classify-form").requestSubmit();
    return;
  }
  const copy = event.target.closest("#copy-labels");
  if (copy) copyLabels(copy);
});
$("#classify-out").addEventListener("toggle", (event) => {
  if (event.target.id === "explore-map") state.mapOpen = event.target.open;
}, true);
$("#classify-out").addEventListener("change", (event) => {
  const select = event.target.closest("select.label-add");
  if (select && select.value) addLabel(select.dataset.taxonomy, select.value, "you");
  const change = event.target.closest("select.label-edit");
  const set = state.labels[APS];
  if (change && set && change.value !== change.dataset.from) {
    const old = set.get(change.dataset.from);
    const score = state.classification.classifications.find((c) => c.taxonomy_id === APS).scores.find((s) => s.topic_id === change.value);
    // keep the list order stable: rebuild the map with the replacement in place of the old label
    state.labels[APS] = new Map(
      [...set.entries()]
        .filter(([id]) => id !== change.value)
        .map(([id, l]) => (id === change.dataset.from ? [change.value, { name: score.name, origin: "you", p: score.probability, status: "accepted" }] : [id, l]))
    );
    state.editing = null;
    if (old) refreshLabels();
  }
});

// ---------- start ----------

// Deep links for demos: ?q=… runs a search, ?ref=… classifies (optionally &taxonomies=a,b and &rank=0).
(async function start() {
  const params = new URLSearchParams(location.search);
  let tab = params.get("ref") ? "classify" : params.get("q") ? "search" : null;
  tab = tab || (location.hash === "#classify" ? "classify" : location.hash === "#search" ? "search" : null);
  if (!tab) {
    try {
      tab = localStorage.getItem("console-tab");
    } catch {
      tab = null;
    }
  }
  selectTab(tab === "classify" ? "classify" : "search");
  loadHealth();
  await Promise.all([loadParliaments(), loadTaxonomies()]);

  if (params.get("q")) {
    $("#q").value = params.get("q");
    if (params.get("rank") === "0") $("#rank").checked = false;
    $("#search-form").requestSubmit();
  } else if (params.get("ref")) {
    setMode("link");
    $("#ref").value = params.get("ref");
    $("#classify-form").requestSubmit();
  }
})();
