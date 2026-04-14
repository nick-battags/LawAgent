const contractText = document.querySelector("#contractText");
const analyzeBtn = document.querySelector("#analyzeBtn");
const analyzeV2Btn = document.querySelector("#analyzeV2Btn");
const loadSample = document.querySelector("#loadSample");
const clearContract = document.querySelector("#clearContract");
const analysisEmpty = document.querySelector("#analysisEmpty");
const analysisResult = document.querySelector("#analysisResult");
const templateForm = document.querySelector("#templateForm");
const draftOutput = document.querySelector("#draftOutput");
const copyDraft = document.querySelector("#copyDraft");
const sourceCards = document.querySelector("#sourceCards");
const corpusStatus = document.querySelector("#corpusStatus");
const ingestDeposits = document.querySelector("#ingestDeposits");
const refreshCorpus = document.querySelector("#refreshCorpus");
const corpusUpload = document.querySelector("#corpusUpload");
const corpusQuery = document.querySelector("#corpusQuery");
const corpusSearch = document.querySelector("#corpusSearch");
const corpusResults = document.querySelector("#corpusResults");
const edgarQuery = document.querySelector("#edgarQuery");
const edgarStartDate = document.querySelector("#edgarStartDate");
const edgarEndDate = document.querySelector("#edgarEndDate");
const edgarMax = document.querySelector("#edgarMax");
const edgarSearchBtn = document.querySelector("#edgarSearchBtn");
const edgarIngestBtn = document.querySelector("#edgarIngestBtn");
const edgarResults = document.querySelector("#edgarResults");

document.querySelectorAll("[data-scroll]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector(`#${button.dataset.scroll}`).scrollIntoView({ behavior: "smooth" });
  });
});

async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderAnalysis(data) {
  const parties = data.summary.possible_parties.length
    ? data.summary.possible_parties.map(escapeHtml).join(", ")
    : "Not detected";

  analysisResult.innerHTML = `
    <div class="summary-grid">
      <div class="metric"><span>Deal type</span><strong>${escapeHtml(data.summary.deal_type)}</strong></div>
      <div class="metric"><span>Risk</span><strong>${escapeHtml(data.summary.risk_level)}</strong></div>
      <div class="metric"><span>Score</span><strong>${data.summary.risk_score}/100</strong></div>
      <div class="metric"><span>Issues</span><strong>${data.summary.issues_found}</strong></div>
    </div>
    <div class="issue">
      <span class="tag">Detected parties</span>
      <p>${parties}</p>
      <span class="tag">Pipeline</span>
      <p>${data.summary.crag_pipeline.map(escapeHtml).join(" → ")}</p>
    </div>
    <h3>Corrective issue list</h3>
    ${
      data.issues.length
        ? data.issues
            .map(
              (issue) => `
        <article class="issue ${escapeHtml(issue.severity)}">
          <span class="tag">${escapeHtml(issue.severity)}</span>
          <h3>${escapeHtml(issue.title)}</h3>
          <p><strong>Why it matters:</strong> ${escapeHtml(issue.why_it_matters)}</p>
          <p><strong>Corrective action:</strong> ${escapeHtml(issue.corrective_action)}</p>
          <div class="suggested">${escapeHtml(issue.suggested_clause)}</div>
          ${
            issue.corpus_support
              ? `<p><strong>Corpus support:</strong></p>${issue.corpus_support
                  .map(
                    (support) => `
                    <div class="reference">
                      <span class="tag">${escapeHtml(support.category.replaceAll("_", " "))}</span>
                      <p><strong>${escapeHtml(support.title)}</strong> · page ${escapeHtml(support.page)}</p>
                      <p>${escapeHtml(support.excerpt)}</p>
                    </div>`
                  )
                  .join("")}`
              : ""
          }
          <p><a href="${escapeHtml(issue.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(issue.source)}</a></p>
        </article>`
            )
            .join("")
        : `<div class="issue"><h3>No major missing clauses detected</h3><p>Review the clause map and checklist before relying on the draft.</p></div>`
    }
    <h3>Clause map</h3>
    ${data.clause_breakdown
      .map(
        (clause) => `
      <article class="clause">
        <span class="tag ${escapeHtml(clause.status)}">${escapeHtml(clause.status.replaceAll("_", " "))}</span>
        <h3>${escapeHtml(clause.label)}</h3>
        <p>${clause.excerpt ? escapeHtml(clause.excerpt) : "No matching section detected."}</p>
        <p><strong>Reference:</strong> ${escapeHtml(clause.retrieval.drafting_tip)}</p>
      </article>`
      )
      .join("")}
    <h3>Diligence checklist</h3>
    ${data.checklist.map((item) => `<div class="followup">${escapeHtml(item)}</div>`).join("")}
    <h3>Retrieved public-reference guidance</h3>
    ${data.retrieved_authorities
      .map(
        (item) => `
      <article class="reference">
        <span class="tag">${escapeHtml(item.topic.replaceAll("_", " "))}</span>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.text)}</p>
        <p><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source)}</a></p>
      </article>`
      )
      .join("")}
    ${
      data.corpus_results
        ? `<h3>V2 corpus chunks used</h3>${data.corpus_results
            .map(
              (item) => `
              <article class="reference">
                <span class="tag">${escapeHtml(item.category.replaceAll("_", " "))}</span>
                <h3>${escapeHtml(item.title)} · page ${escapeHtml(item.page)}</h3>
                <p>${escapeHtml(item.text.slice(0, 700))}</p>
                <p><strong>Source:</strong> ${escapeHtml(item.source_system)}</p>
              </article>`
            )
            .join("")}`
        : ""
    }
    ${
      data.architecture
        ? `<h3>V2 architecture</h3><div class="issue"><p><strong>Variation:</strong> ${escapeHtml(data.architecture.variation)}</p><p><strong>Database:</strong> ${escapeHtml(data.architecture.database)}</p><p>${data.architecture.security.map(escapeHtml).join("<br>")}</p></div>`
        : ""
    }
    <div class="issue medium"><p>${escapeHtml(data.disclaimer)}</p></div>
  `;
  analysisEmpty.classList.add("hidden");
  analysisResult.classList.remove("hidden");
}

