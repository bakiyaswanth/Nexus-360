"""End-to-end UI flow with Streamlit AppTest against live Snowflake (local key-pair connection).

Dashboard -> select customer -> context bar -> Customer 360 -> NBA (offer) -> Offers -> switch customer -> rerun.
Opt-in (needs a local Streamlit Snowflake connection): ACTION360_UI_TESTS=1 pytest tests/test_app_flow.py
"""
import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
pytestmark = pytest.mark.skipif(os.environ.get("ACTION360_UI_TESTS") != "1",
                                reason="set ACTION360_UI_TESTS=1 (local Snowflake connection required)")


@pytest.fixture(scope="module")
def at():
    os.environ.setdefault("SNOWFLAKE_DEFAULT_CONNECTION_NAME", os.environ.get("ACTION360_CONNECTION", "action360_dev"))
    sys.path.insert(0, str(APP_DIR))
    from streamlit.testing.v1 import AppTest
    cwd = os.getcwd()
    os.chdir(APP_DIR)
    app = AppTest.from_file(str(APP_DIR / "streamlit_app.py"), default_timeout=180)
    app.run()
    yield app
    os.chdir(cwd)


def page_text(app) -> str:
    return "\n".join([m.value for m in app.markdown] + [t.value for t in app.title] + [str(e.value) for e in app.error]
                     + [str(w.value) for w in app.warning] + [m.label for m in app.metric])


def no_exceptions(app):
    assert not app.exception, [e.value for e in app.exception]


def select_via_search(app, cid):
    nonce = app.session_state["selection_nonce"]
    app.text_input(key=f"find_{nonce}").input(cid).run()
    no_exceptions(app)
    app.button(key=f"fr_{nonce}_{cid}").click().run()
    no_exceptions(app)


def goto(app, key):
    app.button(key=f"cb_{key}").click().run()
    no_exceptions(app)


def test_1_dashboard_without_customer(at):
    no_exceptions(at)
    assert at.title[0].value == "Portfolio dashboard"
    assert at.session_state["selected_customer_id"] is None
    assert not any(b.key == "cb_nba" for b in at.button)          # no contextual nav before selection


def test_2_select_customer_shows_context_bar(at):
    select_via_search(at, "C10238")
    assert at.session_state["selected_customer_id"] == "C10238"
    txt = page_text(at)
    assert "Selected customer" in txt and "C10238" in txt and "risk" in txt.lower()
    keys = {b.key for b in at.button}
    assert {"cb_c360", "cb_nba", "cb_offers", "cb_interactions"} <= keys


def test_3_customer_360_preserves_customer_and_previews_offer(at):
    goto(at, "c360")
    txt = page_text(at)
    assert at.title[0].value == "Customer 360" and at.session_state["selected_customer_id"] == "C10238"
    assert "Next best action preview" in txt and "Annual card fee waiver" in txt and "Eligible" in txt


def test_4_nba_shows_action_offer_eligibility_evidence(at):
    goto(at, "nba")
    txt = page_text(at)
    assert at.title[0].value == "Next best action"
    assert "Recommended action" in txt and "Service recovery" in txt
    assert "Recommended offer" in txt and "Annual card fee waiver (goodwill)" in txt and "Goodwill annual fee waiver" in txt
    assert "✓ Eligible" in txt and "Why eligible" in txt and "Holds a credit card" in txt
    assert "Other eligible options" in txt and "Not eligible (" in "\n".join(e.label for e in at.expander)
    assert "Supporting evidence" in txt and "Why now" in txt
    nba = at.session_state["nba"]
    assert nba["_customer_id"] == "C10238" and nba["offer_id"] == "OFF_FEE_WAIVER"
    assert any(b.label == "Generate outreach" for b in at.button)


def test_5_rerun_keeps_customer_and_does_not_recompute(at):
    rec_id = at.session_state["nba"]["recommendation_id"]
    at.run()
    no_exceptions(at)
    assert at.session_state["selected_customer_id"] == "C10238"
    assert at.session_state["nba"]["recommendation_id"] == rec_id     # cached for the customer, no new engine call


def test_6_approve_and_log_backend_used_by_ui(at):
    # AppTest does not expose widgets inside st.popover; the popover is exercised in the live browser test.
    # Here: the same data-layer call the popover makes, for the recommendation the UI is showing.
    sys.path.insert(0, str(APP_DIR))
    import data as d
    rec_id = at.session_state["nba"]["recommendation_id"]
    res = d.log_action(rec_id, "DEFERRED", "", "AppTest UI flow")
    assert res["logged"] is True and res["user_action"] == "DEFERRED"
    blocked = d.log_action(rec_id, "APPROVED", "OFF_TOPUP_LOAN", "AppTest ineligible")
    assert blocked["logged"] is False


def test_7_offers_page_lists_statuses(at):
    goto(at, "offers")
    txt = page_text(at)
    assert at.title[0].value == "Offers" and "Recommended offer" in txt
    df = at.dataframe[0].value
    assert set(df["Status"]) >= {"✓ Eligible", "✕ Not eligible"}
    assert (df["Recommended"] == "Yes").sum() == 1
    assert df["Offer ID"].is_unique


def test_8_switch_customer_refreshes_everything(at):
    goto(at, "switch")
    assert at.title[0].value == "Portfolio dashboard" and at.session_state["selected_customer_id"] == "C10238"
    select_via_search(at, "C10417")
    assert at.session_state["selected_customer_id"] == "C10417"
    assert at.session_state["nba"] is None and at.session_state["last_log_result"] is None   # A's results cleared
    goto(at, "nba")
    txt = page_text(at)
    assert "Payment-plan discussion" in txt and "Hardship assistance plan" in txt and "Service recovery" not in txt
    nba = at.session_state["nba"]
    assert nba["_customer_id"] == "C10417" and nba["offer_id"] == "OFF_HARDSHIP_PLAN"
    assert "C10417" in txt and "C10238" not in txt


def test_9_no_offer_customer_shows_explanation(at):
    goto(at, "switch")
    select_via_search(at, "C11024")
    goto(at, "nba")
    txt = page_text(at)
    assert "No offer needed for this action" in txt and "policy does not attach a commercial offer" in txt
    assert "Recommended offer" in txt


def test_10_customer_pages_require_selection(at):
    goto(at, "offers")
    at.button(key="cb_clear").click().run()
    no_exceptions(at)
    assert at.session_state["selected_customer_id"] is None
    assert at.title[0].value == "Portfolio dashboard"
    assert not any(b.key == "cb_nba" for b in at.button)
