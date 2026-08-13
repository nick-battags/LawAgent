(() => {
  'use strict';

  const $ = id => document.getElementById(id);

  const sourcesList     = $('sourcesList');
  const sourcesEmptyHint = $('sourcesEmptyHint');
  const sourcesStatus   = $('sourcesStatus');
  const addSourceBtn    = $('addSourceBtn');
  const sourceFileInput = $('sourceFileInput');
  const chatThread      = $('chatThread');
  const chatForm        = $('chatForm');
  const chatInput       = $('chatInput');
  const sendBtn         = $('sendBtn');
  const sendLabel       = $('sendLabel');
  const sendSpinner     = $('sendSpinner');
  const promptSuggestions = document.querySelectorAll('[data-research-prompt]');

  // ── Consent ───────────────────────────────────────────────────────────────
  // The accessible consent gate lives in consent.js (loaded first); mirror its
  // token so the X-Consent-Token headers below stay unchanged.

  let consentToken = (window.argusConsent && window.argusConsent.token) || null;
  document.addEventListener('argus:consent', e => { consentToken = e.detail.token; });
  document.addEventListener('argus:consent-invalid', () => { consentToken = null; });

  // ── Session ID ────────────────────────────────────────────────────────────
  // Persisted in sessionStorage so a reload keeps the same Session-source scope.

  let sessionId = sessionStorage.getItem('lawagent_chat_session_id');
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('lawagent_chat_session_id', sessionId);
  }

  // ── Sources sidebar ───────────────────────────────────────────────────────

  const SOURCE_POLL_MAX_ATTEMPTS = 15;
  const SOURCE_POLL_INTERVAL_MS = 2000;
  const addSourceDefaultLabel = addSourceBtn.textContent;
  let sourcePollTimer = null;
  let sourcePollAttempts = 0;
  let sourceRefreshGeneration = 0;
  let pageUnloading = false;

  function setSourceStatus(message) {
    sourcesStatus.textContent = message || '';
  }

  function cancelSourcePolling(resetAttempts = true) {
    if (sourcePollTimer !== null) {
      clearTimeout(sourcePollTimer);
      sourcePollTimer = null;
    }
    if (resetAttempts) sourcePollAttempts = 0;
  }

  function scheduleSourcePoll() {
    if (pageUnloading) return;
    if (sourcePollAttempts >= SOURCE_POLL_MAX_ATTEMPTS) {
      cancelSourcePolling(false);
      setSourceStatus('Still processing — try again shortly.');
      return;
    }
    if (sourcePollTimer !== null) clearTimeout(sourcePollTimer);
    sourcePollTimer = setTimeout(async () => {
      sourcePollTimer = null;
      if (pageUnloading) return;
      sourcePollAttempts += 1;
      await loadSources({ polling: true });
    }, SOURCE_POLL_INTERVAL_MS);
  }

  async function loadSources({ polling = false } = {}) {
    const generation = ++sourceRefreshGeneration;
    if (!polling) cancelSourcePolling();
    try {
      const r = await fetch(`/api/v2/context/list?session_id=${encodeURIComponent(sessionId)}`);
      if (!r.ok) {
        throw await window.argusConsent.errorFromResponse(r, 'Session sources unavailable');
      }
      const d = await r.json();
      if (generation !== sourceRefreshGeneration || pageUnloading) return;
      const sources = d.sources || [];
      renderSources(sources);

      const processingCount = sources.filter(s => s.processing_status === 'processing').length;
      const failedCount = sources.filter(s => s.processing_status === 'failed').length;
      if (processingCount > 0) {
        setSourceStatus(
          `${processingCount} Session source${processingCount === 1 ? '' : 's'} processing…`
        );
        scheduleSourcePoll();
      } else {
        cancelSourcePolling();
        if (failedCount > 0) {
          setSourceStatus(
            `${failedCount} Session source${failedCount === 1 ? '' : 's'} failed to process.`
          );
        } else if (sources.length > 0) {
          setSourceStatus('Session sources ready.');
        } else {
          setSourceStatus('');
        }
      }
    } catch (err) {
      if (generation !== sourceRefreshGeneration || pageUnloading) return;
      cancelSourcePolling();
      setSourceStatus('Session sources unavailable — try again shortly.');
      console.warn('Sources list failed:', err);
    }
  }

  function renderSources(sources) {
    if (!sources.length) {
      sourcesEmptyHint.style.display = '';
      sourcesList.innerHTML = '';
      return;
    }
    sourcesEmptyHint.style.display = 'none';
    sourcesList.innerHTML = sources.map(s => `
      <li class="source-item" data-id="${escapeAttr(s.id || '')}">
        <div class="source-info">
          <span class="source-name" title="${escapeAttr(s.filename)}">${escapeHtml(s.filename)}</span>
          <span class="source-meta">${(s.char_count || 0).toLocaleString()} chars · ${sourceStatusLabel(s.processing_status)}</span>
        </div>
        <button class="source-remove" aria-label="Remove ${escapeAttr(s.filename)}" title="Remove">×</button>
      </li>
    `).join('');

    sourcesList.querySelectorAll('.source-remove').forEach(btn => {
      btn.addEventListener('click', async () => {
        const li = btn.closest('.source-item');
        const id = li.dataset.id;
        const name = li.querySelector('.source-name').textContent;
        if (!id) return;
        if (!confirm(`Remove "${name}" from this session?`)) return;
        btn.disabled = true;
        try {
          const r = await fetch(
            `/api/v2/context/${encodeURIComponent(id)}?session_id=${encodeURIComponent(sessionId)}`,
            { method: 'DELETE' }
          );
          if (!r.ok) {
            throw await window.argusConsent.errorFromResponse(r, 'Delete failed');
          }
          setSourceStatus('Session source removed.');
          await loadSources();
        } catch (err) {
          btn.disabled = false;
          setSourceStatus('Session source could not be removed — try again.');
          console.warn('Source delete failed:', err);
        }
      });
    });
  }

  function sourceStatusLabel(status) {
    if (status === 'ready') return 'Ready';
    if (status === 'failed') return 'Failed';
    return 'Processing';
  }

  addSourceBtn.addEventListener('click', () => sourceFileInput.click());

  sourceFileInput.addEventListener('change', async () => {
    const file = sourceFileInput.files[0];
    if (!file) return;
    addSourceBtn.disabled = true;
    addSourceBtn.textContent = 'Uploading…';
    setSourceStatus('Uploading Session source…');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(
        `/api/v2/context/attach?session_id=${encodeURIComponent(sessionId)}`,
        {
          method: 'POST',
          headers: { 'X-Consent-Token': consentToken || '' },
          body: fd,
        }
      );
      if (!r.ok) {
        throw await window.argusConsent.errorFromResponse(r, 'Upload failed');
      }
      const result = await r.json();
      if (result.processing_status === 'ready') {
        setSourceStatus('Session source ready.');
      } else {
        setSourceStatus('Session source accepted and processing…');
      }
      await loadSources();
    } catch (err) {
      if (err.code !== 'CONSENT_REQUIRED') {
        setSourceStatus('Session source upload failed — try again.');
        alert(`Upload error: ${err.message}`);
      }
    } finally {
      addSourceBtn.disabled = false;
      addSourceBtn.textContent = addSourceDefaultLabel;
      sourceFileInput.value = '';
    }
  });

  window.addEventListener('beforeunload', () => {
    pageUnloading = true;
    cancelSourcePolling();
  });

  loadSources();

  promptSuggestions.forEach(button => {
    button.addEventListener('click', () => {
      chatInput.value = button.dataset.researchPrompt || '';
      chatInput.focus();
    });
  });

  // ── Chat submit ───────────────────────────────────────────────────────────

  chatForm.addEventListener('submit', async e => {
    e.preventDefault();
    if (!consentToken) { window.argusConsent.showModal(); return; }
    const query = chatInput.value.trim();
    if (!query) return;

    const empty = chatThread.querySelector('.chat-empty');
    if (empty) empty.remove();

    const pendingMessage = appendUserMessage(query);
    chatInput.value = '';
    setBusy(true);

    try {
      await streamAnswer(query);
    } catch (err) {
      if (err.code === 'CONSENT_REQUIRED') {
        pendingMessage.remove();
        restoreQuery(query);
      } else {
        appendError(err.message || String(err));
      }
    } finally {
      setBusy(false);
      chatInput.focus();
    }
  });

  chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      chatForm.requestSubmit();
    }
  });

  // ── Streaming ─────────────────────────────────────────────────────────────

  async function streamAnswer(query) {
    const r = await fetch('/api/v2/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Consent-Token': consentToken || '',
      },
      body: JSON.stringify({ query, session_id: sessionId }),
    });

    if (!r.ok) {
      throw await window.argusConsent.errorFromResponse(r, 'Research failed');
    }

    const container = appendAssistantContainer();
    const bubble    = container.querySelector('.bubble');
    const citesEl   = container.querySelector('.citations');

    const reader = r.body.getReader();
    const dec    = new TextDecoder();
    let buf      = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let payload;
        try { payload = JSON.parse(line.slice(6)); } catch { continue; }
        if (payload.token !== undefined) {
          bubble.textContent += payload.token;
          scrollBottom();
        }
        if (payload.citations) {
          renderCitations(citesEl, payload.citations);
        }
      }
    }
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────

  function appendUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'msg user';
    div.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
    chatThread.appendChild(div);
    scrollBottom();
    return div;
  }

  function restoreQuery(query) {
    const current = chatInput.value.trim();
    chatInput.value = current ? `${query}\n\n${chatInput.value}` : query;
  }

  function appendAssistantContainer() {
    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = '<div class="bubble"></div><div class="citations"></div>';
    chatThread.appendChild(div);
    scrollBottom();
    return div;
  }

  function appendError(msg) {
    const div = document.createElement('div');
    div.className = 'msg assistant error';
    div.innerHTML = `<div class="bubble">${escapeHtml(msg)}</div>`;
    chatThread.appendChild(div);
    scrollBottom();
  }

  function renderCitations(el, cites) {
    if (!cites || !cites.length) return;
    el.innerHTML = 'Retrieved sources: ' + cites.map((c, i) => {
      const tip = escapeAttr(c.title || (c.text || '').substring(0, 120) || `Source ${i + 1}`);
      const sourceKind = c.category === 'session_context' ? 'Session' : 'Library';
      return `<span class="citation" title="${tip}">[${i + 1}] ${sourceKind}</span>`;
    }).join(' ');
  }

  function setBusy(busy) {
    sendBtn.disabled = busy;
    sendLabel.textContent = busy ? 'Researching…' : 'Research';
    sendSpinner.hidden = !busy;
    chatThread.setAttribute('aria-busy', String(busy));
  }

  function scrollBottom() {
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, '&#39;');
  }
})();
