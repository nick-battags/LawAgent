let cachedDocs = [];

document.querySelectorAll(".sidebar-link").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".sidebar-link").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".admin-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.querySelector(`#panel-${btn.dataset.panel}`).classList.add("active");
    if (btn.dataset.panel === "documents") {
      renderDocumentTable(cachedDocs);
    }
  });
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function tagBadge(label, value) {
  if (!value) return "";
  return `<span class="tag tag-${label}">${escapeHtml(value)}</span>`;
}

function renderDashboard(data) {
  document.getElementById("statBackend").textContent = data.backend || "--";
  document.getElementById("statDocs").textContent = data.document_count || 0;
  document.getElementById("statChunks").textContent = data.chunk_count || 0;
  document.getElementById("statCategories").textContent = Object.keys(data.categories || {}).length;

  const CATEGORY_GROUPS = {
    "M&A Legal": ["ancillary_agreements", "asset_acquisition", "due_diligence", "corporate_templates_market_data", "ip_technology", "employment_benefits", "regulatory", "environmental", "real_estate", "purchase_agreement", "general_ma"],
    "Guides & Playbooks": ["guide", "practical_guidance", "playbook"],
    "Notes & Training": ["capability_notes", "prompt_engineering", "training_instructions"],
  };

  const cats = document.getElementById("categoryBreakdown");
  const catEntries = Object.entries(data.categories || {});
  if (catEntries.length) {
    let html = "";
    for (const [groupLabel, groupCats] of Object.entries(CATEGORY_GROUPS)) {
      const matched = catEntries.filter(([name]) => groupCats.includes(name));
      if (matched.length) {
        html += `<div style="margin-bottom:10px"><strong style="font-size:.85rem;color:var(--fg-muted)">${escapeHtml(groupLabel)}</strong><br>`;
        html += matched.map(([name, count]) => `<span class="tag">${escapeHtml(name.replaceAll("_", " "))}: ${count}</span>`).join(" ");
        html += `</div>`;
      }
    }
    const ungrouped = catEntries.filter(([name]) => !Object.values(CATEGORY_GROUPS).flat().includes(name));
    if (ungrouped.length) {
      html += `<div style="margin-bottom:10px"><strong style="font-size:.85rem;color:var(--fg-muted)">Other</strong><br>`;
      html += ungrouped.map(([name, count]) => `<span class="tag">${escapeHtml(name.replaceAll("_", " "))}: ${count}</span>`).join(" ");
      html += `</div>`;
    }
    cats.innerHTML = html;
  } else {
    cats.innerHTML = "";
  }

  const docList = document.getElementById("dashboardDocList");
  const docs = data.documents || [];
  cachedDocs = docs;
  if (!docs.length) {
    docList.innerHTML = `<div class="admin-card wide"><p class="muted">No documents ingested yet. Use the Corpus Management panel to add training data.</p></div>`;
    return;
  }
  docList.innerHTML = docs.map((doc) => `
    <div class="admin-card" style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <strong>${escapeHtml(doc.title)}</strong>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <span class="tag">${escapeHtml(doc.category.replaceAll("_", " "))}</span>
          ${tagBadge("jurisdiction", doc.jurisdiction)}
          ${tagBadge("stance", doc.deal_stance)}
          ${tagBadge("structure", doc.deal_structure)}
        </div>
      </div>
      <p class="muted" style="margin:6px 0 0">${escapeHtml(doc.document_type)} · ${doc.chunk_count} chunks · ${escapeHtml(doc.source_system)}</p>
    </div>
  `).join("");

  renderDocumentTable(docs);
}