loadSample.addEventListener("click", async () => {
  const data = await getJson("/api/sample-contract");
  contractText.value = data.contract;
});

clearContract.addEventListener("click", () => {
  contractText.value = "";
  analysisResult.classList.add("hidden");
  analysisEmpty.classList.remove("hidden");
});

analyzeBtn.addEventListener("click", async () => {
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Analyzing...";
  try {
    const data = await getJson("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract: contractText.value }),
    });
    renderAnalysis(data);
  } catch (error) {
    analysisEmpty.classList.add("hidden");
    analysisResult.classList.remove("hidden");
    analysisResult.innerHTML = `<div class="issue high"><h3>Unable to analyze</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "Run issue spotting";
  }
});

analyzeV2Btn.addEventListener("click", async () => {
  analyzeV2Btn.disabled = true;
  analyzeV2Btn.textContent = "Running V2 CRAG...";
  try {
    const data = await getJson("/api/v2/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract: contractText.value }),
    });
    renderAnalysis(data);
  } catch (error) {
    analysisEmpty.classList.add("hidden");
    analysisResult.classList.remove("hidden");
    analysisResult.innerHTML = `<div class="issue high"><h3>Unable to analyze with V2</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    analyzeV2Btn.disabled = false;
    analyzeV2Btn.textContent = "Run V2 database CRAG";
  }
});

function renderCorpusStatus(data) {
  const categories = Object.entries(data.categories || {})
    .map(([name, count]) => `<span class="tag">${escapeHtml(name.replaceAll("_", " "))}: ${count}</span>`)
    .join(" ");
  const documents = (data.documents || [])
    .slice(0, 8)
    .map(
      (doc) => `
      <div class="reference">
        <span class="tag">${escapeHtml(doc.category.replaceAll("_", " "))}</span>
        <p><strong>${escapeHtml(doc.title)}</strong></p>
        <p>${escapeHtml(doc.document_type)} · ${doc.chunk_count} chunks · ${escapeHtml(doc.source_system)}</p>
      </div>`
    )
    .join("");
  corpusStatus.innerHTML = `
    <div class="summary-grid">
      <div class="metric"><span>Backend</span><strong>${escapeHtml(data.backend)}</strong></div>
      <div class="metric"><span>Docs</span><strong>${data.document_count}</strong></div>
      <div class="metric"><span>Chunks</span><strong>${data.chunk_count}</strong></div>
      <div class="metric"><span>Categories</span><strong>${Object.keys(data.categories || {}).length}</strong></div>
    </div>
    <p>${categories || "No documents ingested yet."}</p>
    ${documents}
  `;
}

