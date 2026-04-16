const contractText = document.querySelector("#contractText");
const analyzeBtn = document.querySelector("#analyzeBtn");
const analyzeV2Btn = document.querySelector("#analyzeV2Btn");
const analyzeMode = document.querySelector("#analyzeMode");
const loadSample = document.querySelector("#loadSample");
const clearContract = document.querySelector("#clearContract");
const analysisEmpty = document.querySelector("#analysisEmpty");
const analysisResult = document.querySelector("#analysisResult");
const templateForm = document.querySelector("#templateForm");
const draftOutput = document.querySelector("#draftOutput");
const copyDraft = document.querySelector("#copyDraft");
const sessionUpload = document.querySelector("#sessionUpload");
const sessionStatus = document.querySelector("#sessionStatus");
const sessionDocs = document.querySelector("#sessionDocs");

let sessionId = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2);
let sessionDocuments = [];

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

function updateSessionStatus() {
  if (!sessionDocuments.length) {
    sessionStatus.textContent = "No session documents loaded.";
    sessionDocs.innerHTML = "Upload deal-specific documents to see them listed here. They will be used as context during contract analysis.";
    return;
  }
  sessionStatus.innerHTML = `<strong>${sessionDocuments.length}</strong> document${sessionDocuments.length > 1 ? "s" : ""} loaded for this session.`;
  sessionDocs.innerHTML = sessionDocuments.map((doc) => `
    <div style="border-bottom:1px solid var(--line);padding:8px 0">
      <span class="tag">${escapeHtml(doc.category.replaceAll("_", " "))}</span>
      <strong> ${escapeHtml(doc.filename)}</strong>
      <p class="muted" style="margin:4px 0 0">${doc.chunk_count} chunks extracted Â· ${escapeHtml(doc.document_type)}</p>
    </div>
  `).join("");
}

