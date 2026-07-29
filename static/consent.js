/**
 * Argus shared consent gate — accessible dialog focus management.
 *
 * Owns the first-visit consent modal shared by the Drafting & Review Hub
 * (review.html) and the M&A Research Desk (chat.html). Loaded BEFORE the
 * page script (hub.js / chat.js) so those scripts can read the token and
 * reopen the dialog through `window.argusConsent`.
 *
 * Preserved contracts (do not rename):
 *   - #consentModal / #consentAccept markup
 *   - sessionStorage key `lawagent_consent_token`
 *   - POST /api/consent/accept  ->  { token }
 *   - X-Consent-Token header (sent by the page scripts, not here)
 *
 * Accessibility behavior when consent is required:
 *   - focus starts inside the dialog, on #consentAccept;
 *   - the skip link, masthead, and main content are made `inert` so they
 *     cannot receive focus or pointer interaction while the dialog is open;
 *   - Tab / Shift+Tab wrap within the dialog (belt-and-suspenders with inert);
 *   - after acceptance the background is restored and focus moves to #main;
 *   - reopening (e.g. a submit before acceptance) repeats the same behavior.
 */
(function () {
  'use strict';

  var KEY = 'lawagent_consent_token';
  var modal = document.getElementById('consentModal');
  var acceptBtn = document.getElementById('consentAccept');
  var errorEl = document.getElementById('consentError');

  // Pages without the consent markup get a no-op facade so page scripts can
  // call the same API unconditionally.
  if (!modal || !acceptBtn) {
    window.argusConsent = {
      get token() { return sessionStorage.getItem(KEY) || null; },
      get required() { return !this.token; },
      showModal: function () {},
      invalidate: function () { sessionStorage.removeItem(KEY); },
      errorFromResponse: async function (response, fallbackMessage) {
        var data = null;
        try { data = await response.json(); } catch { data = null; }
        return new Error(
          (data && (data.error || data.message)) ||
          response.statusText || fallbackMessage || 'Request failed'
        );
      },
    };
    return;
  }

  var main = document.getElementById('main');
  var skipLink = document.querySelector('.skip-link');
  var masthead = document.querySelector('.masthead');
  var footer = document.querySelector('.shell-footer');

  // Everything outside the dialog that must be neutralized while it is open.
  var backgroundEls = [skipLink, masthead, main, footer].filter(Boolean);

  var token = sessionStorage.getItem(KEY) || null;
  var trapping = false;

  function setError(message) {
    if (!errorEl) return;
    errorEl.textContent = message || '';
    errorEl.hidden = !message;
  }

  function setBackgroundInert(on) {
    backgroundEls.forEach(function (el) {
      if (on) {
        el.setAttribute('inert', '');
        el.setAttribute('aria-hidden', 'true');
      } else {
        el.removeAttribute('inert');
        el.removeAttribute('aria-hidden');
      }
    });
  }

  function dialogFocusables() {
    var sel = 'a[href], button:not([disabled]), textarea:not([disabled]), ' +
      'input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.prototype.slice.call(modal.querySelectorAll(sel))
      .filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
  }

  function onKeydown(e) {
    if (e.key !== 'Tab') return;
    var f = dialogFocusables();
    if (!f.length) { e.preventDefault(); return; }
    var first = f[0];
    var last = f[f.length - 1];
    // If focus somehow escaped the dialog, pull it back in.
    if (!modal.contains(document.activeElement)) {
      e.preventDefault();
      first.focus();
      return;
    }
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function openModal() {
    modal.style.display = 'flex';
    modal.removeAttribute('hidden');
    setBackgroundInert(true);
    if (!trapping) {
      document.addEventListener('keydown', onKeydown, true);
      trapping = true;
    }
    // Defer so layout/display settles before we move focus.
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(function () { acceptBtn.focus(); });
    } else {
      acceptBtn.focus();
    }
  }

  function closeModal() {
    modal.style.display = 'none';
    setBackgroundInert(false);
    if (trapping) {
      document.removeEventListener('keydown', onKeydown, true);
      trapping = false;
    }
    // Move focus to sensible visible content now that the background is live.
    if (main && typeof main.focus === 'function') {
      main.focus();
    }
  }

  function invalidate(message) {
    token = null;
    sessionStorage.removeItem(KEY);
    document.dispatchEvent(new CustomEvent('argus:consent-invalid'));
    setError(message || 'Your consent expired. Please confirm again to continue.');
    openModal();
  }

  async function errorFromResponse(response, fallbackMessage) {
    var data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    var message = (data && (data.error || data.message)) ||
      response.statusText || fallbackMessage || 'Request failed';
    var error = new Error(message);
    var consentRequired = response.status === 403 && (
      (data && data.code === 'CONSENT_REQUIRED') ||
      message.toLowerCase() === 'consent required'
    );
    if (consentRequired) {
      error.code = 'CONSENT_REQUIRED';
      invalidate('Your consent expired. Please confirm again to continue.');
    }
    return error;
  }

  acceptBtn.addEventListener('click', function () {
    acceptBtn.disabled = true;
    setError('');
    fetch('/api/consent/accept', { method: 'POST' })
      .then(function (r) {
        if (!r.ok) throw new Error('Consent could not be recorded.');
        return r.json();
      })
      .then(function (data) {
        if (!data || !data.token) throw new Error('Consent could not be recorded.');
        token = data.token;
        sessionStorage.setItem(KEY, token);
        acceptBtn.disabled = false;
        document.dispatchEvent(new CustomEvent('argus:consent', { detail: { token: token } }));
        closeModal();
      })
      .catch(function () {
        token = null;
        sessionStorage.removeItem(KEY);
        acceptBtn.disabled = false;
        setError('Consent could not be recorded. Check your connection and try again.');
        acceptBtn.focus();
      });
  });

  window.argusConsent = {
    get token() { return token || sessionStorage.getItem(KEY) || null; },
    get required() { return !this.token; },
    showModal: openModal,
    invalidate: invalidate,
    errorFromResponse: errorFromResponse,
  };

  if (token) {
    modal.style.display = 'none';
  } else {
    openModal();
  }
})();