async function refreshCorpusStatus() {
  corpusStatus.textContent = "Loading corpus status...";
  const data = await getJson("/api/v2/corpus/status");
  renderCorpusStatus(data);
}

ingestDeposits.addEventListener("click", async () => {
  ingestDeposits.disabled = true;
  ingestDeposits.textContent = "Ingesting...";
  try {
    const data = await getJson("/api/v2/corpus/ingest-deposits", { method: "POST" });
    renderCorpusStatus(data.status);
    corpusResults.innerHTML = `<div class="issue"><h3>Ingestion complete</h3><p>${data.results.length} deposited files checked. New or updated documents are now available to V2 CRAG.</p></div>`;
  } catch (error) {
    corpusResults.innerHTML = `<div class="issue high"><h3>Ingestion failed</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    ingestDeposits.disabled = false;
    ingestDeposits.textContent = "Ingest deposited files";
  }
});

refreshCorpus.addEventListener("click", refreshCorpusStatus);

corpusUpload.addEventListener("change", async () => {
  if (!corpusUpload.files.length) return;
  const formData = new FormData();
  formData.append("file", corpusUpload.files[0]);
  corpusResults.innerHTML = `<div class="issue"><p>Uploading and ingesting ${escapeHtml(corpusUpload.files[0].name)}...</p></div>`;
  const response = await fetch("/api/v2/corpus/upload", { method: "POST", body: formData });
  const data = await response.json();
  if (!response.ok) {
    corpusResults.innerHTML = `<div class="issue high"><h3>Upload failed</h3><p>${escapeHtml(data.error || "Upload failed")}</p></div>`;
    return;
  }
  renderCorpusStatus(data.status);
  corpusResults.innerHTML = `<div class="issue"><h3>Uploaded and ingested</h3><p>${escapeHtml(data.result.title || data.result.path)} · ${escapeHtml(data.result.category || data.result.status)}</p></div>`;
});

corpusSearch.addEventListener("click", async () => {
  const query = corpusQuery.value || "M&A due diligence escrow ancillary agreement";
  const data = await getJson(`/api/v2/retrieve?q=${encodeURIComponent(query)}`);
  corpusResults.innerHTML = data.results.length
    ? data.results
        .map(
          (item) => `
        <article class="reference">
          <span class="tag">${escapeHtml(item.category.replaceAll("_", " "))}</span>
          <h3>${escapeHtml(item.title)} · page ${escapeHtml(item.page)}</h3>
          <p>${escapeHtml(item.text.slice(0, 650))}</p>
          <p><strong>Matched:</strong> ${item.matched_terms.map(escapeHtml).join(", ")}</p>
        </article>`
        )
        .join("")
    : `<div class="issue medium"><p>No matching corpus chunks yet. Ingest deposited files first.</p></div>`;
});

async function buildTemplateForm() {
  const data = await getJson("/api/template/questions");
  templateForm.innerHTML = data.questions
    .map(
      (question) => `
      <label>
        ${escapeHtml(question.label)}
        <input name="${escapeHtml(question.name)}" placeholder="${escapeHtml(question.placeholder)}">
      </label>`
    )
    .join("");
  templateForm.insertAdjacentHTML("beforeend", `<button class="primary wide" type="submit">Generate agreement draft</button>`);
}

templateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(templateForm);
  const details = Object.fromEntries(formData.entries());
  draftOutput.textContent = "Generating draft...";
  const data = await getJson("/api/template/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ details }),
  });
  const followUps = data.follow_up_questions.map((item) => `- ${item}`).join("\n");
  const references = data.retrieved_authorities
    .map((item) => `- ${item.title}: ${item.source_url}`)
    .join("\n");
  draftOutput.textContent = `${data.agreement}\n\nCORRECTIVE FOLLOW-UP QUESTIONS\n${followUps}\n\nPUBLIC-REFERENCE GUIDANCE\n${references}\n\n${data.disclaimer}`;
});

copyDraft.addEventListener("click", async () => {
  await navigator.clipboard.writeText(draftOutput.textContent);
  copyDraft.textContent = "Copied";
  setTimeout(() => {
    copyDraft.textContent = "Copy draft";
  }, 1200);
});

async function renderSources() {
  const data = await getJson("/api/retrieve?q=merger acquisition indemnification representations closing conditions assignment");
  sourceCards.innerHTML = data.results
    .slice(0, 6)
    .map(
      (item) => `
      <article class="source-card">
        <span class="tag">${escapeHtml(item.topic.replaceAll("_", " "))}</span>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.drafting_tip)}</p>
        <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">Open source reference</a>
      </article>`
    )
    .join("");
}

edgarSearchBtn.addEventListener("click", async () => {
  edgarSearchBtn.disabled = true;
  edgarSearchBtn.textContent = "Searching EDGAR...";
  edgarResults.innerHTML = `<div class="issue"><p>Querying SEC EDGAR full-text search index...</p></div>`;
  try {
    const params = new URLSearchParams({
      q: edgarQuery.value,
      start_date: edgarStartDate.value,
      end_date: edgarEndDate.value,
      max: edgarMax.value,
    });
    const data = await getJson(`/api/edgar/search?${params}`);
    if (!data.results.length) {
      edgarResults.innerHTML = `<div class="issue medium"><p>No EDGAR filings matched your query. Try a broader search term.</p></div>`;
      return;
    }
    edgarResults.innerHTML = data.results
      .map(
        (item) => `
        <article class="reference">
          <span class="tag">EDGAR ${escapeHtml(item.file_type || "8-K")}</span>
          <h3>${escapeHtml(item.entity_name)}</h3>
          <p><strong>Filed:</strong> ${escapeHtml(item.file_date)} · <strong>Description:</strong> ${escapeHtml(item.file_description || "Exhibit")}</p>
          ${item.file_url ? `<p><a href="${escapeHtml(item.file_url)}" target="_blank" rel="noreferrer">View on SEC.gov</a></p>` : ""}
        </article>`
      )
      .join("");
  } catch (error) {
    edgarResults.innerHTML = `<div class="issue high"><h3>EDGAR search failed</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    edgarSearchBtn.disabled = false;
    edgarSearchBtn.textContent = "Search EDGAR";
  }
});

