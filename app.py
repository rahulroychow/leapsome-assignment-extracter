"""Streamlit UI for reviewing open-ended learning responses in Leapsome.

Run:
    .venv/bin/streamlit run app.py
"""
import json
import time

import streamlit as st

from capture_token import CaptureError, NotLoggedIn, get_token, open_leapsome, seconds_left
from leapsome_api import (
    LeapsomeError,
    approve_responses,
    download_attachment,
    fetch_open_ended_responses,
    html_to_text,
)

st.set_page_config(page_title="Leapsome reviews", layout="wide")

STATUS_LABELS = {"pendingApproval": "🟡 Pending review", "approved": "✅ Approved", "rejected": "❌ Rejected"}
GRID = [2, 2, 5, 1.4]


STYLE = """
<style>
  #MainMenu, footer, header[data-testid="stHeader"] { display: none; }
  .block-container { padding-top: 2rem; max-width: 1200px; }

  .hero {
    background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 55%, #EC4899 120%);
    border-radius: 20px; padding: 28px 32px; margin-bottom: 20px;
    color: #fff; box-shadow: 0 10px 30px rgba(79, 70, 229, .25);
  }
  .hero-title { font-size: 2rem; font-weight: 800; letter-spacing: -.02em; line-height: 1.15; }
  .hero-sub { margin-top: 6px; font-size: 1rem; opacity: .9; max-width: 46rem; }

  .stat {
    background: #fff; border-radius: 16px; padding: 16px 20px;
    border: 1px solid #E8EAF3; box-shadow: 0 2px 10px rgba(31, 41, 55, .05);
    border-left: 6px solid var(--accent);
  }
  .stat-label { font-size: .78rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #6B7280; }
  .stat-value { font-size: 2.1rem; font-weight: 800; color: var(--accent); line-height: 1.2; }

  .progress-wrap { margin: 14px 0 6px; }
  .progress-label { display: flex; justify-content: space-between; font-size: .85rem; color: #4B5563; font-weight: 600; margin-bottom: 6px; }
  .progress-track { height: 10px; border-radius: 999px; background: #E5E7EB; overflow: hidden; }
  .progress-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #10B981, #34D399); }

  /* response rows and assessment sections */
  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #fff; border-radius: 14px; border-color: #E8EAF3 !important;
    box-shadow: 0 1px 6px rgba(31, 41, 55, .05);
  }
  div[data-testid="stExpander"] { border-radius: 14px; border-color: #E8EAF3; background: #fff; }
  div[data-testid="stExpander"] summary { font-weight: 600; }
  .stButton > button, .stDownloadButton > button { border-radius: 10px; font-weight: 600; }
</style>
"""


def stat_card(label, value, accent):
    return (
        f'<div class="stat" style="--accent:{accent}">'
        f'<div class="stat-label">{label}</div><div class="stat-value">{value}</div></div>'
    )


# --- Token ---------------------------------------------------------------------
def get_valid_token():
    """Return a token with time left, read from Chrome's Leapsome localStorage."""
    token = st.session_state.get("token")
    if token and seconds_left(token) > 120:
        return token
    try:
        token = get_token()
    except NotLoggedIn as e:
        st.session_state.update(needs_login=True, token_error=str(e))
        st.rerun()
    except CaptureError as e:
        st.session_state["token_error"] = str(e)
        st.rerun()
    st.session_state.update(token=token, needs_login=False)
    st.session_state.pop("token_error", None)
    return token


def adopt_token_if_available():
    """If a usable token has appeared in Chrome, store it and clear the old error."""
    try:
        token = get_token()
    except CaptureError:
        return False
    st.session_state.update(token=token, needs_login=False)
    st.session_state.pop("token_error", None)
    st.session_state.pop("review_raw", None)
    return True


@st.fragment(run_every=3)
def watch_for_token():
    """Poll Chrome's storage while we're waiting, so the error clears as soon as a token shows up."""
    if adopt_token_if_available():
        st.rerun()


