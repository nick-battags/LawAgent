# Argus UI renovation implementation brief

This is the canonical implementation brief for the Argus application in
`nick-battags/LawAgent`. It is written for contributors and future Codex
sessions working from this repository.

The visual concept is a decision prototype. It is not production code and must
not be copied into this repository as a React, Next.js, Vinext, Tailwind 4, or
SPA migration. Argus remains Flask/Jinja, page-specific vanilla JavaScript, and
same-origin APIs.

## Baseline and repository boundaries

The source audit used:

- LawAgent `origin/main` at
  `95d711afb95f4a30476f8a058baafd12f5829b80`;
- `nick-battags/nickvbattaglia-site` `origin/main` at
  `38421c79bace90e50c1a2aea0df886cd13c76a28`;
- the approved visual concept through commit `baeb3f8`.

Authenticated visual reference:
[Argus renovation concept](https://argus-renovation-concept.nickvbattaglia.chatgpt.site).

Fetch the relevant remote and verify these assumptions before beginning a new
stage. Do not work directly on `main`.

Repository ownership is deliberately separate:

| Repository | Owns |
| --- | --- |
| `LawAgent` | Product landing, Hub, Research, Legal & Data Use, Flask routes and APIs, application state, Admin retirement, and product tests |
| `nickvbattaglia-site` | Portfolio homepage, Argus case study, portfolio components, public project narrative, and portfolio metadata |
| Visual concept | Design reference and screenshot evidence only |

## Approved direction

Argus should feel like a professional legal-work product while remaining
candidly presented as a law-student portfolio project.

- Preserve Nick's portfolio statement: “Preparing for the next generation of
  transactional work at the intersection of law, finance, and technology.”
- Describe Nick plainly as a JD/MBA student.
- Describe Argus as an educational portfolio demonstration, not a commercial
  legal platform.
- Make the document, clause, issue, decision, and supporting source the primary
  interface objects.
- Prefer editorial typography, paper-like surfaces, ink, and restrained
  oxblood accents over generic AI/SaaS styling.
- Optimize for 1440×900, 1280×800, 1600×1000, and a compressed 1100×700
  laptop viewport.
- Mobile needs a readable, non-breaking fallback; mobile feature parity is not
  a renovation goal.

Use these product terms consistently:

| Purpose | Approved term |
| --- | --- |
| Public research surface | **M&A Research Desk** |
| Short navigation label | **Research** |
| User-uploaded research material | **Session sources** |
| Always-searched indexed collection | **Argus research library** |
| Evidence attached to an answer | **Supporting sources** |
| Contextual research inside the Hub | **Clause research** |

Do not use “Ask the Corpus” in new visible copy.

## Supported routes and route truth

| Route | Contract |
| --- | --- |
| `/` | Argus product overview with clear Draft & Review and Research entry points |
| `/hub` | Canonical Draft & Review intake and active-session workspace |
| `/review` | Compatibility alias for `/hub`; preserve inbound links |
| `/research` | Preferred public URL for the M&A Research Desk |
| `/chat` | Compatibility URL rendering the same Research surface; do not remove or redirect-break it |
| `/legal` | Planned Legal & Data Use surface; do not publish links until the route exists |
| `/admin*` | Environment-only maintenance surface, excluded from the public renovation |

`templates/index.html` and `static/app.js` are dormant legacy assets, not the
current landing page. Explicitly retire or restore and test them; never
half-restyle or accidentally revive them.

### Admin behavior

Admin is abandoned as a public product surface, but its maintenance scaffolding
has not yet been fully deleted.

The audited `origin/main` still defined `/admin`, `/admin/login`, and
`/admin/logout`. With `ADMIN_PIN` unset, `/admin` redirected to the login route
and the login route redirected back, producing a loop. Commit `4407a52`
documented the intent to abandon the in-app console while retaining the PIN
gate and other scaffolding for later cleanup.

The renovation contract is:

- when `ADMIN_PIN` is absent, every Admin page and Admin-only API returns a
  deliberate empty `404`, even if a stale session contains
  `admin_authed=True`;
- when `ADMIN_PIN` is configured, the existing PIN login/logout behavior
  remains available and unauthenticated Admin APIs return JSON `401`;
- Admin is not linked from public navigation and receives no visual redesign;
- production observability remains in the Cloud Run, Neon, Vertex, Cohere,
  Supermemory, and Cloudflare provider dashboards;
- complete deletion of the retained routes, templates, styles, JavaScript, and
  APIs requires a separately reviewable dependency and operator-use audit.

The tracked launcher no longer supplies fixed `ADMIN_PIN` or
`FLASK_SECRET_KEY` values. Local operators must provide unique values through
the process environment when those features are needed. Rotate either value
anywhere a previously tracked launcher value was reused; this PR does not
rewrite Git history.

The “Backend Management” link found during the audit is in dormant
`templates/index.html`; `/` renders `templates/landing.html`. Do not describe
that dormant link as part of the active public landing page.

## Process contracts to preserve

Do not rename or remove these contracts while changing markup:

- consent: `POST /api/consent/accept` and `X-Consent-Token`;
- Hub modes: `POST /api/v2/hub/generate`, `/revise`, and `/review`;
- Hub status values: `running`, `ready`, `failed`, and `error`;
- finding actions: `accept`, `reject`, `edit`, and `dismiss`;
- streamed Research events: `token`, `citations`, and `done`;
- Research session key: `sessionStorage.lawagent_chat_session_id`;
- exact artifact keys: `redline.docx`, `clean.docx`, `memo.docx`, and
  `register.json`;
- current IDs, form names, endpoint paths, `data-*` hooks, dynamic classes,
  `.active`, inline visibility behavior, and native `[hidden]` semantics until
  browser contract coverage permits migration.

## Functional truth before polish

Visual copy must not promise behavior the application does not support.

1. Generate without a document intentionally skips document anonymization and
   research-library retrieval.
2. Optional Hub context currently arrives after the background job begins; call
   it material for later Clause research until it is wired into the initial
   run.
3. Do not claim selected-clause grounding until clause text and category are
   sent to the Clause research endpoint.
4. Label progress stages as estimated until the server emits real stage
   telemetry.
5. Do not add saved matters or resume/history claims while Hub draft and
   artifact state remain partly process-memory-bound.
6. Reconcile TXT picker and extractor support before advertising TXT uploads.
7. Normalize GCS artifact delivery before promising durable later downloads.
8. Replace array-index finding linkage with stable change IDs before findings
   can be sorted, filtered, or regrouped.
9. Reopen consent on `CONSENT_REQUIRED`; never cache a fallback acceptance.
10. Replace silent, console-only, `alert()`, and `confirm()` failures with
    visible pending, success, and error states without changing API schemas.

## Native implementation map

Primary product files:

- `templates/landing.html`
- `templates/review.html`
- `templates/chat.html`
- `static/styles.css`
- `static/landing.css`
- `static/hub.css`
- `static/chat.css`
- `static/hub.js`
- `static/chat.js`

Likely shared additions:

- `templates/base.html`
- `templates/legal.html`
- `static/tokens.css`
- `static/components.css`
- licensed, self-hosted files under `static/fonts/`
- project metadata and Open Graph artwork
- browser and screenshot coverage under `tests/ui/`

Keep page-specific behavior page-specific. A template must not load a script
whose required DOM hooks are absent.

## LawAgent delivery sequence

Each stage uses a fresh branch from the latest `origin/main`, a draft GitHub PR,
and review against `main`.

1. **Accuracy and contract baseline**
   - correct public claims and links;
   - add build identity;
   - add `/research` while preserving `/chat`;
   - make disabled Admin routes deliberately unavailable;
   - capture supported route behavior in tests.
2. **Workflow correctness**
   - repair consent recovery, context timing, clause grounding, file-type
     truth, stable IDs, session durability, downloads, progress truth, and
     visible error states.
3. **Visual foundation**
   - introduce canonical tokens, real font delivery, shared metadata, base
     template primitives, fields, buttons, tabs, focus rings, and cards.
4. **Overview and intake**
   - renovate `/` and the Generate, Revise, and Review intake states without
     breaking Flask or API contracts.
5. **Document-first Hub**
   - implement the matter rail, document canvas, and review inspector;
   - preserve reversible finding decisions and all four artifact names.
6. **Research, Legal, and hardening**
   - renovate the M&A Research Desk;
   - add verified Legal & Data Use content;
   - complete accessibility, visual regression, and confirmed legacy cleanup.

Portfolio foundation, homepage, and case-study work proceeds in a separate
branch and PR in `nickvbattaglia-site`. Never combine changes from the two
repositories in one commit or PR.

## Validation gates

At minimum, each applicable stage must verify:

- supported pages render and deprecated routes do not loop;
- all three Hub modes, validation failures, status polling, finding decisions,
  Clause research, bake, four downloads, and deletion;
- Research source add/list/remove, streamed partial answers, citations, retry,
  expiry, and follow-up;
- keyboard order, visible focus, dialog focus management, contrast, and reduced
  motion;
- zero findings, eight or more findings, long clauses, long filenames, multiple
  sources, interrupted streams, and action failures;
- screenshots at 1440×900, 1280×800, 1600×1000, and 1100×700;
- no horizontal overflow.

Run focused tests for the changed contract first, then the full available suite.
Record any pre-existing failures accurately rather than claiming an interrupted
or partially run suite passed.

## Definition of done

The renovation is complete only when:

- the Argus overview establishes the two real workflows before discussing
  providers or architecture;
- a user can understand and complete Generate, Revise, Review, Research, and
  export paths without ambiguous state;
- the document and its review state remain visually primary;
- claims match current source and runtime behavior;
- `/review` and `/chat` remain compatible;
- `/legal` resolves before it is publicly linked;
- disabled Admin routes never loop or expose a public product surface;
- the relevant automated and laptop-view validation is green.
