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

const state = { parliaments: {}, taxonomies: [] };

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

const loading = (text) => `<div class="loading"><span class="spinner" aria-hidden="true"></span>${esc(text)}</div>`;
const errorBox = (text) => `<div class="error" role="alert">${esc(text)}</div>`;
const rawJson = (data) =>
  `<details class="raw"><summary>Raw response</summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>`;

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.textContent = label;
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
$("#tab-classify").addEventListener("click", () => selectTab("classify"));

// ---------- startup data ----------

async function loadHealth() {
  const box = $("#status");
  const pill = (ok, label, hint) =>
    `<span class="pill ${ok ? "good" : "bad"}" title="${esc(hint)}">${esc(label)}</span>`;
  try {
    const { data } = await api("/health");
    box.innerHTML =
      pill(data.search, `Search · ${data.apertus_model}`, data.search ? "Apertus is configured" : "APERTUS_API_KEY is missing") +
      pill(data.classification, `Classify · ${data.jev_model}`, data.classification ? "Jev is configured" : "TYPESAFE_API_KEY is missing");
  } catch (error) {
    box.innerHTML = `<span class="pill bad">${esc(error.message)}</span>`;
  }
}

async function loadTaxonomies() {
  const box = $("#taxonomies");
  try {
    const { data } = await api("/taxonomies");
    state.taxonomies = data;
    box.innerHTML = data
      .map((t) => {
        const note =
          t.id === "curia_subject_areas" ? " · labelled, accuracy known" : t.id === "aps_topics" ? " · no labelled examples" : "";
        return `<label class="taxonomy-option">
          <input type="checkbox" name="taxonomy" value="${esc(t.id)}"${t.id === "curia_subject_areas" ? " checked" : ""}>
          <span>${esc(t.name)} <span class="muted">· ${t.topics} ${t.topics === 1 ? "topic" : "topics"}</span></span>
          <small>${esc(KIND_LABEL[t.kind] || t.kind)}${esc(note)}</small>
        </label>`;
      })
      .join("");
  } catch (error) {
    box.innerHTML = errorBox(error.message);
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
    scope: $("#scope").value,
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
    `<div class="summary">
      <span><strong>${result.unique_affairs}</strong> affairs found</span>
      <span>showing <strong>${result.hits.length}</strong></span>
      <span>from <strong>${bodies.size}</strong> parliaments</span>
      <span>matched in ${esc([...languages].map((l) => LANG_NAMES[l] || l).join(", ") || "no language")}</span>
      <span>${result.ranked ? "ranked by Jev relevance" : "ordered by number of matching queries, then date"}</span>
      <span class="muted">${(ms / 1000).toFixed(1)} s</span>
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
      `<div class="empty"><h2>No affairs matched</h2><p>Try a broader request or more languages, or match in texts and documents under Options.</p></div>`
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
        <a class="ghost" href="${esc(affair.url)}" target="_blank" rel="noopener">Open ↗</a>
        <button type="button" class="ghost" data-classify="${esc(affair.url)}">Classify →</button>
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

function addTopic(name = "", description = "") {
  const existing = $$("#custom-topics .topic-name").map((input) => input.value.trim().toLowerCase());
  if (name && existing.includes(name.toLowerCase())) return;
  const row = $("#topic-row").content.firstElementChild.cloneNode(true);
  $(".topic-name", row).value = name;
  $(".topic-desc", row).value = description;
  $(".remove", row).addEventListener("click", () => row.remove());
  $("#custom-topics").appendChild(row);
  if (!name) $(".topic-name", row).focus();
}
$("#add-topic").addEventListener("click", () => addTopic());
$$("#classify-form [data-topic]").forEach((chip) => chip.addEventListener("click", () => addTopic(chip.dataset.topic)));

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
  const taxonomies = $$('input[name="taxonomy"]:checked').map((input) => input.value);
  const customTopics = $$("#custom-topics .topic")
    .map((row) => ({ name: $(".topic-name", row).value.trim(), description: $(".topic-desc", row).value.trim() || null }))
    .filter((topic) => topic.name);
  const threshold = $("#override").checked ? Number($("#threshold").value) : null;
  if (!taxonomies.length && !customTopics.length) {
    out.innerHTML = errorBox("Pick a label set or add an ad-hoc topic.");
    return;
  }

  let request;
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
        language: $("#language").value || null,
        include_answer: $("#include-answer").checked,
        threshold,
      },
    });
  } else if (mode === "text") {
    const text = $("#text").value.trim();
    if (!text) {
      out.innerHTML = errorBox("Paste the text to classify.");
      return;
    }
    request = api("/classify", {
      json: { text, title: $("#title").value.trim() || null, taxonomies, custom_topics: customTopics, threshold },
    });
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
    const title = $("#file-title").value.trim();
    if (title) form.append("title", title);
    if (threshold != null) form.append("threshold", String(threshold));
    request = api("/classify/upload", { form });
  }

  const button = $("#classify-submit");
  setBusy(button, true, "Classifying…");
  out.innerHTML = loading("Reading the document and asking Jev…");
  try {
    const { data, ms } = await request;
    renderClassification(data, ms);
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
    ${affair ? `<div><a class="ghost" href="${esc(affair.url)}" target="_blank" rel="noopener">Open on OpenParlData ↗</a></div>` : ""}
  </div>`;
}

let barsCounter = 0;
function barsHtml(scores, { threshold, on, limit }) {
  const id = `bars-${++barsCounter}`;
  const rows = scores
    .map((score, index) => {
      const assigned = on.has(score.topic_id);
      const marker =
        threshold == null ? "" : `<span class="threshold" style="left:calc(${(threshold * 100).toFixed(1)}% - 1px)"></span>`;
      return `<div class="bar-row${assigned ? " on" : ""}"${index >= limit ? " hidden" : ""} title="${esc(score.name)}: ${score.probability.toFixed(3)}">
        <span class="name">${esc(score.name)}</span>
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

function renderClassification(result, ms) {
  $("#classify-out").innerHTML = [
    documentCard(result.document, ms),
    ...result.classifications.map(classificationCard),
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
    const wanted = (params.get("taxonomies") || "").split(",").filter(Boolean);
    if (wanted.length) $$('input[name="taxonomy"]').forEach((input) => (input.checked = wanted.includes(input.value)));
    setMode("link");
    $("#ref").value = params.get("ref");
    $("#classify-form").requestSubmit();
  }
})();