sessionUpload.addEventListener("change", async () => {
  if (!sessionUpload.files.length) return;
  for (const file of sessionUpload.files) {
    sessionStatus.innerHTML = `Uploading ${escapeHtml(file.name)}...`;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId);
    try {
      const response = await fetch("/api/session/upload", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Upload failed");
      sessionDocuments.push(data);
    } catch (err) {
      sessionStatus.innerHTML = `<span style="color:var(--red)">Error uploading ${escapeHtml(file.name)}: ${escapeHtml(err.message)}</span>`;
      return;
    }
  }
  updateSessionStatus();
  sessionUpload.value = "";
});

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
      <p>${data.summary.crag_pipeline.map(escapeHtml).join(" â†’ ")}</p>
    </div>
    ${sessionDocuments.length ? `<div class="issue"><span class="tag present">Session context</span><p>${sessionDocuments.length} deal-specific document${sessionDocuments.length > 1 ? "s" : ""} included in this analysis.</p></div>` : ""}
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
            issue.llm_enhancement
              ? `<div class="llm-enhancement">
                  <span class="tag present">LLM-enhanced</span>
                  ${issue.llm_enhancement.enhanced_analysis ? `<p>${escapeHtml(issue.llm_enhancement.enhanced_analysis)}</p>` : ""}
                  ${issue.llm_enhancement.recommended_language ? `<p><strong>Recommended language:</strong> ${escapeHtml(issue.llm_enhancement.recommended_language)}</p>` : ""}
                  ${issue.llm_enhancement.precedent_basis ? `<p class="muted">${escapeHtml(issue.llm_enhancement.precedent_basis)}</p>` : ""}
                </div>`
              : ""
          }
          ${
            issue.corpus_support
              ? `<p><strong>Corpus support:</strong></p>${issue.corpus_support
                  .map(
                    (support) => `
                    <div class="reference">
                      <span class="tag">${escapeHtml(support.category.replaceAll("_", " "))}</span>
                      <p><strong>${escapeHtml(support.title)}</strong> Â· page ${escapeHtml(support.page)}</p>
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
                <h3>${escapeHtml(item.title)} Â· page ${escapeHtml(item.page)}</h3>
                <p>${escapeHtml(item.text.slice(0, 700))}</p>
                <p><strong>Source:</strong> ${escapeHtml(item.source_system)}</p>
              </article>`
            )
            .join("")}`
        : ""
    }
    ${
      data.llm_analysis && data.llm_analysis.analysis
        ? `<h3>LLM synthesis (Command-R7B)</h3>
           <div class="issue">
             ${data.llm_analysis.risk_level && data.llm_analysis.risk_level !== "unknown" ? `<span class="tag ${data.llm_analysis.risk_level}">${escapeHtml(data.llm_analysis.risk_level)} risk</span>` : ""}
             <p>${escapeHtml(data.llm_analysis.analysis)}</p>
             ${data.llm_analysis.key_findings && data.llm_analysis.key_findings.length ? `<p><strong>Key findings:</strong></p><ul>${data.llm_analysis.key_findings.map(f => `<li>${escapeHtml(f)}</li>`).join("")}</ul>` : ""}
             ${data.llm_analysis.corrective_suggestions && data.llm_analysis.corrective_suggestions.length ? `<p><strong>Corrective suggestions:</strong></p><ul>${data.llm_analysis.corrective_suggestions.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ul>` : ""}
             ${data.llm_analysis.citations && data.llm_analysis.citations.length ? `<p><strong>Citations:</strong></p>${data.llm_analysis.citations.map(c => `<div class="reference"><p><strong>${escapeHtml(c.source || "")}</strong> Page ${escapeHtml(c.page || "")}: ${escapeHtml(c.excerpt || "")}</p></div>`).join("")}` : ""}
           </div>`
        : ""
    }
    ${
      data.architecture
        ? `<h3>V2 architecture</h3><div class="issue">
            <p><strong>Mode:</strong> ${escapeHtml(data.architecture.mode || "deterministic")}</p>
            <p><strong>Runtime preference:</strong> ${escapeHtml(data.architecture.runtime_mode || "auto")}</p>
            <p><strong>Grader:</strong> ${escapeHtml(data.architecture.grader || "n/a")} Â· <strong>Generator:</strong> ${escapeHtml(data.architecture.generator || "n/a")}</p>
            <p><strong>Embedding:</strong> ${escapeHtml(data.architecture.embedding || "default")} Â· <strong>Vectors:</strong> ${data.architecture.vector_count || 0}</p>
            <p><strong>Database:</strong> ${escapeHtml(data.architecture.database || "")}</p>
            ${data.architecture.pipeline ? `<ol>${data.architecture.pipeline.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ol>` : ""}
            <p>${(data.architecture.security || []).map(escapeHtml).join("<br>")}</p>
          </div>`
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
  if (!contractText.value.trim() || contractText.value.trim().length < 30) {
    analysisEmpty.classList.add("hidden");
    analysisResult.classList.remove("hidden");
    analysisResult.innerHTML = `<div class="issue medium"><h3>Contract text required</h3><p>Paste at least a few sentences of contract text, or click "Load sample" to try a demo agreement.</p></div>`;
    return;
  }
  analyzeBtn.disabled = true;
  analyzeV2Btn.disabled = true;
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
    analyzeV2Btn.disabled = false;
    analyzeBtn.textContent = "Run issue spotting";
  }
});