edgarIngestBtn.addEventListener("click", async () => {
  edgarIngestBtn.disabled = true;
  edgarIngestBtn.textContent = "Fetching and ingesting...";
  edgarResults.innerHTML = `<div class="issue"><p>Searching EDGAR, downloading filing text, and ingesting into the corpus database. This may take a moment...</p></div>`;
  try {
    const data = await getJson("/api/edgar/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: edgarQuery.value,
        start_date: edgarStartDate.value,
        end_date: edgarEndDate.value,
        max_filings: parseInt(edgarMax.value, 10),
      }),
    });
    const ingested = data.ingested || [];
    const succeeded = ingested.filter((item) => item.status === "ingested" || item.status === "updated");
    const skipped = ingested.filter((item) => item.status !== "ingested" && item.status !== "updated");
    edgarResults.innerHTML = `
      <div class="issue">
        <h3>EDGAR ingestion complete</h3>
        <p>${data.filings_found} filings found · ${succeeded.length} ingested · ${skipped.length} skipped or unchanged</p>
      </div>
      ${succeeded
        .map(
          (item) => `
          <article class="reference">
            <span class="tag">${escapeHtml((item.category || "general_ma").replaceAll("_", " "))}</span>
            <h3>${escapeHtml(item.title || item.entity_name || "Filing")}</h3>
            <p>${item.chunk_count || 0} chunks · ${escapeHtml(item.source_system || "SEC EDGAR")}</p>
            ${item.edgar_url ? `<p><a href="${escapeHtml(item.edgar_url)}" target="_blank" rel="noreferrer">View on SEC.gov</a></p>` : ""}
          </article>`
        )
        .join("")}
    `;
    if (data.corpus_status) renderCorpusStatus(data.corpus_status);
  } catch (error) {
    edgarResults.innerHTML = `<div class="issue high"><h3>EDGAR ingestion failed</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    edgarIngestBtn.disabled = false;
    edgarIngestBtn.textContent = "Search and ingest into corpus";
  }
});

buildTemplateForm();
renderSources();
refreshCorpusStatus();