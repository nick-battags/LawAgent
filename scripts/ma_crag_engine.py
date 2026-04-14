"""Deterministic Corrective RAG engine for M&A legal issue spotting and drafting."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


@dataclass(frozen=True)
class KnowledgeItem:
    topic: str
    title: str
    source: str
    source_url: str
    text: str
    drafting_tip: str
    fallback_clause: str


KNOWLEDGE_BASE = [
    KnowledgeItem(
        topic="deal_structure",
        title="Agreement and Plan of Merger structure",
        source="SEC EDGAR public M&A filings, commonly Exhibit 2.1 to Form 8-K",
        source_url="https://www.sec.gov/edgar/search/",
        text=(
            "M&A agreements typically identify the parties, transaction structure, merger or asset sale mechanics, "
            "closing conditions, purchase price or merger consideration, representations and warranties, covenants, "
            "termination rights, and post-closing remedies. Public SEC-filed merger agreements are useful reference "
            "points for clause organization, but terms must be adapted to the transaction."
        ),
        drafting_tip="Start by confirming transaction form, parties, entity types, consideration, closing deliverables, and governing law.",
        fallback_clause=(
            "The parties intend that, upon the terms and subject to the conditions of this Agreement, Merger Sub "
            "shall merge with and into the Company, with the Company surviving as a wholly owned subsidiary of Parent."
        ),
    ),
    KnowledgeItem(
        topic="indemnification",
        title="Post-closing indemnification",
        source="SEC EDGAR public acquisition agreements and indemnification agreement exhibits",
        source_url="https://www.sec.gov/Archives/edgar/data/79282/000119312514195014/d700826dex101.htm",
        text=(
            "Indemnification provisions allocate post-closing responsibility for losses arising from breaches of "
            "representations, warranties, covenants, taxes, debt, transaction expenses, and excluded liabilities. "
            "Key economic points include survival periods, baskets, caps, escrow or holdback, claim procedures, "
            "exclusive remedy language, fraud carve-outs, and whether fundamental representations have separate limits."
        ),
        drafting_tip="A buyer-favorable draft should specify basket type, cap, survival, escrow source, claim process, and fraud carve-out.",
        fallback_clause=(
            "From and after the Closing, Sellers shall indemnify, defend, and hold harmless Buyer and its Affiliates "
            "from Losses arising out of any breach of Seller representations, warranties, covenants, Excluded "
            "Liabilities, unpaid Indebtedness, Transaction Expenses, or pre-Closing Taxes, subject to the Basket, Cap, "
            "survival periods, and fraud carve-outs set forth herein."
        ),
    ),
    KnowledgeItem(
        topic="representations",
        title="Representations and warranties",
        source="SEC EDGAR merger and stock purchase agreement examples",
        source_url="https://www.sec.gov/Archives/edgar/data/732717/000119312511072458/dex21.htm",
        text=(
            "Seller and company representations usually cover organization, authority, capitalization, financial "
            "statements, undisclosed liabilities, absence of changes, title to assets, material contracts, litigation, "
            "compliance with law, taxes, employees, benefits, intellectual property, data privacy, environmental, "
            "brokers, and related-party transactions. Buyer representations often cover organization, authority, "
            "financing, broker fees, and regulatory approvals."
        ),
        drafting_tip="Flag missing fundamental reps, tax reps, IP/data reps, capitalization, undisclosed liability, and material contract schedules.",
        fallback_clause=(
            "Each Seller represents and warrants that it has full power and authority to execute and perform this "
            "Agreement and that the execution, delivery, and performance of this Agreement will not violate its "
            "organizational documents, applicable law, or any Material Contract."
        ),
    ),
    KnowledgeItem(
        topic="covenants",
        title="Interim operating covenants",
        source="SEC EDGAR agreement and plan of merger examples",
        source_url="https://www.sec.gov/Archives/edgar/data/712515/000114036125036415/ef20056167_ex2-1.htm",
        text=(
            "Between signing and closing, target companies are commonly required to operate in the ordinary course, "
            "preserve business relationships, maintain insurance, avoid issuing equity or debt, avoid extraordinary "
            "transactions, and obtain buyer consent for restricted actions. Public company deals also include "
            "stockholder meeting, no-shop, fiduciary-out, and recommendation covenants."
        ),
        drafting_tip="Confirm ordinary-course restrictions, consent rights, efforts standards, access rights, and public-company fiduciary out mechanics.",
        fallback_clause=(
            "From signing until the earlier of Closing or termination, the Company shall conduct its business in the "
            "ordinary course consistent with past practice and shall not take restricted actions without Buyer consent."
        ),
    ),
    KnowledgeItem(
        topic="closing_conditions",
        title="Closing conditions and deliverables",
        source="SEC EDGAR acquisition agreement examples",
        source_url="https://www.sec.gov/edgar/search/",
        text=(
            "Closing conditions typically include accuracy of representations, covenant performance, absence of legal "
            "restraint, regulatory approvals, required consents, financing or no financing condition, no material "
            "adverse effect, officer certificates, ancillary documents, payoff letters, releases, resignations, and "
            "escrow documents."
        ),
        drafting_tip="Make the conditions measurable and tie third-party consents, payoff letters, and approvals to schedules.",
        fallback_clause=(
            "Buyer shall not be obligated to close unless the Seller representations are true and correct as of Closing, "
            "Seller has performed its covenants in all material respects, required consents have been obtained, and no "
            "Material Adverse Effect has occurred."
        ),
    ),
    KnowledgeItem(
        topic="change_of_control",
        title="Change of control, assignment, and third-party consents",
        source="SEC EDGAR merger agreement and executive/change-of-control disclosures",
        source_url="https://www.sec.gov/edgar/search/",
        text=(
            "M&A diligence should identify contracts that prohibit assignment, require consent on merger, asset sale, "
            "equity transfer, or change of control, or trigger termination, acceleration, exclusivity, most-favored "
            "customer rights, customer notice, or pricing changes. The acquisition agreement should allocate who "
            "obtains consents and what happens if they are not obtained."
        ),
        drafting_tip="Flag silent assignment clauses, anti-assignment language, change-of-control triggers, and required consent deliverables.",
        fallback_clause=(
            "Neither party may assign this Agreement without prior written consent, except Buyer may assign to an "
            "Affiliate or financing source if Buyer remains liable. Required third-party consents listed on Schedule "
            "6.4 shall be obtained before Closing unless waived by Buyer."
        ),
    ),
    KnowledgeItem(
        topic="termination",
        title="Termination, fees, and remedies",
        source="SEC EDGAR public merger agreement examples",
        source_url="https://www.sec.gov/Archives/edgar/data/1131457/000119312513000130/d460221dex21.htm",
        text=(
            "Termination provisions normally cover mutual consent, outside date, injunctions, stockholder approval "
            "failure, uncured breach, failure of conditions, superior proposal, recommendation change, and financing "
            "failure. Public company deals may include termination fees, expense reimbursement, reverse termination "
            "fees, and specific performance."
        ),
        drafting_tip="Check for outside date, cure periods, fee triggers, specific performance, and survival after termination.",
        fallback_clause=(
            "This Agreement may be terminated by mutual written consent, by either party after the Outside Date, by a "
            "non-breaching party following an uncured material breach, or if a final nonappealable order prohibits the "
            "transactions. Sections concerning confidentiality, fees, remedies, and miscellaneous terms shall survive."
        ),
    ),
    KnowledgeItem(
        topic="tax_employment_ip",
        title="Special diligence areas",
        source="SEC EDGAR acquisition agreement examples and common M&A diligence checklists",
        source_url="https://www.sec.gov/edgar/search/",
        text=(
            "M&A legal review should separately assess tax liabilities, employment and benefits matters, 280G parachute "
            "payments, employee classification, non-competes, data privacy, cybersecurity, open-source software, IP "
            "ownership, environmental matters, sanctions, export controls, anti-bribery, and industry-specific approvals."
        ),
        drafting_tip="Add schedules and special indemnities for known liabilities, taxes, IP gaps, privacy incidents, and regulatory issues.",
        fallback_clause=(
            "Without limiting any other remedy, Sellers shall indemnify Buyer for pre-Closing Taxes, employee "
            "misclassification liabilities, unpaid compensation, and scheduled special matters identified in Schedule 9.5."
        ),
    ),
]


CLAUSE_TESTS = [
    {
        "key": "parties_and_recitals",
        "label": "Parties, recitals, and transaction background",
        "patterns": [r"\bby and among\b", r"\bbetween\b", r"\brecitals\b", r"\bwhereas\b"],
        "risk_if_missing": "The agreement may not clearly identify transaction parties or deal background.",
        "topic": "deal_structure",
    },
    {
        "key": "transaction_structure",
        "label": "Transaction structure and closing mechanics",
        "patterns": [r"\bmerger\b", r"\basset purchase\b", r"\bstock purchase\b", r"\bclosing\b", r"\bclosing date\b"],
        "risk_if_missing": "The draft does not clearly specify the transaction form or closing mechanics.",
        "topic": "deal_structure",
    },
    {
        "key": "purchase_price",
        "label": "Purchase price / merger consideration",
        "patterns": [r"\bpurchase price\b", r"\bmerger consideration\b", r"\bconsideration\b", r"\bearnout\b"],
        "risk_if_missing": "Economic terms may be incomplete, including payment timing, adjustments, escrow, or earnout mechanics.",
        "topic": "deal_structure",
    },
    {
        "key": "representations",
        "label": "Representations and warranties",
        "patterns": [r"\brepresentations? and warranties\b", r"\brepresents and warrants\b"],
        "risk_if_missing": "Missing reps can leave key diligence risks unallocated.",
        "topic": "representations",
    },
    {
        "key": "covenants",
        "label": "Pre-closing and post-closing covenants",
        "patterns": [r"\bcovenants\b", r"\bordinary course\b", r"\breasonable best efforts\b", r"\bcommercially reasonable efforts\b"],
        "risk_if_missing": "The seller may not be restricted from changing the business between signing and closing.",
        "topic": "covenants",
    },
    {
        "key": "closing_conditions",
        "label": "Closing conditions",
        "patterns": [r"\bconditions to closing\b", r"\bconditions precedent\b", r"\bno material adverse\b", r"\bconsents\b"],
        "risk_if_missing": "Buyer and seller obligations to close may be unclear.",
        "topic": "closing_conditions",
    },
    {
        "key": "indemnification",
        "label": "Indemnification, basket, cap, survival, escrow",
        "patterns": [r"\bindemnif", r"\bhold harmless\b", r"\bbasket\b", r"\bcap\b", r"\bsurviv"],
        "risk_if_missing": "Post-closing loss allocation may be missing or underdeveloped.",
        "topic": "indemnification",
    },
    {
        "key": "assignment_change_control",
        "label": "Assignment, change of control, and third-party consents",
        "patterns": [r"\bassignment\b", r"\bassign\b", r"\bchange of control\b", r"\bthird[- ]party consent\b"],
        "risk_if_missing": "Anti-assignment or change-of-control consent issues may not be allocated.",
        "topic": "change_of_control",
    },
    {
        "key": "termination",
        "label": "Termination rights, outside date, and remedies",
        "patterns": [r"\btermination\b", r"\bterminate\b", r"\boutside date\b", r"\bspecific performance\b"],
        "risk_if_missing": "The parties may lack clean exit rights, cure periods, or remedy provisions.",
        "topic": "termination",
    },
    {
        "key": "tax_employment_ip",
        "label": "Tax, employment, IP/data, and regulatory risk allocation",
        "patterns": [r"\btax", r"\bemploy", r"\bintellectual property\b", r"\bprivacy\b", r"\bregulatory\b", r"\benvironmental\b"],
        "risk_if_missing": "Special diligence areas may not be separately covered by reps, covenants, schedules, or indemnities.",
        "topic": "tax_employment_ip",
    },
]


TEMPLATE_QUESTIONS = [
    {"name": "transaction_type", "label": "Transaction type", "placeholder": "Reverse triangular merger, stock purchase, asset purchase"},
    {"name": "buyer_name", "label": "Buyer / Parent legal name", "placeholder": "Acquirer Inc."},
    {"name": "seller_name", "label": "Seller / Target legal name", "placeholder": "Target Holdings LLC"},
    {"name": "merger_sub_name", "label": "Merger Sub or acquisition vehicle", "placeholder": "Acquirer Merger Sub Inc."},
    {"name": "target_business", "label": "Target business description", "placeholder": "Cloud contract lifecycle software"},
    {"name": "purchase_price", "label": "Purchase price / consideration", "placeholder": "$25,000,000 cash at closing"},
    {"name": "working_capital", "label": "Working capital or price adjustment", "placeholder": "Dollar-for-dollar adjustment against target NWC of $1,200,000"},
    {"name": "escrow", "label": "Escrow / holdback", "placeholder": "10% of purchase price for 18 months"},
    {"name": "indemnity_cap", "label": "Indemnity cap and basket", "placeholder": "1% deductible basket; 15% general cap; fraud uncapped"},
    {"name": "survival_period", "label": "Survival period", "placeholder": "18 months; fundamental reps survive 6 years"},
    {"name": "closing_conditions", "label": "Key closing conditions", "placeholder": "Customer consents, no MAE, financing, board approvals"},
    {"name": "governing_law", "label": "Governing law", "placeholder": "Delaware"},
    {"name": "special_issues", "label": "Known special issues", "placeholder": "Open-source software review; key customer consent; tax clearance"},
]


SAMPLE_CONTRACT = """AGREEMENT AND PLAN OF MERGER