function renderDocumentTable(docs) {
  const container = document.getElementById("documentTable");
  if (!docs.length) {
    container.innerHTML = `<p class="muted">No documents in the corpus yet.</p>`;
    return;
  }
  container.innerHTML = `
    <table class="doc-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Category</th>
          <th>Type</th>
          <th>Jurisdiction</th>
          <th>Stance</th>
          <th>Structure</th>
          <th>Source</th>
          <th>Chunks</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${docs.map((doc) => `
          <tr data-doc-id="${doc.id}">
            <td><strong>${escapeHtml(doc.title)}</strong></td>
            <td><span class="tag">${escapeHtml(doc.category.replaceAll("_", " "))}</span></td>
            <td>${escapeHtml(doc.document_type)}</td>
            <td>${doc.jurisdiction ? `<span class="tag tag-jurisdiction">${escapeHtml(doc.jurisdiction)}</span>` : '<span class="muted">--</span>'}</td>
            <td>${doc.deal_stance ? `<span class="tag tag-stance">${escapeHtml(doc.deal_stance)}</span>` : '<span class="muted">--</span>'}</td>
            <td>${doc.deal_structure ? `<span class="tag tag-structure">${escapeHtml(doc.deal_structure)}</span>` : '<span class="muted">--</span>'}</td>
            <td>${escapeHtml(doc.source_system)}</td>
            <td>${doc.chunk_count}</td>
            <td>
              <button class="edit-tags-btn secondary" data-doc-id="${doc.id}" data-jurisdiction="${escapeHtml(doc.jurisdiction || "")}" data-stance="${escapeHtml(doc.deal_stance || "")}" data-structure="${escapeHtml(doc.deal_structure || "")}">Edit tags</button>
              <button class="delete-doc-btn ghost" data-doc-id="${doc.id}" data-title="${escapeHtml(doc.title)}" style="color:var(--red);margin-left:4px">Delete</button>
            </td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;

  container.querySelectorAll(".edit-tags-btn").forEach((btn) => {
    btn.addEventListener("click", () => openTagEditor(btn));
  });

  container.querySelectorAll(".delete-doc-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const docId = btn.dataset.docId;
      const title = btn.dataset.title;
      if (!confirm(`Delete "${title}" and all its chunks from the corpus?`)) return;
      btn.disabled = true;
      btn.textContent = "Deleting...";
      try {
        const resp = await fetch(`/api/v2/corpus/document/${docId}`, { method: "DELETE" });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Delete failed");
        refreshDashboard();
      } catch (err) {
        alert("Delete failed: " + err.message);
        btn.disabled = false;
        btn.textContent = "Delete";
      }
    });
  });
}

