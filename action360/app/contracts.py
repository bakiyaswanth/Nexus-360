"""Response contracts for ACTION360: validation + normalisation between Snowflake procedures and the UI.

Pure Python (no Streamlit, no Snowflake) so it is unit-testable. Business decisions are NOT made here:
the offer and action always come from the governed procedures. This module only guarantees the UI gets a
predictable, null-safe shape and never shows an unvalidated or ineligible offer as "recommended".
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

log = logging.getLogger("action360.contracts")

# ------------------------------------------------------------------ status vocabulary
ELIGIBLE, NOT_ELIGIBLE, NEEDS_REVIEW, UNAVAILABLE = "ELIGIBLE", "NOT_ELIGIBLE", "NEEDS_REVIEW", "UNAVAILABLE"
ELIGIBILITY_STATUSES = (ELIGIBLE, NOT_ELIGIBLE, NEEDS_REVIEW, UNAVAILABLE)

# label, text icon (status never relies on colour alone), css class
STATUS_META = {
    ELIGIBLE: ("Eligible", "✓", "s-ok"),
    NOT_ELIGIBLE: ("Not eligible", "✕", "s-bad"),
    NEEDS_REVIEW: ("Needs review", "?", "s-warn"),
    UNAVAILABLE: ("Unavailable", "–", "s-muted"),
}

# offer_status values returned by AI.GET_CUSTOMER_OFFERS (+ NEEDS_REVIEW when validation fails)
RECOMMENDED, NO_OFFER_REQUIRED, NO_ELIGIBLE_OFFER, NO_RECOMMENDATION = (
    "RECOMMENDED", "NO_OFFER_REQUIRED", "NO_ELIGIBLE_OFFER", "NO_RECOMMENDATION")
OFFER_STATUSES = (RECOMMENDED, NO_OFFER_REQUIRED, NO_ELIGIBLE_OFFER, NO_RECOMMENDATION, NEEDS_REVIEW)

UNKNOWN_ELIGIBILITY = "Eligibility could not be determined"
NO_ELIGIBLE_OFFER_TEXT = "No eligible offer found"
CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")


# ------------------------------------------------------------------ primitives
def as_obj(v: Any) -> Any:
    """Decode JSON strings returned by VARIANT procedures; pass through everything else."""
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def text(v: Any) -> str:
    """Null-safe trimmed string."""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v).strip()


def num(v: Any) -> float | None:
    """Numeric or None (never raises, rejects NaN/inf/bool)."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def str_list(v: Any) -> list[str]:
    v = as_obj(v)
    if not isinstance(v, list):
        return []
    return [text(x) for x in v if text(x)]


def normalize_customer_id(cid: Any) -> str:
    """'  c10238 ' -> 'C10238'. Customer IDs are strings; integers are not valid IDs."""
    return text(cid).upper()


# ------------------------------------------------------------------ offers
def validate_offer(raw: Any) -> tuple[dict | None, list[str]]:
    """Validate one candidate offer. Returns (offer | None, issues). Offers without id/name are dropped."""
    issues: list[str] = []
    raw = as_obj(raw)
    if not isinstance(raw, dict):
        return None, ["offer is not an object"]
    oid, name = text(raw.get("offer_id")).upper(), text(raw.get("offer_name"))
    if not oid:
        return None, ["offer without offer_id dropped"]
    if not name:
        return None, [f"{oid}: missing offer_name, dropped"]
    status = text(raw.get("eligibility_status")).upper().replace(" ", "_")
    if status not in ELIGIBILITY_STATUSES:
        issues.append(f"{oid}: unknown eligibility status {status or 'NULL'} -> NEEDS_REVIEW")
        status = NEEDS_REVIEW
    reason = text(raw.get("reason"))
    if not reason:
        reason = UNKNOWN_ELIGIBILITY if status == NEEDS_REVIEW else f"No reason provided ({STATUS_META[status][0].lower()})"
        issues.append(f"{oid}: missing reason")
    priority = num(raw.get("priority"))
    if raw.get("priority") is not None and priority is None:
        issues.append(f"{oid}: non-numeric priority {raw.get('priority')!r}")
    return {
        "offer_id": oid,
        "offer_name": name,
        "description": text(raw.get("description")),
        "value_to_customer": text(raw.get("value_to_customer")),
        "category": text(raw.get("category")).upper(),
        "priority": priority,
        "policy_doc": text(raw.get("policy_doc")),
        "eligibility_status": status,
        "reason": reason,
        "passed_rules": str_list(raw.get("passed_rules")),
        "failed_rules": str_list(raw.get("failed_rules")),
        "business_purpose": text(raw.get("business_purpose")),
        "expected_business_outcome": text(raw.get("expected_business_outcome")),
        "is_recommended": raw.get("is_recommended") is True,
    }, issues


