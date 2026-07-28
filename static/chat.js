(() => {
  'use strict';

  const $ = id => document.getElementById(id);

  const consentModal    = $('consentModal');
  const consentAccept   = $('consentAccept');
  const sourcesList     = $('sourcesList');
  const sourcesEmptyHint = $('sourcesEmptyHint');
  const addSourceBtn    = $('addSourceBtn');
  const sourceFileInput = $('sourceFileInput');
  const chatThread      = $('chatThread');
  const chatForm        = $('chatForm');
  const chatInput       = $('chatInput');
  const sendBtn         = $('sendBtn');
  const sendLabel       = $('sendLabel');
  const sendSpinner     = $('sendSpinner');

  // ── Consent ───────────────────────────────────────────────────────────────

  let consentToken = sessionStorage.getItem('lawagent_consent_token') || null;

  function showModal() { consentModal.style.display = 'flex'; }
  function hideModal() { consentModal.style.display = 'none'; }

  if (consentToken) {
    hideModal();
  } else {
    showModal();
    consentAccept.addEventListener('click', async () => {
      try {
        const r = await fetch('/api/consent/accept', { method: 'POST' });
        const d = await r.json();
        consentToken = d.token || 'accepted';
      } catch {
        consentToken = 'accepted';
      }
      sessionStorage.setItem('lawagent_consent_token', consentToken);
      hideModal();
    });
  }

  // ── Session ID ────────────────────────────────────────────────────────────
  // Persisted in sessionStorage so a reload keeps the same Supermemory container.

  let sessionId = sessionStorage.getItem('lawagent_chat_session_id');
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('lawagent_chat_session_id', sessionId);
  }

  // ── Sources sidebar ───────────────────────────────────────────────────────

  async function loadSources() {
    try {
      const r = await fetch(`/api/v2/context/list?session_id=${encodeURIComponent(sessionId)}`);
      const d = await r.json();
      renderSources(d.sources || []);
    } catch (err) {
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
          <span class="source-meta">${(s.char_count || 0).toLocaleString()} chars</span>
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
          await fetch(
            `/api/v2/context/${encodeURIComponent(id)}?session_id=${encodeURIComponent(sessionId)}`,
            { method: 'DELETE' }
          );
        } finally {
          await loadSources();
        }
      });
    });
  }

  addSourceBtn.addEventListener('click', () => sourceFileInput.click());

  sourceFileInput.addEventListener('change', async () => {
    const file = sourceFileInput.files[0];
    if (!file) return;
    addSourceBtn.disabled = true;
    addSourceBtn.textContent = 'Uploading…';
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
        const err = await r.json().catch(() => ({ error: r.statusText }));
        alert(`Upload failed: ${err.error || r.statusText}`);
      } else {
        await loadSources();
      }
    } catch (err) {
      alert(`Upload error: ${err.message}`);
    } finally {
      addSourceBtn.disabled = false;
      addSourceBtn.textContent = '+ Add';
      sourceFileInput.value = '';
    }
  });

  loadSources();

  // ── Chat submit ───────────────────────────────────────────────────────────

  chatForm.addEventListener('submit', async e => {
    e.preventDefault();
    if (!consentToken) { showModal(); return; }
    const query = chatInput.value.trim();
    if (!query) return;

    const empty = chatThread.querySelector('.chat-empty');
    if (empty) empty.remove();

    appendUserMessage(query);
    chatInput.value = '';
    setBusy(true);

    try {
      await streamAnswer(query);
    } catch (err) {
      appendError(err.message || String(err));
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
      const err = await r.json().catch(() => ({ error: r.statusText }));
      throw new Error(err.error || r.statusText);
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
    div.className = 'msg assistant';
    div.innerHTML = `<div class="bubble" style="color:#D97084">${escapeHtml(msg)}</div>`;
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
