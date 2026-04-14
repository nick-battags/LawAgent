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

function renderDashboard(data) {
  document.getElementById("statBackend").textContent = data.backend || "--";
  document.getElementById("statDocs").textContent = data.document_count || 0;
  document.getElementById("statChunks").textContent = data.chunk_count || 0;
  document.getElementById("statCategories").textContent = Object.keys(data.categories || {}).length;

  const cats = document.getElementById("categoryBreakdown");
  cats.innerHTML = Object.entries(data.categories || {})
    .map(([name, count]) => `<span class="tag">${escapeHtml(name.replaceAll("_", " "))}: ${count}</span>`)
    .join(" ");

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
        <span class="tag">${escapeHtml(doc.category.replaceAll("_", " "))}</span>
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
          <th>Source</th>
          <th>Chunks</th>
        </tr>
      </thead>
      <tbody>
        ${docs.map((doc) => `
          <tr>
            <td><strong>${escapeHtml(doc.title)}</strong></td>
            <td><span class="tag">${escapeHtml(doc.category.replaceAll("_", " "))}</span></td>
            <td>${escapeHtml(doc.document_type)}</td>
            <td>${escapeHtml(doc.source_system)}</td>
            <td>${doc.chunk_count}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
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
  result.innerHTML = `Uploading ${escapeHtml(this.files[0].name)}...`;
  const formData = new FormData();
  formData.append("file", this.files[0]);
  try {
    const response = await fetch("/api/v2/corpus/upload", { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Upload failed");
    result.innerHTML = `<strong>Ingested:</strong> ${escapeHtml(data.result.title || "")} · ${escapeHtml(data.result.category || "")} · ${data.result.chunk_count || 0} chunks`;
    refreshDashboard();
  } catch (err) {
    result.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
  }
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

refreshDashboard();
