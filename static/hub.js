/**
 * LawAgent Drafting & Review Hub — frontend JS
 *
 * Handles:
 *   - Mode tab switching (generate / revise / review)
 *   - Consent gate (HMAC token from POST /api/consent/accept)
 *   - Form submission → POST /api/v2/hub/{mode} → poll status
 *   - Editing Hub rendering (doc viewer + issues/missing panels)
 *   - Per-change accept / reject / edit / dismiss via PATCH
 *   - Anchored chat (POST /api/v2/hub/{id}/ask → SSE stream)
 *   - Save & download (POST /api/v2/hub/{id}/bake → enable download buttons)
 *   - Session delete (DELETE /api/v2/hub/{id})
 */

(() => {
  'use strict';

  // ── State ────────────────────────────────────────────────────────────────
  let currentMode = 'generate';
  let currentSessionId = null;
  let currentChanges = [];
  // Consent is owned by the shared gate in consent.js (loaded first); mirror
  // its token locally so the X-Consent-Token headers below stay unchanged.
  let consentToken = (window.argusConsent && window.argusConsent.token) || null;
  document.addEventListener('argus:consent', e => { consentToken = e.detail.token; });
  let pollInterval = null;

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const $ = id => document.getElementById(id);
  const hubForm        = $('hubForm');
  const modeTabs       = document.querySelectorAll('.mode-tab');
  const promptSection  = $('promptSection');
  const uploadSection  = $('uploadSection');
  const uploadLabelText = $('uploadLabelText');
  const promptText     = $('promptText');
  const promptLabel    = $('promptLabel');
  const promptHint     = $('promptHint');
  const promptCounter  = $('promptCounter');
  const intakeError    = $('intakeError');
  const modeSteps      = $('modeSteps');
  const modeNote       = $('modeNote');
  const submitBtn      = $('submitBtn');
  const submitLabel    = $('submitLabel');
  const submitSpinner  = $('submitSpinner');
  const fileInput      = $('fileInput');
  const dropZone       = $('dropZone');
  const fileStatus     = $('fileStatus');
  const contextInput   = $('contextInput');
  const contextDropZone = $('contextDropZone');
  const contextFileList = $('contextFileList');
  const editingHub     = $('editingHub');
  const hubModeLabel   = $('hubModeLabel');
  const hubPostureLabel = $('hubPostureLabel');
  const docViewer      = $('docViewer');
  const issuesList     = $('issuesList');
  const missingList    = $('missingList');
  const issuesBadge    = $('issuesBadge');
  const missingBadge   = $('missingBadge');
  const askQuestion    = $('askQuestion');
  const anchorInput    = $('anchorInput');
  const askSubmit      = $('askSubmit');
  const askAnswer      = $('askAnswer');
  const acceptAllBtn   = $('acceptAllBtn');
  const rejectAllBtn   = $('rejectAllBtn');
  const saveBakeBtn    = $('saveBakeBtn');
  const dlRedline      = $('dlRedline');
  const dlClean        = $('dlClean');
  const dlMemo         = $('dlMemo');
  const dlRegister     = $('dlRegister');
  const deleteSession  = $('deleteSession');
  const SUPPORTED_DOCUMENT_EXTENSIONS = ['.pdf', '.docx'];

  // ── Mode tab switching ────────────────────────────────────────────────────

  // Mode truth — copy and behavior for each intake mode. Kept honest to the
  // pipeline: Generate skips anonymization/retrieval; Revise/Review are
  // document-backed and attempt (best-effort) anonymization; Review does not
  // auto-rewrite. See docs/UI_RENOVATION.md "Functional truth before polish".
  const MODE_CONFIG = {
    generate: {
      submit: 'Generate first draft',
      promptLabel: 'What contract should I draft?',
      promptPlaceholder: 'e.g. Draft a buy-side mutual NDA for a $25M software acquisition with 18-month indemnification and 20% cap.',
      promptHint: 'Key terms, dollar amounts, and deal structure. Use public or fictional details only.',
      steps: [
        'Your prompt is sent straight to the drafting model — no document anonymization or research-library retrieval runs.',
        'A first draft opens in the editing workspace.',
        'You review spotted issues and suggested provisions, then export.',
      ],
      note: 'Because Generate skips retrieval and anonymization, do not include confidential or identifying details in the prompt. Optional context is held for later clause research, not this initial draft.',
    },
    revise: {
      submit: 'Revise and open workspace',
      uploadLabel: 'Upload your draft',
      promptLabel: 'Revision instructions',
      promptPlaceholder: 'e.g. Make confidentiality mutual; tighten indemnification to 20%/$50K/18mo; add a Delaware forum-selection clause.',
      promptHint: 'What changes should I make? e.g. "Make confidentiality mutual; tighten indemnification to 20%/$50K/18mo."',
      steps: [
        'Argus attempts to remove identifying details, then retrieves relevant playbook and library passages.',
        'Your draft opens in the workspace with proposed redlines and suggested provisions.',
        'Accept, reject, or edit each change, then export.',
      ],
      note: 'Anonymization is best effort and may pass the original text through, so use public or fictional material only.',
    },
    review: {
      submit: 'Review agreement',
      uploadLabel: 'Upload the agreement to review',
      steps: [
        'Argus attempts to remove identifying details, then retrieves relevant passages.',
        'The agreement opens in the workspace with spotted issues and suggested missing provisions — Review does not rewrite the document for you.',
        'Work through each finding, then export a memo and change register.',
      ],
      note: 'Anonymization is best effort and may pass the original text through, so use public or fictional material only.',
    },
  };

  function switchMode(mode) {
    currentMode = mode;
    clearIntakeError();
    const cfg = MODE_CONFIG[mode] || MODE_CONFIG.generate;

    modeTabs.forEach(t => {
      const active = t.dataset.mode === mode;
      t.classList.toggle('active', active);
      t.setAttribute('aria-selected', active ? 'true' : 'false');
      t.tabIndex = active ? 0 : -1;   // roving tabindex
    });

    const needsPrompt  = mode === 'generate' || mode === 'revise';
    const needsUpload  = mode === 'revise'   || mode === 'review';
    promptSection.style.display = needsPrompt ? '' : 'none';
    uploadSection.style.display = needsUpload ? '' : 'none';

    if (needsPrompt && cfg.promptLabel) promptLabel.textContent = cfg.promptLabel;
    if (needsPrompt && cfg.promptHint)  promptHint.textContent  = cfg.promptHint;
    if (needsPrompt && cfg.promptPlaceholder && promptText) promptText.placeholder = cfg.promptPlaceholder;
    if (needsUpload && cfg.uploadLabel && uploadLabelText) uploadLabelText.textContent = cfg.uploadLabel;
    submitLabel.textContent = cfg.submit;

    renderModeSteps(cfg);
  }

  function renderModeSteps(cfg) {
    if (modeSteps) {
      modeSteps.innerHTML = '';
      (cfg.steps || []).forEach(text => {
        const li = document.createElement('li');
        li.textContent = text;
        modeSteps.appendChild(li);
      });
    }
    if (modeNote) modeNote.textContent = cfg.note || '';
  }

  // Click + roving keyboard (Arrow/Home/End follow the WAI-ARIA tabs pattern).
  const modeTabList = Array.from(modeTabs);
  modeTabs.forEach((tab, i) => {
    tab.addEventListener('click', () => switchMode(tab.dataset.mode));
    tab.addEventListener('keydown', e => {
      let next = -1;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % modeTabList.length;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + modeTabList.length) % modeTabList.length;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = modeTabList.length - 1;
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); switchMode(tab.dataset.mode); return; }
      else return;
      e.preventDefault();
      const target = modeTabList[next];
      switchMode(target.dataset.mode);
      target.focus();
    });
  });

  // ── Inline intake error surface (accessible, replaces alert() for intake) ──

  function showIntakeError(msg) {
    if (!intakeError) { alert(msg); return; }
    intakeError.textContent = msg;
    intakeError.hidden = false;
  }

  function clearIntakeError() {
    if (intakeError) { intakeError.textContent = ''; intakeError.hidden = true; }
  }

  // ── Char counter ──────────────────────────────────────────────────────────

  if (promptText) {
    promptText.addEventListener('input', () => {
      const len = promptText.value.length;
      promptCounter.textContent = `${len} / 5000`;
      promptCounter.classList.toggle('amber', len >= 4500 && len < 4900);
      promptCounter.classList.toggle('red', len >= 4900);
    });
  }

  // ── File drop zone ────────────────────────────────────────────────────────

  function isSupportedDocument(file) {
    if (!file || !file.name) return false;
    const name = file.name.toLowerCase();
    return SUPPORTED_DOCUMENT_EXTENSIONS.some(ext => name.endsWith(ext));
  }

  function showUnsupportedFile(file) {
    const name = file && file.name ? `"${file.name}"` : 'That file';
    showIntakeError(`${name} is not supported. Upload a PDF or DOCX document.`);
  }

  function setupDropZone(zone, input, statusEl) {
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      if (e.dataTransfer.files[0]) {
        if (!isSupportedDocument(e.dataTransfer.files[0])) {
          showUnsupportedFile(e.dataTransfer.files[0]);
          return;
        }
        const dt = new DataTransfer();
        dt.items.add(e.dataTransfer.files[0]);
        input.files = dt.files;
        input.dispatchEvent(new Event('change'));
      }
    });
    if (statusEl) {
      input.addEventListener('change', () => {
        if (input.files[0] && !isSupportedDocument(input.files[0])) {
          showUnsupportedFile(input.files[0]);
          input.value = '';
        }
        statusEl.textContent = input.files[0] ? input.files[0].name : 'No file selected';
      });
    }
  }

  setupDropZone(dropZone, fileInput, fileStatus);

  // Context multi-file
  contextDropZone.addEventListener('click', () => contextInput.click());
  contextDropZone.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); contextInput.click(); }
  });
  contextDropZone.addEventListener('dragover', e => { e.preventDefault(); contextDropZone.classList.add('drag-over'); });
  contextDropZone.addEventListener('dragleave', () => contextDropZone.classList.remove('drag-over'));
  contextDropZone.addEventListener('drop', e => {
    e.preventDefault();
    contextDropZone.classList.remove('drag-over');
    Array.from(e.dataTransfer.files).forEach(f => addContextFile(f));
  });
  contextInput.addEventListener('change', () => {
    Array.from(contextInput.files).forEach(f => addContextFile(f));
    contextInput.value = '';
  });

  const contextFiles = [];
  function addContextFile(file) {
    if (!isSupportedDocument(file)) {
      showUnsupportedFile(file);
      return;
    }
    contextFiles.push(file);
    const item = document.createElement('div');
    item.className = 'context-file-item';
    const filename = document.createElement('span');
    filename.textContent = file.name;
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'remove-file';
    removeBtn.setAttribute('aria-label', `Remove ${file.name}`);
    removeBtn.textContent = '×';
    item.append(filename, ' ', removeBtn);
    removeBtn.addEventListener('click', () => {
      const idx = contextFiles.indexOf(file);
      if (idx !== -1) contextFiles.splice(idx, 1);
      item.remove();
    });
    contextFileList.appendChild(item);
  }

  // ── Form submission ───────────────────────────────────────────────────────

  hubForm.addEventListener('submit', async e => {
    e.preventDefault();
    clearIntakeError();
    if (!consentToken) { window.argusConsent.showModal(); return; }

    // Review has no prompt control. Do not let text retained from Generate or
    // Revise invisibly influence its retrieval query after a mode switch.
    const prompt = currentMode === 'review'
      ? ''
      : (promptText ? promptText.value.trim() : '');
    const hasFile = !!fileInput.files[0];

    // Generate needs a prompt; Revise needs both a document and instructions;
    // Review needs a document (its prompt is hidden).
    if ((currentMode === 'generate' || currentMode === 'revise') && !prompt) {
      showIntakeError(currentMode === 'generate'
        ? 'Enter a prompt describing the contract to draft.'
        : 'Enter the revision instructions for your draft.');
      promptText.focus();
      return;
    }
    if ((currentMode === 'revise' || currentMode === 'review') && !hasFile) {
      showIntakeError('Upload a PDF or DOCX document to continue.');
      dropZone.focus();
      return;
    }

    submitBtn.disabled = true;
    submitLabel.hidden = true;
    submitSpinner.hidden = false;

    try {
      // Submit first to get a session_id, then upload context (which requires session_id)
      const sessionResult = await submitHub(currentMode, prompt);
      currentSessionId = sessionResult.session_id;

      const contextFailures = [];
      for (const ctxFile of contextFiles) {
        try {
          await uploadContext(ctxFile);
        } catch (err) {
          contextFailures.push(`${ctxFile.name}: ${err.message}`);
        }
      }
      if (contextFailures.length) {
        showIntakeError(
          `The session started, but some context files could not be attached: ${contextFailures.join('; ')}`
        );
      }

      if (sessionResult.status === 'running') {
        startPolling(currentSessionId);
      } else {
        openEditingHub(sessionResult);
      }
    } catch (err) {
      showIntakeError(`Submission error: ${err.message}`);
      submitBtn.disabled = false;
      submitLabel.hidden = false;
      submitSpinner.hidden = true;
    }
  });

  async function uploadContext(file) {
    if (!currentSessionId) return;
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`/api/v2/context/attach?session_id=${encodeURIComponent(currentSessionId)}`, {
      method: 'POST',
      headers: { 'X-Consent-Token': consentToken || '' },
      body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: r.statusText }));
      throw new Error(err.error || r.statusText || 'Context upload failed');
    }
  }

  async function submitHub(mode, prompt) {
    const endpoint = `/api/v2/hub/${mode}`;
    const fd = new FormData();
    fd.append('posture', document.getElementById('posture').value);
    fd.append('doc_type', document.getElementById('docType').value);
    fd.append('governing_law', document.getElementById('governingLaw').value);
    if (mode !== 'review' && prompt) fd.append('prompt', prompt);
    if (fileInput.files[0]) fd.append('file', fileInput.files[0]);

    const r = await fetch(endpoint, {
      method: 'POST',
      headers: { 'X-Consent-Token': consentToken || '' },
      body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: r.statusText }));
      throw new Error(err.error || r.statusText);
    }
    return r.json();
  }

  function startPolling(sessionId) {
    clearInterval(pollInterval);
    let pollCount = 0;
    const MAX_POLLS = 120; // 120 × 2.5s = 5 minutes timeout
    const t0 = Date.now();
    // The server only reports broad running/ready/failed status — not real
    // stage telemetry — so show honest, mode-appropriate elapsed-time text and
    // mark it estimated rather than inventing retrieval/drafting sub-stages.
    const working = currentMode === 'generate' ? 'Drafting your first draft' : 'Analyzing the document';
    const updateProgress = () => {
      const sec = Math.floor((Date.now() - t0) / 1000);
      if (submitLabel) submitLabel.textContent = `${working}… (${sec}s, estimated)`;
    };
    updateProgress();
    if (submitLabel) submitLabel.hidden = false; // show the label alongside the spinner
    pollInterval = setInterval(async () => {
      pollCount++;
      updateProgress();
      if (pollCount > MAX_POLLS) {
        clearInterval(pollInterval);
        showIntakeError('Processing timed out. The server may still be working — refresh to check.');
        submitBtn.disabled = false;
        submitLabel.hidden = false;
        resetSubmitLabel();
        submitSpinner.hidden = true;
        return;
      }
      try {
        const r = await fetch(`/api/v2/hub/${sessionId}/status`);
        if (!r.ok) return;
        const data = await r.json();
        if (data.status === 'ready') {
          clearInterval(pollInterval);
          resetSubmitLabel();
          openEditingHub(data);
        } else if (data.status === 'failed' || data.status === 'error') {
          clearInterval(pollInterval);
          const msg = data.error ? `Processing failed: ${data.error}` : 'Processing failed. Please try again.';
          showIntakeError(msg);
          submitBtn.disabled = false;
          submitLabel.hidden = false;
          resetSubmitLabel();
          submitSpinner.hidden = true;
        }
      } catch { /* retry next tick */ }
    }, 2500);
  }

  // ── Editing Hub ───────────────────────────────────────────────────────────

  function openEditingHub(data) {
    submitBtn.disabled = false;
    submitLabel.hidden = false;
    submitSpinner.hidden = true;

    document.querySelector('.hub-intake').style.display = 'none';
    editingHub.style.display = 'flex';

    hubModeLabel.textContent = data.mode || currentMode;
    hubPostureLabel.textContent = (data.posture || 'neutral').toUpperCase();

    currentChanges = data.changes || [];
    renderDocViewer(data.draft_text || '', currentChanges);
    renderIssuesPanel(currentChanges.filter(c => c.kind === 'redline'));
    renderMissingPanel(currentChanges.filter(c => c.kind === 'missing_clause'));
  }

  function renderDocViewer(text, changes) {
    let html = escapeHtml(text);

    // Highlight spans with accepted/pending changes
    changes.forEach((c, i) => {
      if (c.kind === 'redline' && c.original_text) {
        const escaped = escapeHtml(c.original_text);
        const cls = severityClass(c.severity);
        html = html.replace(
          escaped,
          `<mark class="change-mark ${cls}" data-idx="${i}" title="${escapeAttr(c.clause_anchor)}">${escaped}</mark>`
        );
      }
    });

    docViewer.innerHTML = `<pre class="doc-text">${html}</pre>`;

    // Click mark → scroll to issue card
    docViewer.querySelectorAll('.change-mark').forEach(mark => {
      mark.addEventListener('click', () => {
        const idx = parseInt(mark.dataset.idx, 10);
        const card = document.querySelector(`.change-card[data-idx="${idx}"]`);
        if (card) {
          activateSideTab('issues');
          card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          card.classList.add('highlight-flash');
          setTimeout(() => card.classList.remove('highlight-flash'), 800);
        }
      });
    });
  }

  function renderIssuesPanel(redlines) {
    issuesBadge.textContent = redlines.length || '';
    issuesList.innerHTML = '';
    if (!redlines.length) {
      issuesList.innerHTML = '<p class="muted empty-state">No issues found.</p>';
      return;
    }
    redlines.forEach((c, localIdx) => {
      const globalIdx = currentChanges.indexOf(c);
      issuesList.appendChild(buildChangeCard(c, globalIdx));
    });
  }

  function renderMissingPanel(missing) {
    missingBadge.textContent = missing.length || '';
    missingList.innerHTML = '';
    if (!missing.length) {
      missingList.innerHTML = '<p class="muted empty-state">No missing clauses proposed.</p>';
      return;
    }
    missing.forEach(c => {
      const globalIdx = currentChanges.indexOf(c);
      missingList.appendChild(buildMissingCard(c, globalIdx));
    });
  }

  function buildChangeCard(change, idx) {
    const card = document.createElement('div');
    card.className = `change-card severity-${change.severity || 'med'}`;
    card.dataset.idx = idx;

    card.innerHTML = `
      <div class="card-header">
        <span class="severity-chip ${change.severity}">${(change.severity || 'med').toUpperCase()}</span>
        <span class="card-anchor">${escapeHtml(change.clause_anchor || '')}</span>
        <span class="card-category">${(change.category || '').replace(/_/g, ' ')}</span>
        <span class="action-badge" data-idx="${idx}">${actionLabel(change.current_action)}</span>
      </div>
      <div class="card-why"><strong>Why:</strong> ${escapeHtml(change.rationale || '')}</div>
      ${change.source_ref ? `<div class="card-source muted"><strong>Source:</strong> ${escapeHtml(change.source_ref)}</div>` : ''}
      <div class="card-proposed"><strong>Proposed:</strong> <span class="proposed-text">${escapeHtml(truncate(change.current_text || change.proposed_text || '', 300))}</span></div>
      <div class="card-actions">
        <button class="btn-accept btn-action" data-idx="${idx}">Accept</button>
        <button class="btn-reject btn-action" data-idx="${idx}">Reject</button>
        <button class="btn-edit btn-action" data-idx="${idx}">Edit</button>
        <button class="btn-ask-clause btn-action" data-idx="${idx}" data-anchor="${escapeAttr(change.clause_anchor || '')}">Ask</button>
      </div>
      <div class="edit-area" style="display:none">
        <textarea class="edit-textarea" data-idx="${idx}">${escapeHtml(change.current_text || change.proposed_text || '')}</textarea>
        <button class="btn-save-edit btn-action" data-idx="${idx}">Save edit</button>
      </div>
    `;

    card.querySelector('.btn-accept').addEventListener('click', () => applyAction(idx, 'accept'));
    card.querySelector('.btn-reject').addEventListener('click', () => applyAction(idx, 'reject'));
    card.querySelector('.btn-edit').addEventListener('click', () => toggleEdit(card, idx));
    card.querySelector('.btn-save-edit').addEventListener('click', () => {
      const edited = card.querySelector(`.edit-textarea[data-idx="${idx}"]`).value;
      applyAction(idx, 'edit', edited);
      card.querySelector('.edit-area').style.display = 'none';
    });
    card.querySelector('.btn-ask-clause').addEventListener('click', () => {
      activateSideTab('ask');
      anchorInput.value = change.clause_anchor || '';
      askQuestion.focus();
    });

    return card;
  }

  function buildMissingCard(change, idx) {
    const card = document.createElement('div');
    card.className = 'change-card missing-card';
    card.dataset.idx = idx;

    card.innerHTML = `
      <div class="card-header">
        <span class="severity-chip ${change.severity}">${(change.severity || 'med').toUpperCase()}</span>
        <span class="card-category">${(change.category || '').replace(/_/g, ' ')}</span>
        <span class="action-badge" data-idx="${idx}">${actionLabel(change.current_action)}</span>
      </div>
      <div class="card-why"><strong>Why:</strong> ${escapeHtml(change.rationale || '')}</div>
      <details class="proposed-clause-details">
        <summary>View proposed clause</summary>
        <pre class="proposed-clause-text">${escapeHtml(change.proposed_text || '')}</pre>
      </details>
      <div class="card-actions">
        <button class="btn-insert btn-action" data-idx="${idx}">Insert clause</button>
        <button class="btn-edit-before btn-action" data-idx="${idx}">Edit before inserting</button>
        <button class="btn-dismiss btn-action" data-idx="${idx}">Dismiss</button>
      </div>
      <div class="edit-area" style="display:none">
        <textarea class="edit-textarea" data-idx="${idx}">${escapeHtml(change.proposed_text || '')}</textarea>
        <button class="btn-save-edit btn-action" data-idx="${idx}">Insert edited</button>
      </div>
    `;

    card.querySelector('.btn-insert').addEventListener('click', () => applyAction(idx, 'accept'));
    card.querySelector('.btn-dismiss').addEventListener('click', () => applyAction(idx, 'dismiss'));
    card.querySelector('.btn-edit-before').addEventListener('click', () => toggleEdit(card, idx));
    card.querySelector('.btn-save-edit').addEventListener('click', () => {
      const edited = card.querySelector(`.edit-textarea[data-idx="${idx}"]`).value;
      applyAction(idx, 'edit', edited);
      card.querySelector('.edit-area').style.display = 'none';
    });

    return card;
  }

  function toggleEdit(card, idx) {
    const ea = card.querySelector('.edit-area');
    ea.style.display = ea.style.display === 'none' ? '' : 'none';
  }

  // ── Per-change actions ────────────────────────────────────────────────────

  async function applyAction(idx, action, editedText) {
    if (!currentSessionId) return;
    const change = currentChanges[idx];
    if (!change) return;

    const changeId = change.id || change.change_id;
    if (!changeId) {
      change.current_action = action;
      if (editedText !== undefined) change.current_text = editedText;
      updateActionBadges(idx, action);
      return;
    }

    const body = { action };
    if (editedText !== undefined) body.edited_text = editedText;

    try {
      const r = await fetch(`/api/v2/hub/${currentSessionId}/changes/${changeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Consent-Token': consentToken || '' },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        change.current_action = action;
        if (editedText !== undefined) change.current_text = editedText;
        updateActionBadges(idx, action);
      }
    } catch (err) {
      console.error('Action failed:', err);
    }
  }

  function updateActionBadges(idx, action) {
    const canonical = { accept: 'accepted', reject: 'rejected', edit: 'edited', dismiss: 'dismissed' }[action] || action;
    document.querySelectorAll(`.action-badge[data-idx="${idx}"]`).forEach(b => {
      b.textContent = actionLabel(canonical);
      b.className = `action-badge action-${canonical}`;
    });
  }

  acceptAllBtn.addEventListener('click', async () => {
    for (let i = 0; i < currentChanges.length; i++) {
      if (currentChanges[i].current_action === 'pending') await applyAction(i, 'accept');
    }
  });

  rejectAllBtn.addEventListener('click', async () => {
    for (let i = 0; i < currentChanges.length; i++) {
      if (currentChanges[i].current_action === 'pending') await applyAction(i, 'reject');
    }
  });

  // ── Save & bake ───────────────────────────────────────────────────────────

  saveBakeBtn.addEventListener('click', async () => {
    if (!currentSessionId) return;
    saveBakeBtn.disabled = true;
    saveBakeBtn.textContent = 'Baking…';
    try {
      const r = await fetch(`/api/v2/hub/${currentSessionId}/bake`, {
        method: 'POST',
        headers: { 'X-Consent-Token': consentToken || '' },
      });
      if (r.ok) {
        const data = await r.json();
        enableDownloads(data);
      } else {
        alert('Bake failed. Please try again.');
      }
    } catch (err) {
      alert(`Bake error: ${err.message}`);
    } finally {
      saveBakeBtn.disabled = false;
      saveBakeBtn.textContent = 'Save & download';
    }
  });

  function enableDownloads(bakeData) {
    const map = {
      'redline.docx': dlRedline,
      'clean.docx': dlClean,
      'memo.docx': dlMemo,
      'register.json': dlRegister,
    };
    Object.entries(map).forEach(([name, btn]) => {
      const url = bakeData[name];
      if (url) {
        btn.disabled = false;
        btn.addEventListener('click', () => { window.location = `/api/v2/hub/${currentSessionId}/download/${name}`; });
      }
    });
  }

  // ── Anchored chat ─────────────────────────────────────────────────────────

  askSubmit.addEventListener('click', submitAsk);
  askQuestion.addEventListener('keydown', e => { if (e.key === 'Enter' && e.ctrlKey) submitAsk(); });

  async function submitAsk() {
    if (!currentSessionId || !askQuestion.value.trim()) return;
    askAnswer.innerHTML = '<span class="typing-dots">…</span>';
    askSubmit.disabled = true;

    try {
      const r = await fetch(`/api/v2/hub/${currentSessionId}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Consent-Token': consentToken || '' },
        body: JSON.stringify({
          clause_anchor: anchorInput.value.trim(),
          question: askQuestion.value.trim(),
        }),
      });

      if (!r.ok) { askAnswer.textContent = `Error: ${r.statusText}`; return; }

      const ct = r.headers.get('Content-Type') || '';
      if (ct.includes('text/event-stream')) {
        await streamSSE(r, askAnswer);
      } else {
        const data = await r.json();
        askAnswer.textContent = data.answer || JSON.stringify(data);
      }
    } catch (err) {
      askAnswer.textContent = `Error: ${err.message}`;
    } finally {
      askSubmit.disabled = false;
    }
  }

  async function streamSSE(response, container) {
    container.textContent = '';
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const payload = JSON.parse(line.slice(6));
            if (payload.token) container.textContent += payload.token;
          } catch { container.textContent += line.slice(6); }
        }
      }
    }
  }

  // ── Side tab switching ────────────────────────────────────────────────────

  document.querySelectorAll('.side-tab').forEach(tab => {
    tab.addEventListener('click', () => activateSideTab(tab.dataset.panel));
  });

  function activateSideTab(panelName) {
    document.querySelectorAll('.side-tab').forEach(t => t.classList.toggle('active', t.dataset.panel === panelName));
    document.querySelectorAll('.side-panel').forEach(p => p.classList.toggle('active', p.id === `panel${capitalize(panelName)}`));
  }

  // ── Delete session ────────────────────────────────────────────────────────

  deleteSession.addEventListener('click', async () => {
    if (!currentSessionId) return;
    if (!confirm('Delete this session and all artifacts? This cannot be undone.')) return;
    try {
      await fetch(`/api/v2/hub/${currentSessionId}`, {
        method: 'DELETE',
        headers: { 'X-Consent-Token': consentToken || '' },
      });
    } catch { /* best effort */ }
    window.location.href = '/hub';
  });

  // ── Utilities ─────────────────────────────────────────────────────────────

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(str) {
    return escapeHtml(str || '').replace(/'/g, '&#39;');
  }

  function severityClass(sev) {
    return { high: 'sev-high', med: 'sev-med', low: 'sev-low' }[sev] || 'sev-med';
  }

  function actionLabel(action) {
    return { pending: 'Pending', accept: 'Accepted', accepted: 'Accepted',
             reject: 'Rejected', rejected: 'Rejected', edit: 'Edited', edited: 'Edited',
             dismiss: 'Dismissed', dismissed: 'Dismissed' }[action] || action || 'Pending';
  }

  function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  function truncate(str, n) {
    if (!str) return '';
    return str.length > n ? str.substring(0, n) + '…' : str;
  }

  function resetSubmitLabel() {
    if (!submitLabel) return;
    submitLabel.textContent = (MODE_CONFIG[currentMode] || MODE_CONFIG.generate).submit;
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  switchMode('generate');
})();