This Agreement and Plan of Merger is entered into by and among Acquirer Inc., Merger Sub Inc., and Target Software LLC.

RECITALS
WHEREAS, Parent desires to acquire the Company through a reverse triangular merger, with Merger Sub merging with and into the Company.

ARTICLE I - THE MERGER
At Closing, Merger Sub shall merge with and into the Company. The merger consideration shall be $25,000,000 in cash, subject to a working capital adjustment.

ARTICLE III - REPRESENTATIONS AND WARRANTIES
The Company represents and warrants as to organization, authority, financial statements, material contracts, taxes, employees, intellectual property, privacy, and litigation.

ARTICLE V - COVENANTS
From signing until Closing, the Company shall operate in the ordinary course and shall not issue equity, incur debt, terminate material contracts, or make unusual payments without Parent consent.

ARTICLE VI - CONDITIONS TO CLOSING
Closing is conditioned on accuracy of representations, covenant performance, required customer consents, no injunction, and no Material Adverse Effect.

ARTICLE VIII - TERMINATION
The Agreement may be terminated by mutual consent, uncured material breach, injunction, or failure to close by the Outside Date.

MISCELLANEOUS
This Agreement shall be governed by Delaware law.
"""


def tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text.lower()) if token not in STOPWORDS]


def compact(text: str, limit: int = 450) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def retrieve(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    query_terms = Counter(tokenize(query))
    scored = []
    for item in KNOWLEDGE_BASE:
        haystack = f"{item.topic} {item.title} {item.text} {item.drafting_tip}"
        terms = Counter(tokenize(haystack))
        score = sum((terms[token] * weight) for token, weight in query_terms.items())
        if item.topic.replace("_", " ") in query.lower():
            score += 8
        scored.append((score, item))

    ranked = sorted(scored, key=lambda pair: pair[0], reverse=True)
    return [
        {
            "topic": item.topic,
            "title": item.title,
            "source": item.source,
            "source_url": item.source_url,
            "text": item.text,
            "drafting_tip": item.drafting_tip,
            "fallback_clause": item.fallback_clause,
            "score": score,
        }
        for score, item in ranked[:top_k]
        if score > 0 or query.strip()
    ]


def find_excerpt(contract_text: str, patterns: list[str]) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", contract_text) if part.strip()]
    for paragraph in paragraphs:
        if any(re.search(pattern, paragraph, flags=re.IGNORECASE) for pattern in patterns):
            return compact(paragraph)
    for pattern in patterns:
        match = re.search(pattern, contract_text, flags=re.IGNORECASE)
        if match:
            start = max(0, match.start() - 180)
            end = min(len(contract_text), match.end() + 260)
            return compact(contract_text[start:end])
    return ""


def infer_deal_type(contract_text: str) -> str:
    lowered = contract_text.lower()
    if "asset purchase" in lowered:
        return "Asset Purchase"
    if "stock purchase" in lowered or "share purchase" in lowered:
        return "Stock Purchase"
    if "reverse triangular" in lowered:
        return "Reverse Triangular Merger"
    if "merger" in lowered:
        return "Merger"
    return "Unspecified M&A transaction"


def extract_possible_parties(contract_text: str) -> list[str]:
    candidates = []
    patterns = [
        r"by and among\s+(.+?)(?:\.|\n)",
        r"by and between\s+(.+?)(?:\.|\n)",
        r"entered into by\s+(.+?)(?:\.|\n)",
    ]
    for pattern in patterns:
        match = re.search(pattern, contract_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            raw = re.sub(r"\s+", " ", match.group(1))
            pieces = re.split(r",| and | among | between ", raw, flags=re.IGNORECASE)
            candidates.extend(piece.strip(" ,;") for piece in pieces if len(piece.strip()) > 2)
    return candidates[:6]


def analyze_contract(contract_text: str) -> dict[str, Any]:
    text = contract_text.strip()
    if not text:
        raise ValueError("Paste contract text before running issue spotting.")

    clause_breakdown = []
    issues = []
    retrieved_topics = set()
    for test in CLAUSE_TESTS:
        excerpt = find_excerpt(text, test["patterns"])
        present = bool(excerpt)
        status = "present" if present else "missing_or_weak"
        severity = "info" if present else "high"
        authority = retrieve(test["label"], top_k=1)[0]
        retrieved_topics.add(authority["topic"])

        clause_breakdown.append(
            {
                "key": test["key"],
                "label": test["label"],
                "status": status,
                "severity": severity,
                "excerpt": excerpt,
                "retrieval": authority,
            }
        )

        if not present:
            issues.append(
                {
                    "severity": "high",
                    "title": f"Missing or weak: {test['label']}",
                    "why_it_matters": test["risk_if_missing"],
                    "corrective_action": authority["drafting_tip"],
                    "suggested_clause": authority["fallback_clause"],
                    "source": authority["source"],
                    "source_url": authority["source_url"],
                }
            )

    weak_terms = [
        (
            "No fraud carve-out detected",
            r"\bfraud\b",
            "Indemnity caps, baskets, and exclusive remedy clauses usually need an express fraud carve-out.",
            "Add language preserving remedies for fraud, intentional misrepresentation, and willful breach.",
            "indemnification",
        ),
        (
            "No escrow or holdback detected",
            r"\bescrow\b|\bholdback\b",
            "If sellers are thinly capitalized or distributed proceeds immediately, collection risk can undermine indemnity rights.",
            "Consider a funded escrow, holdback, setoff right, or representation and warranty insurance structure.",
            "indemnification",
        ),
        (
            "No disclosure schedule reference detected",
            r"\bdisclosure schedule\b|\bschedules?\b",
            "Reps, exceptions, consents, liabilities, and known issues are usually operationalized through schedules.",
            "Add disclosure schedules for exceptions, consents, capitalization, material contracts, IP, taxes, employees, and litigation.",
            "representations",
        ),
        (
            "No specific performance language detected",
            r"\bspecific performance\b|\binjunctive relief\b",
            "Specific performance provisions can be important if one party refuses to close after conditions are satisfied.",
            "Add equitable remedy language if deal certainty is important.",
            "termination",
        ),
    ]
    for title, pattern, why, action, topic in weak_terms:
        if not re.search(pattern, text, flags=re.IGNORECASE):
            authority = retrieve(topic, top_k=1)[0]
            issues.append(
                {
                    "severity": "medium",
                    "title": title,
                    "why_it_matters": why,
                    "corrective_action": action,
                    "suggested_clause": authority["fallback_clause"],
                    "source": authority["source"],
                    "source_url": authority["source_url"],
                }
            )
            retrieved_topics.add(authority["topic"])

    query = f"{infer_deal_type(text)} legal due diligence contract issue spotting indemnification consents reps covenants closing conditions"
    retrieved_authorities = retrieve(query, top_k=6)
    retrieved_topics.update(item["topic"] for item in retrieved_authorities)

    missing_count = sum(1 for clause in clause_breakdown if clause["status"] != "present")
    risk_score = min(100, 20 + missing_count * 8 + sum(5 for issue in issues if issue["severity"] == "medium"))
    if risk_score < 35:
        risk_level = "Low to moderate"
    elif risk_score < 65:
        risk_level = "Moderate"
    else:
        risk_level = "High"

    checklist = [
        "Confirm exact transaction structure, parties, entity status, authority, and approvals.",
        "Compare reps and warranties against diligence findings and disclosure schedules.",
        "Map third-party consents, anti-assignment clauses, and change-of-control triggers.",
        "Tie known liabilities to purchase price adjustments, special indemnities, or closing conditions.",
        "Review indemnity economics: basket, cap, survival, escrow, fraud carve-out, and exclusive remedy.",
        "Confirm closing deliverables: certificates, consents, payoff letters, releases, escrow, and ancillary agreements.",
    ]

    return {
        "summary": {
            "deal_type": infer_deal_type(text),
            "possible_parties": extract_possible_parties(text),
            "word_count": len(tokenize(text)),
            "risk_level": risk_level,
            "risk_score": risk_score,
            "issues_found": len(issues),
            "crag_pipeline": [
                "Retrieve clause guidance from the M&A knowledge base.",
                "Grade contract sections against expected M&A clause coverage.",
                "Correct missing or weak areas with targeted questions and fallback clauses.",
                "Generate issue list, remediation steps, and source-backed drafting references.",
            ],
        },
        "issues": issues,
        "clause_breakdown": clause_breakdown,
        "retrieved_authorities": retrieved_authorities,
        "checklist": checklist,
        "disclaimer": "Educational drafting support only; not legal advice. Have qualified counsel review before use.",
    }


def value(details: dict[str, str], key: str, default: str) -> str:
    raw = str(details.get(key, "")).strip()
    return raw or default


def generate_agreement(details: dict[str, str]) -> dict[str, Any]:
    buyer = value(details, "buyer_name", "[BUYER/PARENT]")
    seller = value(details, "seller_name", "[TARGET/SELLER]")
    sub = value(details, "merger_sub_name", "[MERGER SUB]")
    transaction_type = value(details, "transaction_type", "reverse triangular merger")
    business = value(details, "target_business", "[target business]")
    price = value(details, "purchase_price", "[purchase price]")
    adjustment = value(details, "working_capital", "[working capital adjustment]")
    escrow = value(details, "escrow", "[escrow or holdback]")
    indemnity = value(details, "indemnity_cap", "[basket, cap, and carve-outs]")
    survival = value(details, "survival_period", "[survival period]")
    conditions = value(details, "closing_conditions", "[closing conditions]")
    law = value(details, "governing_law", "[governing law]")
    special = value(details, "special_issues", "[known special issues]")

    agreement = f"""DRAFT AGREEMENT AND PLAN OF MERGER

