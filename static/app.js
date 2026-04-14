const contractText = document.querySelector("#contractText");
const analyzeBtn = document.querySelector("#analyzeBtn");
const loadSample = document.querySelector("#loadSample");
const clearContract = document.querySelector("#clearContract");
const analysisEmpty = document.querySelector("#analysisEmpty");
const analysisResult = document.querySelector("#analysisResult");
const templateForm = document.querySelector("#templateForm");
const draftOutput = document.querySelector("#draftOutput");
const copyDraft = document.querySelector("#copyDraft");
const sourceCards = document.querySelector("#sourceCards");

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

buildTemplateForm();
renderSources();