function openTagEditor(btn) {
  const docId = btn.dataset.docId;
  const row = btn.closest("tr");
  const next = row.nextElementSibling;
  if (next && next.classList.contains("tag-editor-row")) { next.remove(); return; }

  const editorRow = document.createElement("tr");
  editorRow.className = "tag-editor-row";
  editorRow.innerHTML = `
    <td colspan="9" style="padding:12px;background:var(--bg-raised)">
      <div class="inline-fields" style="align-items:flex-end">
        <label>Jurisdiction
          <select class="te-jurisdiction">
            <option value="">--</option>
            <option value="Delaware">Delaware</option>
            <option value="New York">New York</option>
            <option value="California">California</option>
            <option value="Texas">Texas</option>
            <option value="Nevada">Nevada</option>
            <option value="Illinois">Illinois</option>
            <option value="United Kingdom">United Kingdom</option>
            <option value="Canada">Canada</option>
            <option value="Federal/Multi-State">Federal/Multi-State</option>
          </select>
        </label>
        <label>Stance
          <select class="te-stance">
            <option value="">--</option>
            <option value="pro-buyer">Pro-Buyer</option>
            <option value="pro-seller">Pro-Seller</option>
            <option value="balanced">Balanced</option>
          </select>
        </label>
        <label>Structure
          <select class="te-structure">
            <option value="">--</option>
            <option value="asset purchase">Asset Purchase</option>
            <option value="stock purchase">Stock Purchase</option>
            <option value="merger">Merger</option>
          </select>
        </label>
        <button class="primary te-save">Save</button>
        <button class="secondary te-cancel">Cancel</button>
      </div>
      <p class="te-status muted" style="margin:6px 0 0"></p>
    </td>
  `;
  row.after(editorRow);

  const jSel = editorRow.querySelector(".te-jurisdiction");
  const sSel = editorRow.querySelector(".te-stance");
  const stSel = editorRow.querySelector(".te-structure");
  jSel.value = btn.dataset.jurisdiction || "";
  sSel.value = btn.dataset.stance || "";
  stSel.value = btn.dataset.structure || "";

  editorRow.querySelector(".te-cancel").addEventListener("click", () => editorRow.remove());
  editorRow.querySelector(".te-save").addEventListener("click", async () => {
    const status = editorRow.querySelector(".te-status");
    status.textContent = "Saving...";
    try {
      const resp = await fetch(`/api/v2/corpus/document/${docId}/tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jurisdiction: jSel.value,
          deal_stance: sSel.value,
          deal_structure: stSel.value,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Update failed");
      status.textContent = "Saved!";
      editorRow.remove();
      refreshDashboard();
    } catch (err) {
      status.innerHTML = `<span style="color:var(--red)">${escapeHtml(err.message)}</span>`;
    }
  });
}

async function refreshDashboard() {
  try {
    const data = await getJson("/api/v2/corpus/status");
    renderDashboard(data);
  } catch (err) {
    document.getElementById("statBackend").textContent = "error";
  }
}

document.getElementById("adminIngest").addEventListener("click", async () => {
  const btn = document.getElementById("adminIngest");
  btn.disabled = true;
  btn.textContent = "Ingesting...";
  const result = document.getElementById("ingestResult");
  try {
    const data = await getJson("/api/v2/corpus/ingest-deposits", { method: "POST" });
    result.innerHTML = `<strong>Done.</strong> ${data.results.length} files scanned. Corpus updated.`;
    refreshDashboard();
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Ingest deposited files";
  }
});

document.getElementById("adminUpload").addEventListener("change", async function () {
  if (!this.files.length) return;
  const result = document.getElementById("uploadResult");
  const fileCount = this.files.length;
  result.innerHTML = `Uploading ${fileCount} file${fileCount > 1 ? "s" : ""}...`;

  const formData = new FormData();
  for (const file of this.files) {
    formData.append("file", file);
  }

  const jurisdiction = document.getElementById("uploadJurisdiction").value;
  const stance = document.getElementById("uploadStance").value;
  const structure = document.getElementById("uploadStructure").value;
  if (jurisdiction) formData.append("jurisdiction", jurisdiction);
  if (stance) formData.append("deal_stance", stance);
  if (structure) formData.append("deal_structure", structure);

  try {
    const response = await fetch("/api/v2/corpus/upload", { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Upload failed");
    const items = data.results || [];
    const errs = data.errors || [];
    let html = `<strong>${items.length} file${items.length !== 1 ? "s" : ""} ingested</strong>`;
    if (errs.length) html += ` · <span style="color:var(--red)">${errs.length} error${errs.length !== 1 ? "s" : ""}</span>`;
    html += "<ul style='margin:8px 0 0;padding-left:18px'>";
    for (const item of items) {
      const tags = [item.category?.replaceAll("_", " ")];
      if (item.jurisdiction) tags.push(item.jurisdiction);
      if (item.deal_stance) tags.push(item.deal_stance);
      if (item.deal_structure) tags.push(item.deal_structure);
      html += `<li>${escapeHtml(item.title || "?")} · ${item.chunk_count || 0} chunks · ${tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join(" ")}</li>`;
    }
    for (const err of errs) {
      html += `<li style="color:var(--red)">${escapeHtml(err.file)}: ${escapeHtml(err.error)}</li>`;
    }
    html += "</ul>";
    result.innerHTML = html;
    refreshDashboard();
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
  }
  this.value = "";
});

document.getElementById("adminSearch").addEventListener("click", async () => {
  const query = document.getElementById("adminQuery").value || "M&A due diligence escrow ancillary";
  const result = document.getElementById("adminResults");
  result.innerHTML = "Searching...";
  try {
    const data = await getJson(`/api/v2/retrieve?q=${encodeURIComponent(query)}`);
    if (!data.results.length) {
      result.innerHTML = `<p class="muted">No matching chunks. Ingest documents first.</p>`;
      return;
    }
    result.innerHTML = data.results.map((item) => `
      <div style="border-bottom:1px solid var(--line);padding:10px 0">
        <span class="tag">${escapeHtml(item.category.replaceAll("_", " "))}</span>
        <strong> ${escapeHtml(item.title)}</strong> · page ${escapeHtml(item.page)}
        <p class="muted" style="margin:4px 0 0">${escapeHtml(item.text.slice(0, 400))}</p>
      </div>
    `).join("");
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
  }
});

document.getElementById("adminEdgarSearch").addEventListener("click", async () => {
  const btn = document.getElementById("adminEdgarSearch");
  btn.disabled = true;
  btn.textContent = "Searching...";
  const result = document.getElementById("adminEdgarResults");
  result.innerHTML = "Querying SEC EDGAR...";
  try {
    const params = new URLSearchParams({
      q: document.getElementById("adminEdgarQuery").value,
      start_date: document.getElementById("adminEdgarStart").value,
      end_date: document.getElementById("adminEdgarEnd").value,
      max: document.getElementById("adminEdgarMax").value,
    });
    const data = await getJson(`/api/edgar/search?${params}`);
    if (!data.results.length) {
      result.innerHTML = `<p class="muted">No EDGAR filings matched. Try a broader query.</p>`;
      return;
    }
    result.innerHTML = data.results.map((item) => `
      <div style="border-bottom:1px solid var(--line);padding:10px 0">
        <span class="tag">EDGAR ${escapeHtml(item.file_type || "8-K")}</span>
        <strong> ${escapeHtml(item.entity_name)}</strong>
        <p class="muted" style="margin:4px 0 0">Filed: ${escapeHtml(item.file_date)} · ${escapeHtml(item.file_description || "Exhibit")}
          ${item.file_url ? ` · <a href="${escapeHtml(item.file_url)}" target="_blank" rel="noreferrer">View on SEC.gov</a>` : ""}
        </p>
      </div>
    `).join("");
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Search EDGAR";
  }
});

document.getElementById("adminEdgarIngest").addEventListener("click", async () => {
  const btn = document.getElementById("adminEdgarIngest");
  btn.disabled = true;
  btn.textContent = "Ingesting...";
  const result = document.getElementById("adminEdgarResults");
  result.innerHTML = "Searching EDGAR and ingesting filings into corpus...";
  try {
    const data = await getJson("/api/edgar/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: document.getElementById("adminEdgarQuery").value,
        start_date: document.getElementById("adminEdgarStart").value,
        end_date: document.getElementById("adminEdgarEnd").value,
        max_filings: parseInt(document.getElementById("adminEdgarMax").value, 10),
      }),
    });
    const ingested = data.ingested || [];
    const ok = ingested.filter((i) => i.status === "ingested" || i.status === "updated");
    result.innerHTML = `
      <p><strong>${data.filings_found}</strong> filings found · <strong>${ok.length}</strong> ingested</p>
      ${ok.map((i) => `
        <div style="border-bottom:1px solid var(--line);padding:8px 0">
          <span class="tag">${escapeHtml((i.category || "general_ma").replaceAll("_", " "))}</span>
          <strong> ${escapeHtml(i.title || i.entity_name || "Filing")}</strong> · ${i.chunk_count || 0} chunks
        </div>
      `).join("")}
    `;
    refreshDashboard();
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Search and ingest into corpus";
  }
});

async function refreshDatasetStats() {
  try {
    const data = await getJson("/api/datasets/status");
    const maudEl = document.getElementById("maudStats");
    const cuadEl = document.getElementById("cuadStats");
    if (maudEl) {
      const m = data.maud || {};
      maudEl.innerHTML = `
        <p><strong>${m.document_count || 0}</strong> documents · <strong>${m.chunk_count || 0}</strong> chunks in corpus</p>
        ${m.status?.status && m.status.status !== "idle" ? `<p class="muted">Status: ${escapeHtml(m.status.message || m.status.status)}</p>` : ""}
      `;
    }
    if (cuadEl) {
      const c = data.cuad || {};
      cuadEl.innerHTML = `
        <p><strong>${c.document_count || 0}</strong> documents · <strong>${c.chunk_count || 0}</strong> chunks in corpus</p>
        ${c.status?.status && c.status.status !== "idle" ? `<p class="muted">Status: ${escapeHtml(c.status.message || c.status.status)}</p>` : ""}
      `;
    }
  } catch (err) {
    /* silent */
  }
}

let maudPollTimer = null;
let cuadPollTimer = null;

function pollDatasetStatus(dataset, progressEl, btnEl, originalText) {
  const timer = setInterval(async () => {
    try {
      const status = await getJson(`/api/datasets/${dataset}/status`);
      const pct = status.total ? Math.round((status.progress / status.total) * 100) : 0;
      if (status.status === "ingesting" || status.status === "downloading") {
        progressEl.innerHTML = `
          <div class="progress-bar-container">
            <div class="progress-bar" style="width:${pct}%"></div>
          </div>
          <p class="muted">${escapeHtml(status.message || "Processing...")} (${status.progress || 0}/${status.total || "?"})</p>
        `;
      } else if (status.status === "complete") {
        clearInterval(timer);
        progressEl.innerHTML = `<p style="color:var(--accent)"><strong>${escapeHtml(status.message || "Done!")}</strong></p>`;
        btnEl.disabled = false;
        btnEl.textContent = originalText;
        refreshDashboard();
        refreshDatasetStats();
      } else if (status.status === "error") {
        clearInterval(timer);
        progressEl.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(status.message || "Unknown error")}</span>`;
        btnEl.disabled = false;
        btnEl.textContent = originalText;
      }
    } catch (err) {
      /* keep polling */
    }
  }, 2000);
  return timer;
}