Date: {date.today().isoformat()}
Transaction Type: {transaction_type}

This Draft Agreement and Plan of Merger (this "Agreement") is entered into by and among {buyer}, {sub}, and {seller}.

RECITALS
A. {seller} operates the following business: {business}.
B. The parties desire to consummate a {transaction_type} on the terms set forth in this Agreement.
C. The boards, managers, members, or other applicable governing bodies of the parties have approved the transactions contemplated by this Agreement, subject to the conditions stated herein.

ARTICLE I - THE TRANSACTION
1.1 Structure. Upon the terms and subject to the conditions of this Agreement, {sub} shall merge with and into {seller}, and {seller} shall survive as a wholly owned subsidiary of {buyer}, unless the parties adapt this draft to an asset purchase or stock purchase structure.
1.2 Closing. The closing shall occur remotely by exchange of signatures and deliverables, or at another place and time agreed by the parties, after all closing conditions are satisfied or waived.
1.3 Consideration. At Closing, {buyer} shall pay or cause to be paid the following consideration: {price}.
1.4 Purchase Price Adjustment. The consideration shall be adjusted as follows: {adjustment}.
1.5 Escrow. The parties shall deposit the following amount or arrangement with an escrow agent as security for post-closing obligations: {escrow}.

ARTICLE II - REPRESENTATIONS AND WARRANTIES OF THE COMPANY
{seller} represents and warrants to {buyer} that, except as set forth in the Disclosure Schedules:
(a) Organization and Authority. {seller} is duly organized, validly existing, and authorized to conduct its business.
(b) Authorization. {seller} has authority to execute, deliver, and perform this Agreement.
(c) No Conflict. Execution and performance do not violate organizational documents, law, judgments, or material contracts, except as disclosed.
(d) Financial Statements and Liabilities. Financial statements are accurate in all material respects and there are no undisclosed liabilities except as disclosed.
(e) Material Contracts. Schedule 2.5 lists all material contracts, including contracts requiring consent due to assignment, merger, sale of assets, or change of control.
(f) Compliance; Litigation. {seller} is in compliance with applicable law and has disclosed pending or threatened disputes.
(g) Taxes. All tax returns have been filed and all taxes paid, except as disclosed.
(h) Employees and Benefits. Employee, contractor, benefit plan, wage-hour, and change-in-control obligations are disclosed.
(i) Intellectual Property and Data. {seller} owns or has rights to use the IP and data assets needed for the business and has disclosed open-source, privacy, and cybersecurity issues.

