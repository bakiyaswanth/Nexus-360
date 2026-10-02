"""Selected-customer context: the single source of truth for which customer every page shows.

Works on any MutableMapping (st.session_state in the app, a dict in tests). Customer-specific derived state
is registered in CUSTOMER_SCOPED_KEYS and cleared whenever the customer changes, so no page can render
data from a previously selected customer.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from contracts import normalize_customer_id

SELECTED_ID = "selected_customer_id"
SELECTED = "selected_customer"          # cached header facts for the context bar
NONCE = "selection_nonce"               # bumps widget keys so list selections can't re-apply a stale customer
CUSTOMER_SCOPED_KEYS = ("nba", "outreach", "nba_error", "outreach_error", "last_log_result")


def init_state(ss: MutableMapping, initial_customer_id: Any = None) -> None:
    """Initialise keys once per session; optionally restore a customer (e.g. from the URL)."""
    ss.setdefault(SELECTED_ID, None)
    ss.setdefault(SELECTED, None)
    ss.setdefault(NONCE, 0)
    for k in CUSTOMER_SCOPED_KEYS:
        ss.setdefault(k, None)
    cid = normalize_customer_id(initial_customer_id)
    if cid and not ss.get(SELECTED_ID):
        ss[SELECTED_ID] = cid


def get_selected_customer_id(ss: MutableMapping) -> str | None:
    return ss.get(SELECTED_ID) or None


def get_selected_customer(ss: MutableMapping) -> dict | None:
    """Header facts of the selected customer, only if they belong to the selected ID."""
    cid, cust = get_selected_customer_id(ss), ss.get(SELECTED)
    if cid and isinstance(cust, dict) and cust.get("customer_id") == cid:
        return cust
    return None


def clear_customer_scoped(ss: MutableMapping) -> None:
    for k in CUSTOMER_SCOPED_KEYS:
        ss[k] = None


def select_customer(ss: MutableMapping, customer_id: Any, header: dict | None = None, *, from_list: bool = False) -> bool:
    """Select a customer. Returns True if the selection changed.

    Switching customers clears every customer-scoped result (NBA, outreach, errors) and, unless the selection
    came from a list widget itself, bumps the nonce so list widgets reset instead of re-selecting the old row.
    """
    cid = normalize_customer_id(customer_id) or None
    changed = cid != ss.get(SELECTED_ID)
    if changed:
        ss[SELECTED_ID] = cid
        clear_customer_scoped(ss)
        if not from_list:
            ss[NONCE] = int(ss.get(NONCE) or 0) + 1
    if header is not None and cid and header.get("customer_id") == cid:
        ss[SELECTED] = header
    elif changed:
        ss[SELECTED] = None
    return changed


def clear_selection(ss: MutableMapping) -> None:
    select_customer(ss, None)


def set_scoped(ss: MutableMapping, key: str, value: dict | None) -> None:
    """Store a customer-scoped result tagged with the customer it belongs to."""
    assert key in CUSTOMER_SCOPED_KEYS, key
    cid = get_selected_customer_id(ss)
    ss[key] = None if value is None else {**value, "_customer_id": cid}


def get_scoped(ss: MutableMapping, key: str) -> dict | None:
    """Read a customer-scoped result; returns None if it belongs to another customer (stale)."""
    v = ss.get(key)
    if isinstance(v, dict) and v.get("_customer_id") == get_selected_customer_id(ss):
        return v
    return None