def _error(cid: str, message: str, code: str) -> dict:
    return {"ok": False, "error": message, "error_code": code, "customer_id": cid, "offer": None,
            "candidate_offers": [], "alternatives": [], "not_eligible": [], "other": [], "issues": [message],
            "offer_status": None, "offer_status_reason": ""}


def validate_offer_contract(raw: Any, expected_customer_id: str) -> dict:
    """Validate AI.GET_CUSTOMER_OFFERS output for the CURRENT customer.

    Guarantees:
      * customer_id matches the selected customer (stale/mis-routed responses are rejected)
      * every candidate has offer_id, offer_name, a known eligibility status and a reason; duplicates removed
      * the recommended offer is ELIGIBLE - otherwise it is never shown as recommended (status -> NEEDS_REVIEW)
      * no-offer states always carry an explanation
    """
    cid = normalize_customer_id(expected_customer_id)
    raw = as_obj(raw)
    if not isinstance(raw, dict):
        return _error(cid, "Unexpected offer response format", "BAD_FORMAT")
    if raw.get("found") is False:
        return _error(cid, text(raw.get("message")) or f"Customer {cid} not found", "NOT_FOUND")
    got = normalize_customer_id(raw.get("customer_id"))
    if got != cid:
        return _error(cid, f"Offer response was for {got or 'unknown'}, not {cid}", "CUSTOMER_MISMATCH")

    issues: list[str] = []
    seen: set[str] = set()
    offers: list[dict] = []
    raw_list = as_obj(raw.get("candidate_offers"))
    for item in raw_list if isinstance(raw_list, list) else []:
        o, iss = validate_offer(item)
        issues += iss
        if o is None:
            continue
        if o["offer_id"] in seen:
            issues.append(f"{o['offer_id']}: duplicate removed")
            continue
        seen.add(o["offer_id"])
        offers.append(o)

    status = text(raw.get("offer_status")).upper()
    reason = text(raw.get("offer_status_reason"))
    if status not in OFFER_STATUSES:
        issues.append(f"unknown offer_status {status or 'NULL'}")
        status = NEEDS_REVIEW

    rec_raw = as_obj(raw.get("offer"))
    rec = None
    if rec_raw:
        rec_id = text(rec_raw.get("offer_id")).upper() if isinstance(rec_raw, dict) else ""
        rec = next((o for o in offers if o["offer_id"] == rec_id), None)
        if rec is None:
            rec, iss = validate_offer(rec_raw)
            issues += iss
    # only one recommended flag, and only on the validated recommended offer
    for o in offers:
        o["is_recommended"] = rec is not None and o["offer_id"] == rec["offer_id"]

    if rec is not None and rec["eligibility_status"] != ELIGIBLE:
        issues.append(f"recommended offer {rec['offer_id']} is {rec['eligibility_status']} - not shown as recommended")
        for o in offers:
            o["is_recommended"] = False
        rec, status, reason = None, NEEDS_REVIEW, (
            f"{UNKNOWN_ELIGIBILITY}: the engine's offer did not pass validation. Recalculate or review manually.")
    elif status == RECOMMENDED and rec is None:
        status, reason = NEEDS_REVIEW, f"{UNKNOWN_ELIGIBILITY}: no offer details were returned."
    elif rec is not None and status != RECOMMENDED:
        issues.append(f"offer present but status {status}; treating as RECOMMENDED")
        status = RECOMMENDED
    if not reason:
        reason = {NO_OFFER_REQUIRED: "This action does not carry a commercial offer.",
                  NO_ELIGIBLE_OFFER: "No offer passed the hard eligibility rules.",
                  NO_RECOMMENDATION: "No action passed the guardrails for this customer.",
                  RECOMMENDED: rec["reason"] if rec else "",
                  NEEDS_REVIEW: UNKNOWN_ELIGIBILITY}[status]

    others = [o for o in offers if not o["is_recommended"]]
    for i in issues:
        log.info("offer contract %s: %s", cid, i)
    return {
        "ok": True, "error": None, "error_code": None,
        "customer_id": cid,
        "industry_type": text(raw.get("industry_type")),
        "recommended_action": text(raw.get("recommended_action")),
        "action_name": text(raw.get("action_name")),
        "business_purpose": text(raw.get("business_purpose")),
        "offer_category": text(raw.get("offer_category")),
        "offer_status": status,
        "offer_status_reason": reason,
        "offer": rec,
        "candidate_offers": ([rec] if rec else []) + others,
        "alternatives": [o for o in others if o["eligibility_status"] == ELIGIBLE],
        "not_eligible": [o for o in others if o["eligibility_status"] == NOT_ELIGIBLE],
        "other": [o for o in others if o["eligibility_status"] in (NEEDS_REVIEW, UNAVAILABLE)],
        "issues": issues,
    }