document.getElementById("maudIngest").addEventListener("click", async () => {
  const btn = document.getElementById("maudIngest");
  btn.disabled = true;
  btn.textContent = "Starting...";
  const progress = document.getElementById("maudProgress");
  progress.innerHTML = "Initiating MAUD download from HuggingFace...";

  const splitVal = document.getElementById("maudSplit").value;
  const splits = splitVal === "all" ? ["train", "dev", "test"] : [splitVal];

  try {
    await getJson("/api/datasets/maud/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        max_contracts: parseInt(document.getElementById("maudMax").value, 10),
        splits: splits,
      }),
    });
    btn.textContent = "Ingesting...";
    if (maudPollTimer) clearInterval(maudPollTimer);
    maudPollTimer = pollDatasetStatus("maud", progress, btn, "Start MAUD ingestion");
  } catch (err) {
    progress.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
    btn.disabled = false;
    btn.textContent = "Start MAUD ingestion";
  }
});

document.getElementById("cuadIngest").addEventListener("click", async () => {
  const btn = document.getElementById("cuadIngest");
  btn.disabled = true;
  btn.textContent = "Starting...";
  const progress = document.getElementById("cuadProgress");
  progress.innerHTML = "Initiating CUAD download from HuggingFace...";

  try {
    await getJson("/api/datasets/cuad/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        max_contracts: parseInt(document.getElementById("cuadMax").value, 10),
      }),
    });
    btn.textContent = "Ingesting...";
    if (cuadPollTimer) clearInterval(cuadPollTimer);
    cuadPollTimer = pollDatasetStatus("cuad", progress, btn, "Start CUAD ingestion");
  } catch (err) {
    progress.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
    btn.disabled = false;
    btn.textContent = "Start CUAD ingestion";
  }
});