analyzeV2Btn.addEventListener("click", async () => {
  if (!contractText.value.trim() || contractText.value.trim().length < 30) {
    analysisEmpty.classList.add("hidden");
    analysisResult.classList.remove("hidden");
    analysisResult.innerHTML = `<div class="issue medium"><h3>Contract text required</h3><p>Paste at least a few sentences of contract text, or click "Load sample" to try a demo agreement.</p></div>`;
    return;
  }
  analyzeBtn.disabled = true;
  analyzeV2Btn.disabled = true;
  analyzeV2Btn.textContent = "Running V2 CRAG...";
  try {
    const data = await getJson("/api/v2/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contract: contractText.value,
        session_id: sessionId,
        mode: analyzeMode ? analyzeMode.value : "auto",
      }),
    });
    renderAnalysis(data);
  } catch (error) {
    analysisEmpty.classList.add("hidden");
    analysisResult.classList.remove("hidden");
    analysisResult.innerHTML = `<div class="issue high"><h3>Unable to analyze with V2</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    analyzeBtn.disabled = false;
    analyzeV2Btn.disabled = false;
    analyzeV2Btn.textContent = "Run V2 database CRAG";
  }
});

async function buildTemplateForm() {
  const data = await getJson("/api/template/questions");
  templateForm.innerHTML = `
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <button type="button" id="autofillBtn" class="secondary dark" style="flex:1;min-width:180px">Pre-fill from session context</button>
      <span id="autofillStatus" class="muted" style="font-size:13px"></span>
    </div>` +
    data.questions
      .map(
        (question) => `
      <label>
        ${escapeHtml(question.label)}
        <input name="${escapeHtml(question.name)}" placeholder="${escapeHtml(question.placeholder)}">
      </label>`
      )
      .join("");
  templateForm.insertAdjacentHTML("beforeend", `<button class="primary wide" type="submit">Generate agreement draft</button>`);

  const autofillBtn = document.querySelector("#autofillBtn");
  const autofillStatus = document.querySelector("#autofillStatus");

  autofillBtn.addEventListener("click", async () => {
    if (!sessionDocuments.length) {
      autofillStatus.innerHTML = `<span style="color:var(--amber)">Upload session documents first (Deal context panel above).</span>`;
      return;
    }
    autofillBtn.disabled = true;
    autofillBtn.textContent = "Extracting deal details...";
    autofillStatus.textContent = "";
    try {
      const result = await getJson("/api/session/extract-details", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const details = result.details || {};
      const count = result.fields_found || 0;
      if (count === 0) {
        autofillStatus.innerHTML = `<span style="color:var(--amber)">No deal details could be extracted from the uploaded documents. Fill manually.</span>`;
        return;
      }
      for (const [key, value] of Object.entries(details)) {
        const input = templateForm.querySelector(`input[name="${key}"]`);
        if (input && value) {
          input.value = value;
          input.style.borderColor = "var(--accent)";
          setTimeout(() => { input.style.borderColor = ""; }, 2000);
        }
      }
      autofillStatus.innerHTML = `<span style="color:var(--green)">${count} field${count !== 1 ? "s" : ""} extracted from session context.</span>`;
    } catch (err) {
      autofillStatus.innerHTML = `<span style="color:var(--red)">Extraction failed: ${escapeHtml(err.message)}</span>`;
    } finally {
      autofillBtn.disabled = false;
      autofillBtn.textContent = "Pre-fill from session context";
    }
  });
}

templateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(templateForm);
  const details = Object.fromEntries(formData.entries());
  draftOutput.textContent = "Generating draft...";
  const endpoint = sessionDocuments.length ? "/api/v2/template/generate" : "/api/template/generate";
  const payload = { details, session_id: sessionId };
  if (endpoint === "/api/v2/template/generate" && analyzeMode) {
    payload.mode = analyzeMode.value;
  }
  const data = await getJson(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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

buildTemplateForm();

async function loadPipelineStatus() {
  const el = document.getElementById("pipelineStatus");
  if (!el) return;
  try {
    const data = await getJson("/api/v2/pipeline/status");
    const llm = data.llm || {};
    const vs = data.vector_store || {};
    const runtimeMode = data.runtime_mode || "auto";
    const mode = llm.mode === "llm"
      ? `<span class="tag present">LLM active</span>`
      : `<span class="tag">Deterministic fallback</span>`;
    el.innerHTML = `
      <div class="pipeline-meta">
        ${mode}
        <span class="tag">${escapeHtml(runtimeMode)} mode</span>
        <span class="muted">${vs.vector_count || 0} vectors indexed</span>
        <span class="muted">${vs.embedding || "default"}</span>
      </div>`;
  } catch {
    el.innerHTML = `<div class="pipeline-meta"><span class="tag">Status unavailable</span></div>`;
  }
}

loadPipelineStatus();