def headline_for_no_offer(contract: dict) -> str:
    """User-facing headline when there is no recommended offer (never an empty card)."""
    st_ = contract.get("offer_status")
    if st_ == NO_OFFER_REQUIRED:
        return "No offer needed for this action"
    if st_ == NEEDS_REVIEW:
        return UNKNOWN_ELIGIBILITY
    if st_ == NO_RECOMMENDATION:
        return "No recommendation available"
    return NO_ELIGIBLE_OFFER_TEXT


def format_offer_for_ui(offer: dict | None) -> dict | None:
    """Display-ready view of a validated offer (labels, icon, rules)."""
    if not offer:
        return None
    label, icon, css = STATUS_META.get(offer.get("eligibility_status"), STATUS_META[NEEDS_REVIEW])
    status = offer.get("eligibility_status")
    if status == ELIGIBLE:
        why_title, rules = "Why eligible", offer.get("passed_rules") or []
    elif status == NOT_ELIGIBLE:
        why_title, rules = "Why not eligible", offer.get("failed_rules") or []
    else:
        why_title, rules = "Eligibility", []
    return {
        "offer_id": offer.get("offer_id"),
        "title": offer.get("offer_name") or offer.get("offer_id"),
        "description": offer.get("description") or "No description in the catalogue.",
        "value": offer.get("value_to_customer") or "",
        "status": status,
        "status_label": label,
        "status_icon": icon,
        "status_css": css,
        "status_text": f"{icon} {label}",
        "why_title": why_title,
        "rules": rules,
        "reason": offer.get("reason") or UNKNOWN_ELIGIBILITY,
        "purpose": offer.get("business_purpose") or "-",
        "outcome": offer.get("expected_business_outcome") or "",
        "priority": "-" if offer.get("priority") is None else f"{offer['priority']:.0f}",
        "is_recommended": bool(offer.get("is_recommended")),
    }


# ------------------------------------------------------------------ eligibility check (single offer)
def parse_eligibility_check(raw: Any, customer_id: str, offer_id: str) -> dict:
    """Normalise AI.CHECK_OFFER_ELIGIBILITY for one offer -> {status, reason, rules}."""
    cid, oid = normalize_customer_id(customer_id), text(offer_id).upper()
    raw = as_obj(raw)
    if not isinstance(raw, dict) or raw.get("found") is False:
        return {"customer_id": cid, "offer_id": oid, "status": NEEDS_REVIEW,
                "reason": text(raw.get("message")) if isinstance(raw, dict) else UNKNOWN_ELIGIBILITY}
    if raw.get("offers") is None and raw.get("eligibility"):  # offer not applicable to customer
        return {"customer_id": cid, "offer_id": oid, "status": NOT_ELIGIBLE, "reason": text(raw.get("reason"))}
    rows = [r for r in (as_obj(raw.get("offers")) or []) if isinstance(r, dict) and text(r.get("offer_id")).upper() == oid]
    if not rows:
        return {"customer_id": cid, "offer_id": oid, "status": NEEDS_REVIEW, "reason": UNKNOWN_ELIGIBILITY}
    r = rows[0]
    status = text(r.get("eligibility")).upper().replace(" ", "_")
    status = status if status in (ELIGIBLE, NOT_ELIGIBLE) else NEEDS_REVIEW
    rules = str_list(r.get("passed_rules") if status == ELIGIBLE else r.get("failed_rules"))
    return {"customer_id": cid, "offer_id": oid, "status": status, "rules": rules,
            "reason": "; ".join(rules) if rules else UNKNOWN_ELIGIBILITY}