ARTICLE III - REPRESENTATIONS AND WARRANTIES OF BUYER
{buyer} represents and warrants that it is duly organized, has authority to enter this Agreement, and has or will have at Closing sufficient funds to pay the consideration and perform its obligations.

ARTICLE IV - COVENANTS
4.1 Ordinary Course. Between signing and Closing, {seller} shall operate in the ordinary course and preserve business relationships.
4.2 Restricted Actions. Without {buyer}'s consent, {seller} shall not issue equity, incur debt, dispose of material assets, amend material contracts, hire or terminate key employees outside the ordinary course, settle material claims, or make unusual payments.
4.3 Consents. The parties shall use commercially reasonable efforts to obtain required consents, approvals, payoff letters, releases, and notices.
4.4 Access. {seller} shall provide reasonable access to records, personnel, contracts, financial information, IP records, employment records, tax materials, and regulatory materials.

ARTICLE V - CONDITIONS TO CLOSING
Buyer closing conditions include: accuracy of representations, covenant performance, receipt of required consents and approvals, no injunction, no Material Adverse Effect, delivery of officer certificates, payoff letters, releases, escrow documents, and the following transaction-specific conditions: {conditions}.

ARTICLE VI - INDEMNIFICATION
6.1 Seller Indemnity. From and after Closing, Sellers shall indemnify Buyer and its affiliates for Losses arising from breaches of representations, warranties, covenants, pre-Closing taxes, unpaid indebtedness, transaction expenses, excluded liabilities, and the following special matters: {special}.
6.2 Limitations. Indemnity limitations shall be: {indemnity}.
6.3 Survival. Survival periods shall be: {survival}.
6.4 Fraud Carve-Out. Nothing in this Agreement limits remedies for fraud, intentional misrepresentation, or willful breach.
6.5 Exclusive Remedy. Except for fraud, equitable remedies, purchase price adjustment disputes, and matters expressly carved out, indemnification is the exclusive post-closing remedy.

