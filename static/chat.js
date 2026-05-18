(() => {
  'use strict';

  const $ = id => document.getElementById(id);

  const consentModal  = $('consentModal');
  const consentAccept = $('consentAccept');
  const corpusList    = $('corpusList');
  const corpusCount   = $('corpusCount');
  const chatThread    = $('chatThread');
  const chatForm      = $('chatForm');
  const chatInput     = $('chatInput');
  const sendBtn       = $('sendBtn');
  const sendLabel     = $('sendLabel');
  const sendSpinner   = $('sendSpinner');

  let consentToken = sessionStorage.getItem('lawagent_consent_token') || null;

  // ── Consent ───────────────────────────────────────────────────────────────

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

  // ── Corpus sidebar ────────────────────────────────────────────────────────

  async function loadCorpus() {
    try {
      const r = await fetch('/api/v2/corpus/chunks');
      const d = await r.json();
      const chunks = d.chunks || [];
      corpusCount.textContent = `${chunks.length} sources`;
      corpusList.innerHTML = chunks.map((c, i) => `
        <li class="corpus-item" id="corpus-item-${i}">
          <span class="corpus-title">${escapeHtml(c.title || 'Untitled')}</span>
          <span class="corpus-meta">
            <span class="corpus-category">${escapeHtml((c.category || '').replace(/_/g, ' '))}</span>
            ${c.posture ? `<span class="corpus-posture">${escapeHtml(c.posture)}</span>` : ''}
          </span>
        </li>
      `).join('');
    } catch (err) {
      corpusCount.textContent = 'unavailable';
      console.error('Corpus load failed:', err);
    }
  }
  loadCorpus();

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
      body: JSON.stringify({ query }),
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
          highlightCited(payload.citations);
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
    el.innerHTML = 'Sources: ' + cites.map((c, n) => {
      const idx = c.index !== undefined ? c.index : n;
      const title = escapeAttr(c.title || '');
      return `<a href="#corpus-item-${idx}" title="${title}">[${n + 1}]</a>`;
    }).join(' ');
  }

  function highlightCited(cites) {
    document.querySelectorAll('.corpus-item.cited').forEach(el => el.classList.remove('cited'));
    cites.forEach((c, n) => {
      const idx = c.index !== undefined ? c.index : n;
      const el = document.getElementById(`corpus-item-${idx}`);
      if (el) el.classList.add('cited');
    });
  }

  function setBusy(busy) {
    sendBtn.disabled = busy;
    sendLabel.textContent = busy ? 'Asking…' : 'Send';
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