def session_banner():
    """Show token problems with a one-click way to refresh Chrome's Leapsome session."""
    if st.session_state.get("needs_login") and adopt_token_if_available():
        return
    if st.session_state.get("needs_login"):
        watch_for_token()
    if st.session_state.get("token_error"):
        st.error(st.session_state["token_error"])
    if st.session_state.get("needs_login"):
        c1, c2, _ = st.columns([2, 2, 5])
        if c1.button("Open Leapsome in Chrome", type="primary", width="stretch"):
            try:
                open_leapsome()
            except CaptureError as e:
                st.session_state["token_error"] = str(e)
            else:
                with st.spinner("Waiting for Leapsome to refresh your session..."):
                    for _ in range(20):
                        time.sleep(1)
                        try:
                            st.session_state["token"] = get_token()
                            break
                        except NotLoggedIn:
                            continue
                if st.session_state.get("token") and seconds_left(st.session_state["token"]) > 120:
                    st.session_state.update(needs_login=False)
                    st.session_state.pop("token_error", None)
                    st.session_state.pop("review_raw", None)
            st.rerun()
        if c2.button("Try again", width="stretch"):
            st.session_state.pop("token", None)
            st.session_state.pop("review_raw", None)
            st.rerun()


# --- Data ----------------------------------------------------------------------
def load_review():
    token = get_valid_token()
    try:
        with st.spinner("Fetching responses..."):
            st.session_state["review_raw"] = fetch_open_ended_responses(
                token, st.session_state.get("review_filters", {})
            )
    except LeapsomeError as e:
        st.error(str(e))


def attachments(response_id, files):
    """Per-file 'Load' button; downloaded bytes are kept in session state."""
    cache = st.session_state.setdefault("attachments", {})
    for n, f in enumerate(files):
        name = f["key"].rsplit("/", 1)[-1]
        cache_key = (response_id, f["key"])
        if cache_key not in cache:
            if st.button(f"Load {name}", key=f"load-{response_id}-{n}"):
                token = get_valid_token()
                try:
                    with st.spinner(f"Downloading {name}..."):
                        cache[cache_key] = download_attachment(token, response_id, f)
                except LeapsomeError as e:
                    st.error(str(e))
                else:
                    st.rerun()
            continue
        data, mime = cache[cache_key], f.get("mimeType") or "application/octet-stream"
        st.caption(f"{name} · {mime} · {len(data):,} bytes")
        if mime.startswith("image/"):
            st.image(data)
        st.download_button(f"Download {name}", data, name, mime, key=f"dl-{response_id}-{n}")


def approval_cell(response_id, who):
    """Approve action for a grid row: Approve, then an explicit Confirm / Cancel."""
    if st.session_state.get("pending_approval") != response_id:
        if st.button("Approve", key=f"approve-{response_id}", width="stretch"):
            st.session_state["pending_approval"] = response_id
            st.rerun()
        return
    if st.button("Confirm", type="primary", key=f"confirm-{response_id}", width="stretch"):
        st.session_state.pop("pending_approval")
        token = get_valid_token()
        try:
            with st.spinner("Approving..."):
                approve_responses(token, [response_id])
        except LeapsomeError as e:
            st.error(str(e))
        else:
            st.session_state["approval_notice"] = f"Approved the submission by {who}."
            load_review()
            st.rerun()
    if st.button("Cancel", key=f"cancel-{response_id}", width="stretch"):
        st.session_state.pop("pending_approval")
        st.rerun()


# --- Page ----------------------------------------------------------------------
st.markdown(STYLE, unsafe_allow_html=True)
st.markdown(
    '<div class="hero"><div class="hero-title">Leapsome learnings reviewer</div></div>',
    unsafe_allow_html=True,
)

session_banner()

left, right = st.columns([5, 1], vertical_alignment="bottom")
with left.expander("Advanced: API filters"):
    filters_text = st.text_area("filters (JSON)", value="{}", height=80, label_visibility="collapsed")
if right.button("Refresh", width="stretch"):
    try:
        st.session_state["review_filters"] = json.loads(filters_text or "{}")
    except json.JSONDecodeError as e:
        st.error(f"filters is not valid JSON: {e}")
    else:
        load_review()

# Load automatically the first time the page opens.
if "review_raw" not in st.session_state and not st.session_state.get("needs_login"):
    load_review()

notice = st.session_state.pop("approval_notice", None)
if notice:
    st.success(notice)

raw = st.session_state.get("review_raw")
if raw is None:
    st.stop()
items = raw["data"]["items"]
if not items:
    st.warning("Nothing to review: the API returned no responses.")
    st.stop()