ARTICLE VII - TERMINATION
This Agreement may be terminated by mutual written consent, by either party after the Outside Date, by a non-breaching party for uncured material breach, or if a final order prohibits the transaction. Confidentiality, fees, remedies, and miscellaneous provisions survive termination.

ARTICLE VIII - MISCELLANEOUS
8.1 Assignment. No party may assign this Agreement without consent, except Buyer may assign to an affiliate or financing source if Buyer remains liable.
8.2 Governing Law. This Agreement is governed by the laws of {law}.
8.3 Entire Agreement. This Agreement, schedules, exhibits, and ancillary documents constitute the entire agreement.
8.4 Specific Performance. The parties acknowledge that monetary damages may be inadequate and that specific performance and injunctive relief may be available.

DISCLOSURE SCHEDULE PROMPTS
Schedule 2.5 - Material contracts and change-of-control consents
Schedule 2.8 - Taxes
Schedule 2.9 - Employees, benefits, severance, and 280G matters
Schedule 2.10 - Intellectual property, open-source software, privacy, and cybersecurity
Schedule 6.1 - Special indemnities and known liabilities
"""

    retrieval = retrieve(f"{transaction_type} {special} indemnification closing conditions representations", top_k=5)
    follow_ups = [
        "Who are the equityholders or sellers that should be bound by restrictive covenants or indemnity obligations?",
        "Which contracts require consent because of assignment, merger, asset sale, or change of control?",
        "Should indemnity be seller-pro-rata, several-only, joint and several, escrow-limited, or RWI-backed?",
        "Are there regulatory approvals, antitrust filings, industry licenses, tax clearances, or foreign investment approvals?",
        "What ancillary documents are needed: escrow agreement, transition services, employment agreements, non-competes, payoff letters, releases, or IP assignments?",
    ]

    return {
        "agreement": agreement,
        "retrieved_authorities": retrieval,
        "follow_up_questions": follow_ups,
        "disclaimer": "Educational first draft only; not legal advice. Have qualified counsel tailor and review all provisions.",
    }