# ------------------------------------------------------------------ NBA
def parse_nba_response(raw: Any, expected_customer_id: str) -> dict:
    """Normalise AI.CALCULATE_NEXT_BEST_ACTION output (null-safe, customer-checked)."""
    cid = normalize_customer_id(expected_customer_id)
    raw = as_obj(raw)
    if not isinstance(raw, dict):
        return {"ok": False, "customer_id": cid, "error": "Unexpected recommendation format"}
    if raw.get("found") is False:
        return {"ok": False, "customer_id": cid, "error": text(raw.get("message")) or f"Customer {cid} not found"}
    if normalize_customer_id(raw.get("customer_id")) != cid:
        return {"ok": False, "customer_id": cid, "error": "Recommendation belongs to a different customer"}
    rec_id = text(raw.get("recommendation_id"))
    if not rec_id or not text(raw.get("selected_action")):
        return {"ok": False, "customer_id": cid, "error": "Recommendation is incomplete"}

    reasons = []
    for r in as_obj(raw.get("reasons")) or []:
        if isinstance(r, dict) and text(r.get("signal")):
            reasons.append({"signal": text(r["signal"]), "value": num(r.get("value")) or 0.0,
                            "weight": num(r.get("weight")) or 0.0, "contribution": num(r.get("contribution")) or 0.0})
    ev = as_obj(raw.get("evidence")) or {}
    ev = ev if isinstance(ev, dict) else {}

    def _docs(v):
        v = as_obj(v)
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    offer = as_obj(raw.get("offer"))
    conf = text(raw.get("confidence")).upper()
    return {
        "ok": True, "error": None,
        "recommendation_id": rec_id,
        "customer_id": cid,
        "selected_action": text(raw.get("selected_action")),
        "action_name": text(raw.get("action_name")),
        "action_score": num(raw.get("action_score")),
        "business_purpose": text(raw.get("business_purpose")),
        "confidence": conf if conf in CONFIDENCE_LEVELS else "UNKNOWN",
        "ai_route": text(raw.get("ai_route")),
        "offer_id": text(offer.get("offer_id")).upper() if isinstance(offer, dict) else "",
        "reasons": reasons,
        "facts": str_list(ev.get("structured_facts")),
        "interaction_evidence": _docs(ev.get("interaction_evidence")),
        "policy_evidence": _docs(ev.get("policy_evidence")),
        "candidates": [c for c in (as_obj(raw.get("candidates")) or []) if isinstance(c, dict)],
        "provenance": text(raw.get("decision_provenance")),
    }


# ------------------------------------------------------------------ agent
def parse_agent_response(resp: Any) -> dict:
    """Extract text, tool trace and tool results from a DATA_AGENT_RUN response."""
    resp = as_obj(resp)
    if not isinstance(resp, dict):
        return {"text": text(resp), "tools": [], "tool_results": [], "warnings": None}
    out_text, tools, results = [], [], []
    for c in resp.get("content") or []:
        if not isinstance(c, dict):
            continue
        kind = c.get("type")
        if kind == "text":
            out_text.append(text(c.get("text")))
        elif kind == "tool_use":
            name = text((c.get("tool_use") or {}).get("name"))
            if name:
                tools.append(name)
        elif kind == "tool_result":
            results.append(c.get("tool_result") or {})
    return {"text": "\n".join(t for t in out_text if t).strip(), "tools": tools, "tool_results": results,
            "warnings": resp.get("warnings")}