rows = []
for item in items:
    element = item["learningElement"]
    for r in item["responses"]:
        who = r["response"]["user"]
        rows.append(
            {
                # Versions of the same assessment share a commonId, so they group together.
                "Assessment ID": element.get("commonId") or element["_id"],
                "Assessment": element["name"],
                "Submitted by": who.get("fullname") or who.get("displayedName"),
                "Status": r["status"],
                "Answer": html_to_text(r["response"].get("text")),
                "_element": element,
                "_response": r,
            }
        )
total = len(rows)
pending_total = sum(r["Status"] == "pendingApproval" for r in rows)
reviewed_total = total - pending_total

s1, s2, s3 = st.columns(3)
s1.markdown(stat_card("Assessments", len({r["Assessment ID"] for r in rows}), "#4F46E5"), unsafe_allow_html=True)
s2.markdown(stat_card("Waiting for you", pending_total, "#F59E0B"), unsafe_allow_html=True)
s3.markdown(stat_card("Reviewed", reviewed_total, "#10B981"), unsafe_allow_html=True)
st.markdown(
    '<div class="progress-wrap"><div class="progress-label">'
    f"<span>Review progress</span><span>{reviewed_total} of {total} reviewed</span></div>"
    f'<div class="progress-track"><div class="progress-fill" style="width:{100 * reviewed_total // total}%"></div></div></div>',
    unsafe_allow_html=True,
)
st.write("")

statuses = sorted({r["Status"] for r in rows})
c1, c2 = st.columns(2)
text = c1.text_input("Search", placeholder="Assessment, submitter or answer text")
picked = c2.multiselect(
    "Status", statuses, placeholder="Any status", format_func=lambda s: STATUS_LABELS.get(s, s).split(" ", 1)[-1]
)
needle = text.lower()
rows = [
    r for r in rows
    if (not picked or r["Status"] in picked)
    and (not needle or needle in " ".join(str(r[k]) for k in ("Assessment", "Submitted by", "Answer")).lower())
]
if not rows:
    st.warning("No responses match the current filters.")
    st.stop()

# Group by assessment, keeping the API's order.
groups = {}
for r in rows:
    groups.setdefault(r["Assessment ID"], []).append(r)

# Expand/collapse every assessment and every submission's details at once.
b1, b2, caption_col = st.columns([1, 1, 6], vertical_alignment="center")
if b1.button("Expand all", width="stretch"):
    st.session_state["expand_all"] = True
if b2.button("Collapse all", width="stretch"):
    st.session_state["expand_all"] = False
expand_all = st.session_state.get("expand_all")  # None = default (open assessments with pending items)
if len(rows) != total:
    caption_col.caption(f"Showing {len(rows)} of {total} responses in {len(groups)} assessment{'s' if len(groups) != 1 else ''}.")

for group in groups.values():
    pending = sum(r["Status"] == "pendingApproval" for r in group)
    title = f"{group[0]['Assessment']}  ·  {len(group)} response{'s' if len(group) != 1 else ''}"
    title += f"  ·  🟡 {pending} pending" if pending else "  ·  all reviewed"
    with st.expander(title, expanded=pending > 0 if expand_all is None else expand_all):
        element = group[-1]["_element"]
        if element.get("description"):
            st.caption("Assessment: " + html_to_text(element["description"]))
        if element.get("instructions"):
            st.caption("Instructions: " + html_to_text(element["instructions"]))

        # One row per response, details expand underneath, Approve on the row.
        header = st.columns(GRID)
        for col, label in zip(header, ["Submitted by", "Status", "Answer"]):
            col.markdown(f"**{label}**")
        for r in group:
            resp = r["_response"]
            with st.container(border=True):
                c = st.columns(GRID, vertical_alignment="center")
                c[0].write(r["Submitted by"])
                c[1].write(STATUS_LABELS.get(r["Status"], f"⚪ {r['Status']}"))
                preview = r["Answer"] if len(r["Answer"]) <= 80 else r["Answer"][:77] + "..."
                c[2].write(preview or "—")
                if r["Status"] == "pendingApproval":
                    with c[3]:
                        approval_cell(resp["_id"], r["Submitted by"])
                    if st.session_state.get("pending_approval") == resp["_id"]:
                        st.warning(f"Approve the submission by **{r['Submitted by']}**? This changes it in Leapsome.")
                with st.expander("Details", expanded=bool(expand_all)):
                    st.write(r["Answer"])
                    attachments(resp["_id"], resp["response"].get("files") or [])