async function loadPipelineInfo() {
  try {
    const data = await getJson("/api/v2/pipeline/status");
    const llm = data.llm || {};
    const vs = data.vector_store || {};
    document.getElementById("statVectors").textContent = vs.vector_count || 0;
    document.getElementById("statLlmMode").textContent = llm.mode === "llm" ? "LLM" : "Deterministic";
    const info = document.getElementById("pipelineInfo");
    if (info) {
      info.innerHTML = `
        <div><strong>Ollama</strong><br><span class="muted">${llm.ollama_available ? "Connected" : "Not available"} (${escapeHtml(llm.ollama_url || "")})</span></div>
        <div><strong>Grader</strong><br><span class="muted">${escapeHtml(llm.grader_model || "n/a")}</span></div>
        <div><strong>Generator</strong><br><span class="muted">${escapeHtml(llm.generator_model || "n/a")}</span></div>
        <div><strong>Embedding</strong><br><span class="muted">${escapeHtml(vs.embedding || "default")}</span></div>
        <div><strong>Vectors</strong><br><span class="muted">${vs.vector_count || 0}</span></div>
        <div><strong>Mode</strong><br><span class="muted">${llm.mode === "llm" ? "LLM active" : "Deterministic fallback"}</span></div>`;
    }
  } catch {
    document.getElementById("statVectors").textContent = "?";
    document.getElementById("statLlmMode").textContent = "?";
  }
}

document.getElementById("adminVectorSync").addEventListener("click", async () => {
  const btn = document.getElementById("adminVectorSync");
  const result = document.getElementById("vectorResult");
  btn.disabled = true;
  btn.textContent = "Syncing...";
  result.innerHTML = "Syncing PostgreSQL chunks to ChromaDB vector index...";
  try {
    const data = await getJson("/api/v2/vectors/sync", { method: "POST" });
    result.innerHTML = `<span style="color:var(--green)">Sync complete: ${data.synced || 0} chunks processed (${data.before || 0} → ${data.after || 0} vectors)</span>`;
    loadPipelineInfo();
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Sync failed: ${escapeHtml(err.message)}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Sync vectors from PostgreSQL";
  }
});

document.getElementById("adminVectorClear").addEventListener("click", async () => {
  if (!confirm("Clear all vectors from ChromaDB? This does not affect PostgreSQL data. You can re-sync afterward.")) return;
  const btn = document.getElementById("adminVectorClear");
  const result = document.getElementById("vectorResult");
  btn.disabled = true;
  try {
    await getJson("/api/v2/vectors/clear", { method: "POST" });
    result.innerHTML = `<span style="color:var(--amber)">Vector index cleared. Use "Sync vectors" to rebuild.</span>`;
    loadPipelineInfo();
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Clear failed: ${escapeHtml(err.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
});

refreshDashboard();
refreshDatasetStats();
loadPipelineInfo();
