"""Curated M&A playbook seed corpus.

Each entry covers one of the 12 hub categories (02c_Editing_Hub.md
§ Issue/category vocabulary) with both buy-side and sell-side market
positions plus a short rationale. The spotter and missing-clause
proposer cite these as `source_ref` so every change in the Hub UI shows
real corpus grounding instead of LLM-only opinion.

Source: synthesized from publicly available M&A practice guides
(Harvey M&A patterns, eBrevia 9-category playbook, ABA M&A Subcommittee
Deal Points Studies — Public Target & Private Target editions, and the
CUAD / MAUD academic datasets cited in Phase 1). All language is
restated in original wording for fair use; no clauses are reproduced
verbatim from any single source agreement.

Add to / refine this file rather than ingesting raw EDGAR for the demo —
a small curated playbook is more useful at retrieval time than a noisy
EDGAR corpus, and it stays well under Cohere Embed v4's free tier.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Each chunk targets one of the 12 categories from 02c_Editing_Hub.md:
#   assignment, indemnification, confidentiality, non_solicit,
#   mac_definition, reps_warranties, governing_law, dispute_resolution,
#   termination, ip_ownership, payment_terms, liability_cap
# ---------------------------------------------------------------------------

PLAYBOOK_CHUNKS: list[dict[str, Any]] = [

    # ── Assignment ──────────────────────────────────────────────────────────
    {
        "title": "Assignment — Buy-side standard (consent + change-of-control trigger)",
        "category": "assignment",
        "posture": "buy",
        "text": (
            "Buy-side market: assignment requires the buyer's prior written consent, "
            "and any direct or indirect change of control of the seller (including a "
            "merger, sale of all or substantially all assets, or transfer of more than "
            "50% of voting equity) is deemed an assignment for this purpose. "
            "Anti-assignment clauses without a change-of-control trigger are a known "
            "gap that lets sellers transfer the contract through a parent-level "
            "transaction without buyer consent. ABA Public Target Deal Points Study "
            "shows ~78% of buy-side agreements include the change-of-control trigger."
        ),
    },
    {
        "title": "Assignment — Sell-side carve-outs (intra-group reorgs)",
        "category": "assignment",
        "posture": "sell",
        "text": (
            "Sell-side push: assignment may be made without consent (a) to a wholly "
            "owned subsidiary or affiliate, (b) in connection with a sale of all or "
            "substantially all of the assigning party's business, and (c) by operation "
            "of law in a merger, provided the assignee assumes all obligations in "
            "writing. Sell-side counsel routinely negotiates these carve-outs to "
            "preserve flexibility for internal restructurings."
        ),
    },

    # ── Indemnification (caps, baskets, survival) ───────────────────────────
    {
        "title": "Indemnification cap — Buy-side market (10–15% of purchase price)",
        "category": "indemnification",
        "posture": "buy",
        "text": (
            "Buy-side market range for general indemnification cap is 10–15% of the "
            "purchase price for breaches of general representations, with a separate "
            "uncapped (or full purchase-price-capped) bucket for fundamental reps "
            "(authority, capitalization, title) and tax. A 1% cap on general reps is "
            "aggressively seller-favorable and outside the median range reported in "
            "the ABA Private Target Deal Points Study (median 10%, mode 10%)."
        ),
    },
    {
        "title": "Indemnification basket — Tipping vs. deductible",
        "category": "indemnification",
        "posture": "neutral",
        "text": (
            "A 'tipping basket' (also called a threshold or first-dollar basket) "
            "means once aggregate losses exceed the threshold, the buyer recovers "
            "from dollar one. A 'deductible basket' means the buyer recovers only "
            "the excess above the threshold. Tipping baskets are seller-unfriendly; "
            "deductible baskets are seller-friendly. ABA Deal Points: ~62% of "
            "private-target deals use deductibles. Typical basket size: 0.5–1% of "
            "purchase price."
        ),
    },
    {
        "title": "Indemnification survival — Standard 12-24 months on general reps",
        "category": "indemnification",
        "posture": "buy",
        "text": (
            "General representations and warranties typically survive 12–24 months "
            "post-closing in private-target transactions; fundamental reps survive "
            "indefinitely or until the applicable statute of limitations. A 12-month "
            "survival on general reps with a 1% cap is at the seller-aggressive end "
            "of the market and warrants buy-side pushback. R&W insurance is used in "
            "~75% of private-target deals over $50M to extend effective survival "
            "without burdening either party."
        ),
    },

    # ── Confidentiality ─────────────────────────────────────────────────────
    {
        "title": "Confidentiality — Standard NDA structure with carve-outs",
        "category": "confidentiality",
        "posture": "neutral",
        "text": (
            "Standard mutual NDA carves out information that (a) is or becomes "
            "publicly available through no fault of the receiving party, (b) was "
            "already in the receiving party's possession on a non-confidential "
            "basis, (c) is independently developed without use of the disclosing "
            "party's confidential information, or (d) is required to be disclosed "
            "by law or court order (with prompt notice to the disclosing party "
            "where lawful). Survival period: typically 2–3 years post-termination."
        ),
    },
    {
        "title": "Confidentiality — Residuals clause (sell-side leverage)",
        "category": "confidentiality",
        "posture": "sell",
        "text": (
            "A residuals clause permits the receiving party's personnel to use "
            "general knowledge, skills, and ideas retained in unaided memory after "
            "exposure to confidential information. Sell-side / receiving-party "
            "counsel pushes for residuals; buy-side / disclosing-party counsel "
            "pushes back because the clause can swallow the rest of the NDA. "
            "Common compromise: residuals limited to 'general non-technical' or "
            "'concepts and ideas, not specific implementations.'"
        ),
    },

    # ── Non-solicit / Non-compete ───────────────────────────────────────────
    {
        "title": "Non-solicit — Reasonable scope (12–24 months, employees/customers)",
        "category": "non_solicit",
        "posture": "buy",
        "text": (
            "Reasonable non-solicit covers (a) employees the seller's personnel "
            "had material contact with during the look-back period, and (b) "
            "customers and prospects with whom the seller had a business "
            "relationship in the 12 months before closing. Duration: 12–24 months "
            "post-closing for general non-solicit; up to 36 months on key "
            "executives only. Non-solicit is materially more enforceable than "
            "non-compete in most U.S. jurisdictions, especially post-FTC 2024 "
            "non-compete rule."
        ),
    },
    {
        "title": "Non-compete — Geographic scope and FTC scrutiny",
        "category": "non_solicit",
        "posture": "neutral",
        "text": (
            "Non-compete enforceability depends on jurisdiction (California, "
            "Minnesota, North Dakota, Oklahoma generally void; most others "
            "enforce reasonable scope). Geographic scope must match the seller's "
            "actual operating footprint — 'worldwide' on a regional business is "
            "facially overbroad. The FTC's 2024 non-compete rule (currently "
            "subject to ongoing federal litigation) carved out the M&A context "
            "for sellers but not employees. Confirm current enforceability before "
            "drafting wide-scope clauses."
        ),
    },

    # ── MAC definition ──────────────────────────────────────────────────────
    {
        "title": "Material Adverse Effect — Carve-outs (standard buy/sell ask)",
        "category": "mac_definition",
        "posture": "neutral",
        "text": (
            "Standard MAC carve-outs exclude effects from: (a) general economic "
            "or industry-wide conditions, (b) changes in law or accounting "
            "standards, (c) acts of war, terrorism, or natural disasters, (d) "
            "the announcement or pendency of the transaction, (e) actions taken "
            "at the buyer's written request or required by the agreement. Sell-"
            "side adds: (f) failure to meet projections (effects, not the failure "
            "itself, may still qualify). ABA Deal Points: 95%+ of definitions "
            "include carve-outs (a)–(e); ~85% include (f)."
        ),
    },
    {
        "title": "MAC — Disproportionate-impact qualifier (buy-side leverage)",
        "category": "mac_definition",
        "posture": "buy",
        "text": (
            "Buy-side counsel adds a 'disproportionate impact' clawback to most "
            "carve-outs: industry-wide effects are excluded from the MAC "
            "definition only to the extent they do not disproportionately affect "
            "the target compared to other industry participants. This protects "
            "the buyer from a target that's failing because of industry-wide "
            "headwinds in a particularly bad way. Standard market in 70%+ of "
            "private-target deals."
        ),
    },

    # ── Reps & Warranties ───────────────────────────────────────────────────
    {
        "title": "R&W — Bring-down structure (buy-side standard)",
        "category": "reps_warranties",
        "posture": "buy",
        "text": (
            "Buy-side market: representations and warranties bring down at "
            "closing under one of two standards. (1) 'No MAC' bring-down — "
            "general reps must be true and correct except for failures that, "
            "individually or in aggregate, would not constitute a MAC. (2) "
            "'In all material respects' bring-down — general reps must be true "
            "in all material respects. Fundamental reps always bring down at a "
            "'true and correct in all respects' standard with no materiality or "
            "MAC qualifier."
        ),
    },
    {
        "title": "R&W — Sandbagging provision (buy-side ask)",
        "category": "reps_warranties",
        "posture": "buy",
        "text": (
            "Pro-sandbagging clause: 'Buyer's right to indemnification shall not "
            "be affected by Buyer's knowledge, regardless of when acquired.' "
            "Anti-sandbagging clause: 'Buyer is not entitled to indemnification "
            "for any breach of which Buyer had actual knowledge prior to "
            "closing.' Silence is the most common — courts in most jurisdictions "
            "default to permitting sandbagging if the contract is silent (per "
            "ABA Deal Points). Buy-side push: explicit pro-sandbagging clause."
        ),
    },

    # ── Governing law ───────────────────────────────────────────────────────
    {
        "title": "Governing law — Delaware default for U.S. M&A",
        "category": "governing_law",
        "posture": "neutral",
        "text": (
            "Delaware governing law plus exclusive jurisdiction in the Delaware "
            "Court of Chancery (or Delaware Superior Court for non-equity "
            "claims) is the default for U.S. M&A transactions where either "
            "party is Delaware-incorporated. Delaware courts have the deepest "
            "M&A case law (Frontier Oil, Akorn, IBP, Hexion). New York is the "
            "secondary default for purely commercial deals or where neither "
            "entity is Delaware-domiciled. Specifying a non-standard forum is "
            "a buy/sell leverage point."
        ),
    },

    # ── Dispute resolution ──────────────────────────────────────────────────
    {
        "title": "Dispute resolution — Litigation vs arbitration trade-offs",
        "category": "dispute_resolution",
        "posture": "neutral",
        "text": (
            "Litigation in Delaware Chancery is preferred for equity and "
            "specific-performance claims and produces public, citable rulings. "
            "Confidential JAMS or AAA arbitration is preferred when both "
            "parties want privacy, faster resolution, or arbitrators with "
            "specific industry expertise. M&A deals routinely split the two: "
            "litigate equity / specific performance / preliminary injunctive "
            "relief in Delaware Chancery; arbitrate post-closing purchase-price "
            "or earnout disputes via JAMS. Document each carve-out explicitly."
        ),
    },

    # ── Termination ─────────────────────────────────────────────────────────
    {
        "title": "Termination — Outside date and reverse termination fees",
        "category": "termination",
        "posture": "neutral",
        "text": (
            "Standard mutual termination rights: (a) by mutual consent, (b) if "
            "closing has not occurred by the outside date (typically 6–9 months "
            "from signing, extended for regulatory approvals), (c) for material "
            "uncured breach, (d) if a closing condition is incapable of being "
            "satisfied. Reverse termination fees of 3–6% of equity value are "
            "standard where buyer-side regulatory failure is a non-trivial risk. "
            "ABA Deal Points: median outside date is 6 months; median RTF is 4%."
        ),
    },

    # ── IP ownership ────────────────────────────────────────────────────────
    {
        "title": "IP ownership — Work-for-hire + assignment language",
        "category": "ip_ownership",
        "posture": "buy",
        "text": (
            "Buy-side standard for IP-driven targets (software, biotech, media): "
            "all IP created by employees and contractors during employment, "
            "whether on or off the clock and using or not using company "
            "resources, is work-for-hire owned by the company; to the extent "
            "any IP does not vest as work-for-hire, it is hereby assigned to "
            "the company without further consideration. Buyer should diligence "
            "for any 'specially commissioned work' carve-outs that fail under "
            "the Copyright Act's narrow work-for-hire categories for "
            "non-employees."
        ),
    },
    {
        "title": "IP ownership — Open-source carve-outs and OSS compliance reps",
        "category": "ip_ownership",
        "posture": "buy",
        "text": (
            "Buy-side targets with significant software assets must have an "
            "open-source representation: (a) schedule of all OSS used, (b) "
            "no copyleft (GPL, AGPL, LGPL) license has been combined with "
            "the company's proprietary code in a way that would require the "
            "proprietary code to be released, (c) no obligation to disclose "
            "source code triggered. Material breach is a frequent buy-side "
            "indemnification trigger because remediation can require "
            "rewriting or re-licensing the affected code."
        ),
    },

    # ── Payment terms ───────────────────────────────────────────────────────
    {
        "title": "Payment terms — Working capital adjustment mechanics",
        "category": "payment_terms",
        "posture": "neutral",
        "text": (
            "Standard purchase price adjustment mechanic: (1) seller delivers "
            "an estimated closing balance sheet 3–5 business days before "
            "closing; (2) parties true up against a working capital target "
            "(median = trailing 12-month average) at closing; (3) buyer "
            "delivers a final closing balance sheet within 60–90 days post-"
            "closing; (4) disputes resolved by an independent accountant whose "
            "decision is binding. Cash and indebtedness are typically swept at "
            "closing; defined working capital excludes cash, debt, and tax "
            "items."
        ),
    },
    {
        "title": "Payment terms — Earnout structure and disputes",
        "category": "payment_terms",
        "posture": "neutral",
        "text": (
            "Earnouts shift valuation risk by tying part of the purchase price "
            "to post-closing performance metrics (revenue, EBITDA, milestone "
            "achievement). They are the single largest source of post-closing "
            "M&A litigation. Best-practice protections: (a) clear, "
            "objectively measurable metrics, (b) seller right to operate the "
            "business in the ordinary course during the earnout period, (c) "
            "buyer covenant not to take actions whose primary purpose is to "
            "reduce earnout, (d) accelerated payment on change of control. "
            "Median earnout duration: 2 years; median earnout share: 15-30%."
        ),
    },

    # ── Liability cap ───────────────────────────────────────────────────────
    {
        "title": "Liability cap — General cap vs. fundamental rep carve-outs",
        "category": "liability_cap",
        "posture": "buy",
        "text": (
            "Liability caps are typically tiered: (1) general reps capped at "
            "10–15% of purchase price; (2) fundamental reps (authority, "
            "capitalization, title) capped at the full purchase price or "
            "uncapped; (3) tax reps separately capped or uncapped depending on "
            "structure; (4) covenants generally uncapped. Carve-outs from any "
            "cap typically include: fraud, intentional misrepresentation, "
            "willful breach. The 'no double-recovery' principle limits "
            "stacking of multiple caps for the same loss."
        ),
    },
    {
        "title": "Liability cap — Sole and exclusive remedy clause",
        "category": "liability_cap",
        "posture": "sell",
        "text": (
            "Sell-side push: 'except for fraud, the indemnification provisions "
            "of this Article X are the sole and exclusive remedy of the "
            "parties for any breach of this Agreement.' This forecloses "
            "rescission, common-law fraud claims, and equitable remedies "
            "outside the contract's negotiated structure. Buy-side response: "
            "carve out (a) fraud, (b) intentional misrepresentation, (c) "
            "willful breach of covenants, (d) specific performance, (e) "
            "remedies expressly provided elsewhere in the Agreement (e.g., "
            "purchase-price adjustment, escrow). Standard market includes "
            "all five carve-outs."
        ),
    },
]


def get_seed_chunks() -> list[dict[str, Any]]:
    """Return the playbook chunks shaped for PgvectorCorpusStore.add_chunks."""
    out: list[dict[str, Any]] = []
    for entry in PLAYBOOK_CHUNKS:
        out.append({
            "title": entry["title"],
            "category": entry["category"],
            "posture": entry.get("posture", "neutral"),
            "source_system": "playbook_v1",
            "jurisdiction": entry.get("jurisdiction", ""),
            "deal_structure": entry.get("deal_structure", ""),
            "text": entry["text"].strip(),
        })
    return out
