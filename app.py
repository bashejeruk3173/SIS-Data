"""
PESRP SIS Dashboard — Student, Teacher/Staff, and Sanctioned Post data.
"""

from __future__ import annotations

import html
import traceback
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from sis_client import (
    DEFAULT_WORKERS,
    MARKAZ_TYPES,
    MAX_ATTEMPTS,
    MODULE_VERSION,
    SISClient,
    STATIC_DISTRICTS,
    clear_tehsil_disk_cache,
    classify_markaz_type,
    flatten_wide_columns,
    load_tehsils_disk_cache,
    save_tehsils_disk_cache,
)

st.set_page_config(
    page_title="PESRP SIS Dashboard",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="expanded",
)

DASHBOARD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');

:root {
    --teal: #0d9488;
    --teal-dark: #0f766e;
    --teal-soft: #ccfbf1;
    --slate-50: #f8fafc;
    --slate-100: #f1f5f9;
    --slate-200: #e2e8f0;
    --slate-300: #cbd5e1;
    --slate-500: #64748b;
    --slate-600: #475569;
    --slate-700: #334155;
    --slate-800: #1e293b;
    --slate-900: #0f172a;
    --surface: #ffffff;
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
}

#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
div[data-testid="stToolbar"] { display: none; }

.block-container {
    padding-top: 1rem !important;
    padding-bottom: 1.5rem !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    max-width: 1600px;
}

.app-chrome {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    border: 1px solid var(--slate-200);
    border-radius: 10px;
    padding: 0.85rem 1.15rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.app-chrome-brand {
    display: flex;
    align-items: center;
    gap: 0.85rem;
}
.app-chrome-mark {
    width: 36px;
    height: 36px;
    border-radius: 8px;
    background: linear-gradient(135deg, #0d9488 0%, #0f766e 100%);
    color: #fff;
    font-weight: 700;
    font-size: 0.72rem;
    letter-spacing: 0.02em;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}
.app-chrome-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--slate-900);
    line-height: 1.2;
    margin: 0;
}
.app-chrome-sub {
    font-size: 0.78rem;
    color: var(--slate-500);
    margin: 0.1rem 0 0 0;
}
.app-status {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--slate-600);
    background: var(--slate-50);
    border: 1px solid var(--slate-200);
    border-radius: 999px;
    padding: 0.3rem 0.7rem;
    white-space: nowrap;
}
.app-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
}

section[data-testid="stSidebar"] {
    background: #0f172a !important;
    border-right: 1px solid #1e293b;
}
section[data-testid="stSidebar"] > div {
    padding-top: 1rem;
}
.sidebar-brand {
    padding: 0.25rem 0.5rem 1rem 0.5rem;
    border-bottom: 1px solid #1e293b;
    margin-bottom: 0.85rem;
}
.sidebar-brand-name {
    color: #f8fafc;
    font-weight: 700;
    font-size: 0.95rem;
    margin: 0;
}
.sidebar-brand-tag {
    color: #94a3b8;
    font-size: 0.72rem;
    margin: 0.2rem 0 0 0;
}
.nav-label {
    color: #64748b;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin: 0 0 0.45rem 0.35rem;
}
section[data-testid="stSidebar"] .stRadio > label { display: none; }
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] { gap: 0.25rem; }
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label {
    background: transparent !important;
    border: 1px solid transparent !important;
    border-radius: 8px !important;
    padding: 0.55rem 0.7rem !important;
    color: #cbd5e1 !important;
    font-weight: 500 !important;
    font-size: 0.88rem !important;
}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover {
    background: #1e293b !important;
    color: #f1f5f9 !important;
}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:has(input:checked) {
    background: rgba(13, 148, 136, 0.18) !important;
    border-color: rgba(13, 148, 136, 0.45) !important;
    color: #5eead4 !important;
}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label > div:first-child {
    display: none;
}

.page-head { margin: 0 0 0.85rem 0; }
.page-head h2 {
    margin: 0;
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--slate-900);
}
.page-head p {
    margin: 0.2rem 0 0 0;
    font-size: 0.84rem;
    color: var(--slate-500);
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--surface);
    border-color: var(--slate-200) !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}
.toolbar-title {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--slate-500);
    margin: 0 0 0.15rem 0.1rem;
}
.toolbar-hint {
    font-size: 0.75rem;
    color: var(--slate-500);
    margin: 0.15rem 0 0.35rem 0.1rem;
}

div.stButton > button[kind="primary"] {
    background-color: var(--teal) !important;
    border-color: var(--teal) !important;
    color: white !important;
    font-weight: 600 !important;
    min-height: 2.5rem;
    border-radius: 8px !important;
}
div.stButton > button[kind="primary"]:hover {
    background-color: var(--teal-dark) !important;
    border-color: var(--teal-dark) !important;
}

div[data-testid="stSelectbox"] label,
div[data-testid="stTextInput"] label {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    color: var(--slate-500) !important;
    letter-spacing: 0.02em;
}

.empty-panel {
    border: 1px dashed var(--slate-300);
    background: var(--slate-50);
    border-radius: 10px;
    padding: 2.25rem 1.5rem;
    text-align: center;
}
.empty-panel-icon {
    width: 42px;
    height: 42px;
    margin: 0 auto 0.75rem auto;
    border-radius: 10px;
    background: var(--teal-soft);
    color: var(--teal-dark);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 1rem;
    font-family: 'IBM Plex Mono', monospace;
}
.empty-panel h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--slate-800);
}
.empty-panel p {
    margin: 0.35rem 0 0 0;
    font-size: 0.86rem;
    color: var(--slate-500);
}

.results-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin: 0.25rem 0 0.65rem 0;
}
.results-bar-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--slate-700);
}
.results-bar-meta {
    font-size: 0.78rem;
    color: var(--slate-500);
    font-family: 'IBM Plex Mono', monospace;
}

.placeholder-badge {
    display: inline-block;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #b45309;
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 999px;
    padding: 0.15rem 0.55rem;
    margin-left: 0.4rem;
    vertical-align: middle;
}

div[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--slate-200);
    border-radius: 8px;
    padding: 0.65rem 0.85rem;
}
div[data-testid="stMetric"] label {
    font-size: 0.72rem !important;
    color: var(--slate-500) !important;
}
</style>
"""


@st.cache_resource
def _cached_client(version: int) -> SISClient:
    """version is part of the cache key — bump MODULE_VERSION to invalidate stale clients."""
    return SISClient()


def _client_api_ok(client: SISClient) -> bool:
    """Reject cached instances bound to older SISClient method definitions."""
    import inspect

    checks = {
        "collect_schools_for_markaz_type": {
            "markazes",
            "markaz_type",
            "emis_filter",
            "school_cache",
            "district_id",
            "tehsil_id",
            "max_workers",
            "max_attempts",
            "on_progress",
        },
        "aggregate_sanctioned_posts": {
            "district_id",
            "tehsil_id",
            "schools",
            "max_workers",
            "max_attempts",
            "on_progress",
        },
    }
    for method_name, required in checks.items():
        method = getattr(client, method_name, None)
        class_method = getattr(SISClient, method_name, None)
        if method is None or class_method is None:
            return False
        # Bound method must come from the currently imported SISClient class
        func = getattr(method, "__func__", None)
        if func is not class_method:
            return False
        params = set(inspect.signature(class_method).parameters)
        if not required.issubset(params):
            return False
    return True


def get_client() -> SISClient:
    """
    Always return a SISClient bound to the *current* module class.
    Never reuse a Streamlit-cached instance from a previous import — those keep
    old method bodies (e.g. workers calling on_progress) and cause NoSessionContext.
    """
    try:
        _cached_client.clear()
    except Exception:  # noqa: BLE001
        pass
    return SISClient()


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "districts": list(STATIC_DISTRICTS),
        "tehsils": [],
        "tehsils_by_district": {},
        "markazes": [],
        "schools_cache": {},
        "loaded_districts": True,
        "lists_status": "",
        "posts_df": None,
        "posts_error": None,
        "posts_failures": [],
        "posts_meta": None,
        "nav_section": "Sanctioned Post Data",
        "student_applied": False,
        "teacher_applied": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Always keep districts from the static constant (no network).
    st.session_state.districts = list(STATIC_DISTRICTS)
    st.session_state.loaded_districts = True

    for key, value in {
        "flt_district": "",
        "flt_tehsil": "",
        "flt_markaz_type": "",
        "flt_emis": "",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _labels(options: list[tuple[str, str]], empty: str) -> dict[str, str]:
    return {"": empty, **{v: lab for v, lab in options}}


def _values(options: list[tuple[str, str]]) -> list[str]:
    return [""] + [v for v, _ in options]


def markaz_type_counts() -> dict[str, int]:
    counts = {t: 0 for t in MARKAZ_TYPES}
    for _, lab in st.session_state.markazes:
        kind = classify_markaz_type(lab)
        if kind in counts:
            counts[kind] += 1
    return counts


def load_districts(_client: SISClient | None = None) -> None:
    """Populate districts from STATIC_DISTRICTS — never hits the network."""
    st.session_state.districts = list(STATIC_DISTRICTS)
    st.session_state.loaded_districts = True


def _fetch_tehsils_api(client: SISClient, district_id: str) -> list[tuple[str, str]]:
    tehsils = client.get_tehsils(district_id)
    st.session_state.tehsils_by_district[district_id] = tehsils
    save_tehsils_disk_cache(district_id, tehsils)
    return tehsils


def load_tehsils_for_district(
    client: SISClient,
    district_id: str,
    *,
    force_refresh: bool = False,
) -> list[tuple[str, str]]:
    """Session cache → disk cache → API (CSRF only on API miss)."""
    if not district_id:
        return []

    if not force_refresh:
        cached = st.session_state.tehsils_by_district.get(district_id)
        if cached is not None:
            return cached
        disk = load_tehsils_disk_cache(district_id)
        if disk is not None:
            st.session_state.tehsils_by_district[district_id] = disk
            return disk

    return _fetch_tehsils_api(client, district_id)


def on_district_change() -> None:
    client = get_client()
    district_id = st.session_state.flt_district
    st.session_state.markazes = []
    st.session_state.schools_cache = {}
    st.session_state.flt_tehsil = ""
    st.session_state.flt_markaz_type = ""
    st.session_state.posts_df = None
    st.session_state.posts_error = None
    st.session_state.posts_meta = None
    st.session_state.lists_status = ""
    if district_id:
        st.session_state.tehsils = load_tehsils_for_district(client, district_id)
    else:
        st.session_state.tehsils = []


def on_tehsil_change() -> None:
    client = get_client()
    tehsil_id = st.session_state.flt_tehsil
    st.session_state.markazes = []
    st.session_state.schools_cache = {}
    st.session_state.flt_markaz_type = ""
    st.session_state.posts_df = None
    st.session_state.posts_error = None
    st.session_state.posts_meta = None
    if tehsil_id:
        st.session_state.markazes = client.get_markazes(tehsil_id)


def refresh_location_lists() -> None:
    """Refresh tehsils for the current district only (not markaz/schools/posts)."""
    client = get_client()
    district_id = st.session_state.flt_district
    # Reload static districts (noop network)
    load_districts(client)

    if not district_id:
        st.session_state.lists_status = "Select a district first, then Refresh lists."
        return

    # Invalidate caches for this district, then refetch
    st.session_state.tehsils_by_district.pop(district_id, None)
    clear_tehsil_disk_cache(district_id)
    with st.spinner("Refreshing tehsils from SIS…"):
        tehsils = load_tehsils_for_district(
            client, district_id, force_refresh=True
        )
    st.session_state.tehsils = tehsils

    # Keep current tehsil if still present; otherwise clear downstream selection
    current = st.session_state.flt_tehsil
    valid_ids = {tid for tid, _ in tehsils}
    if current and current not in valid_ids:
        st.session_state.flt_tehsil = ""
        st.session_state.flt_markaz_type = ""
        st.session_state.markazes = []
        st.session_state.schools_cache = {}

    st.session_state.lists_status = (
        f"Refreshed {len(tehsils)} tehsils for the selected district."
    )


def current_selection() -> dict:
    return {
        "district_id": st.session_state.flt_district,
        "tehsil_id": st.session_state.flt_tehsil,
        "markaz_type": st.session_state.flt_markaz_type,
        "emis_code": (st.session_state.flt_emis or "").strip(),
    }


def render_chrome() -> None:
    st.markdown(
        """
        <div class="app-chrome">
          <div class="app-chrome-brand">
            <div class="app-chrome-mark">SIS</div>
            <div>
              <p class="app-chrome-title">PESRP SIS Dashboard</p>
              <p class="app-chrome-sub">Punjab Education Sector Reform Programme · School Information System</p>
            </div>
          </div>
          <div class="app-status">
            <span class="app-status-dot"></span>
            Live · sis.pesrp.edu.pk
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
              <p class="sidebar-brand-name">SIS Console</p>
              <p class="sidebar-brand-tag">Location · Filters · Reports</p>
            </div>
            <p class="nav-label">Modules</p>
            """,
            unsafe_allow_html=True,
        )
        section = st.radio(
            "Section",
            ["Student Data", "Teacher / Staff Data", "Sanctioned Post Data"],
            key="nav_section",
            label_visibility="collapsed",
        )
        st.markdown(
            """
            <div style="margin-top:1.5rem;padding:0.5rem 0.35rem;border-top:1px solid #1e293b;">
              <p style="color:#64748b;font-size:0.72rem;margin:0;">
                Filters: District → Tehsil → Markaz type (Male / Female / Secondary Wing)
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    return section


def render_filter_bar(client: SISClient) -> bool:
    """District → Tehsil → Markaz type → optional EMIS → Apply (+ Refresh lists)."""
    load_districts(client)

    district_labels = _labels(st.session_state.districts, "All Districts")
    tehsil_labels = _labels(st.session_state.tehsils, "All Tehsils")
    counts = markaz_type_counts()

    def markaz_type_label(value: str) -> str:
        if not value:
            return "Select markaz type"
        n = counts.get(value, 0)
        return f"{value} ({n} markaz{'es' if n != 1 else ''})"

    with st.container(border=True):
        st.markdown(
            '<p class="toolbar-title">Location filters</p>',
            unsafe_allow_html=True,
        )
        if st.session_state.flt_tehsil and st.session_state.markazes:
            st.markdown(
                f'<p class="toolbar-hint">Loaded {len(st.session_state.markazes)} markazes · '
                f"Male {counts['Male']} · Female {counts['Female']} · "
                f"Secondary Wing {counts['Secondary Wing']}</p>",
                unsafe_allow_html=True,
            )

        c1, c2, c3, c4, c5, c6 = st.columns([1.15, 1.15, 1.35, 1.0, 0.85, 0.75])

        with c1:
            st.selectbox(
                "District",
                options=_values(st.session_state.districts),
                format_func=lambda v: district_labels.get(v, v),
                key="flt_district",
                on_change=on_district_change,
            )
        with c2:
            st.selectbox(
                "Tehsil",
                options=_values(st.session_state.tehsils),
                format_func=lambda v: tehsil_labels.get(v, v),
                key="flt_tehsil",
                on_change=on_tehsil_change,
                disabled=not st.session_state.flt_district,
            )
        with c3:
            st.selectbox(
                "Markaz type",
                options=["", *MARKAZ_TYPES],
                format_func=markaz_type_label,
                key="flt_markaz_type",
                disabled=not st.session_state.flt_tehsil,
            )
        with c4:
            st.text_input(
                "EMIS Code (optional)",
                placeholder="Filter one school",
                key="flt_emis",
            )
        with c5:
            st.markdown(
                "<div style='height:1.55rem'></div>", unsafe_allow_html=True
            )
            st.button(
                "Refresh lists",
                use_container_width=True,
                help="Reload tehsils for the selected district from SIS. "
                "Does not refresh markazes, schools, or posts.",
                on_click=refresh_location_lists,
            )
        with c6:
            st.markdown(
                "<div style='height:1.55rem'></div>", unsafe_allow_html=True
            )
            apply_clicked = st.button(
                "Apply", type="primary", use_container_width=True
            )

        if st.session_state.get("lists_status"):
            st.caption(st.session_state.lists_status)

    return apply_clicked


def render_empty_state(title: str, detail: str) -> None:
    st.markdown(
        f"""
        <div class="empty-panel">
          <div class="empty-panel-icon">◇</div>
          <h3>{html.escape(title)}</h3>
          <p>{html.escape(detail)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_head(title: str, subtitle: str, pending: bool = False) -> None:
    badge = (
        '<span class="placeholder-badge">API pending</span>' if pending else ""
    )
    st.markdown(
        f"""
        <div class="page-head">
          <h2>{html.escape(title)}{badge}</h2>
          <p>{html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def wide_table_html(df: pd.DataFrame) -> str:
    """Excel-like multi-level header grid."""
    if df.empty:
        return "<p>No rows.</p>"

    if not isinstance(df.columns, pd.MultiIndex):
        return df.to_html(index=False, classes="sis-grid")

    tops = df.columns.get_level_values(0).tolist()
    subs = df.columns.get_level_values(1).tolist()

    head1: list[str] = []
    head2: list[str] = []
    i = 0
    while i < len(tops):
        top = tops[i]
        if top in ("EMIS Code", "School Name"):
            extra = " emis-h" if top == "EMIS Code" else " school-h"
            head1.append(
                f'<th rowspan="2" class="id-col{extra}">{html.escape(str(top))}</th>'
            )
            i += 1
            continue
        span = 1
        while i + span < len(tops) and tops[i + span] == top:
            span += 1
        head1.append(
            f'<th colspan="{span}" class="post-group">{html.escape(str(top))}</th>'
        )
        for k in range(span):
            head2.append(
                f'<th class="metric-col">{html.escape(str(subs[i + k]))}</th>'
            )
        i += span

    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for col_i, top in enumerate(tops):
            val = row.iloc[col_i]
            text = "" if pd.isna(val) else str(val)
            if top == "EMIS Code":
                cls = "id-col emis"
            elif top == "School Name":
                cls = "id-col school"
            else:
                cls = "num-col"
            cells.append(f'<td class="{cls}">{html.escape(text)}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return f"""
    <div class="sis-grid-wrap">
      <table class="sis-grid">
        <thead>
          <tr>{''.join(head1)}</tr>
          <tr>{''.join(head2)}</tr>
        </thead>
        <tbody>
          {''.join(body_rows)}
        </tbody>
      </table>
    </div>
    """


GRID_CSS = """
<style>
  html, body {
    margin: 0;
    font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
    background: transparent;
  }
  .sis-grid-wrap {
    overflow: auto;
    max-height: 620px;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    background: #fff;
  }
  table.sis-grid {
    border-collapse: separate;
    border-spacing: 0;
    width: max-content;
    min-width: 100%;
    font-size: 12.5px;
  }
  table.sis-grid th, table.sis-grid td {
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
    padding: 6px 10px;
    white-space: nowrap;
  }
  table.sis-grid thead th {
    position: sticky;
    top: 0;
    z-index: 2;
    background: #0f766e;
    color: #fff;
    font-weight: 600;
    text-align: center;
  }
  table.sis-grid thead tr:nth-child(2) th {
    top: 28px;
    background: #134e4a;
    font-weight: 500;
    font-size: 11px;
  }
  table.sis-grid th.post-group {
    background: #0d9488;
    letter-spacing: 0.01em;
  }
  table.sis-grid th.id-col {
    background: #115e59;
    text-align: left;
  }
  table.sis-grid td.id-col {
    background: #f8fafc;
    font-weight: 500;
    color: #1e293b;
    position: sticky;
    z-index: 1;
  }
  table.sis-grid td.emis {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11.5px;
    left: 0;
    min-width: 96px;
    z-index: 3;
  }
  table.sis-grid td.school {
    left: 96px;
    min-width: 180px;
    z-index: 2;
  }
  table.sis-grid thead th.id-col.emis-h { left: 0; z-index: 4; }
  table.sis-grid thead th.id-col.school-h { left: 96px; z-index: 4; }
  table.sis-grid td.num-col {
    text-align: center;
    font-variant-numeric: tabular-nums;
    color: #334155;
  }
  table.sis-grid tbody tr:hover td { background: #f0fdfa; }
  table.sis-grid tbody tr:hover td.id-col { background: #ccfbf1; }
</style>
"""


def render_wide_table(df: pd.DataFrame) -> None:
    markup = GRID_CSS + wide_table_html(df)
    height = min(660, 90 + 28 * (len(df) + 2))
    components.html(markup, height=height, scrolling=True)


def render_student_section(selection: dict, apply_clicked: bool) -> None:
    render_page_head(
        "Student Data",
        "Enrollment and student records for the selected markaz type.",
        pending=True,
    )
    if apply_clicked:
        st.session_state.student_applied = True

    if not st.session_state.student_applied and not apply_clicked:
        render_empty_state(
            "Select filters and Apply",
            "Choose District → Tehsil → Markaz type, then Apply.",
        )
        return

    st.info("Student data endpoints were not provided yet.")
    st.json(selection)


def render_teacher_section(selection: dict, apply_clicked: bool) -> None:
    render_page_head(
        "Teacher / Staff Data",
        "Teaching and non-teaching staff roster for the selected markaz type.",
        pending=True,
    )
    if apply_clicked:
        st.session_state.teacher_applied = True

    if not st.session_state.teacher_applied and not apply_clicked:
        render_empty_state(
            "Select filters and Apply",
            "Choose District → Tehsil → Markaz type, then Apply.",
        )
        return

    st.info("Teacher/staff data endpoints were not provided yet.")
    st.json(selection)


def _run_aggregation(client: SISClient, selection: dict) -> None:
    markaz_type = selection["markaz_type"]
    progress = st.progress(0.0, text="Starting…")
    status = st.empty()
    st.session_state.posts_error = None  # clear prior error; keep prior posts_df until success

    # Phase weights: schools 0–15%, posts 15–95%, build 95–100%
    phase = {"name": "schools", "start": 0.0, "end": 0.15}

    def on_progress(message: str, current: int, total: int) -> None:
        """Main-thread only — never invoked from worker threads."""
        total = max(total, 1)
        frac = phase["start"] + (phase["end"] - phase["start"]) * (
            current / total
        )
        try:
            progress.progress(min(max(frac, 0.0), 1.0), text=message)
            status.caption(message)
        except Exception:  # noqa: BLE001 — e.g. NoSessionContext if mis-wired
            pass

    try:
        phase.update(name="schools", start=0.0, end=0.15)
        schools = client.collect_schools_for_markaz_type(
            markazes=st.session_state.markazes,
            markaz_type=markaz_type,
            emis_filter=selection["emis_code"],
            school_cache=st.session_state.schools_cache,
            district_id=selection["district_id"],
            tehsil_id=selection["tehsil_id"],
            max_workers=DEFAULT_WORKERS,
            max_attempts=MAX_ATTEMPTS,
            on_progress=on_progress,
        )
        if not schools:
            st.session_state.posts_df = pd.DataFrame()
            st.session_state.posts_failures = []
            st.session_state.posts_meta = {
                **selection,
                "school_count": 0,
                "markaz_count": 0,
            }
            return

        markaz_ids = {s["markaz_id"] for s in schools}
        status.caption(
            f"Found {len(schools)} schools across {len(markaz_ids)} "
            f"{markaz_type} markazes — fetching sanctioned posts "
            f"({DEFAULT_WORKERS} workers, {MAX_ATTEMPTS} attempts)…"
        )

        phase.update(name="posts", start=0.15, end=0.95)
        df, failures = client.aggregate_sanctioned_posts(
            district_id=selection["district_id"],
            tehsil_id=selection["tehsil_id"],
            schools=schools,
            max_workers=DEFAULT_WORKERS,
            max_attempts=MAX_ATTEMPTS,
            on_progress=on_progress,
        )
        phase.update(name="build", start=0.95, end=1.0)
        on_progress("Done.", 1, 1)

        st.session_state.posts_df = df
        st.session_state.posts_error = None
        st.session_state.posts_failures = failures
        st.session_state.posts_meta = {
            **selection,
            "school_count": len(schools),
            "markaz_count": len(markaz_ids),
            "workers": DEFAULT_WORKERS,
            "max_attempts": MAX_ATTEMPTS,
        }
    except Exception as exc:  # noqa: BLE001
        # Keep any previous posts_df — never wipe to empty CTA on failure
        st.session_state.posts_error = f"{exc}\n\n{traceback.format_exc()}"
        st.session_state.posts_failures = []
    finally:
        progress.empty()
        status.empty()


def sum_wide_post_metrics(df: pd.DataFrame) -> dict[str, int]:
    """Sum Vacant / Filled / Total across all post-type columns in the wide table."""
    totals = {"Vacant": 0, "Filled": 0, "Total": 0}
    if df is None or df.empty:
        return totals

    def _sum_cols(cols: list) -> int:
        if not cols:
            return 0
        values = pd.to_numeric(
            df.loc[:, cols].to_numpy().ravel(), errors="coerce"
        )
        return int(pd.Series(values).fillna(0).sum())

    if isinstance(df.columns, pd.MultiIndex):
        for metric in ("Vacant", "Filled", "Total"):
            cols = [
                c
                for c in df.columns
                if isinstance(c, tuple)
                and len(c) > 1
                and c[1] == metric
                and c[0] not in ("EMIS Code", "School Name")
            ]
            totals[metric] = _sum_cols(cols)
        return totals

    for metric in ("Vacant", "Filled", "Total"):
        cols = [
            c
            for c in df.columns
            if str(c) not in ("EMIS Code", "School Name")
            and (str(c).endswith(f" - {metric}") or str(c) == metric)
        ]
        totals[metric] = _sum_cols(cols)
    return totals


def render_posts_section(
    client: SISClient, selection: dict, apply_clicked: bool
) -> None:
    render_page_head(
        "Sanctioned Post Data",
        "Aggregates all schools in Male / Female / Secondary Wing markazes into one wide Excel-style grid.",
    )

    if apply_clicked:
        if not selection["tehsil_id"]:
            st.warning("Select a District and Tehsil first.")
        elif not selection["markaz_type"]:
            st.warning("Select a Markaz type (Male, Female, or Secondary Wing).")
        else:
            _run_aggregation(client, selection)

    if st.session_state.posts_error:
        st.error(
            "Failed to load sanctioned posts — previous results (if any) are kept.\n\n"
            f"{st.session_state.posts_error}"
        )

    df = st.session_state.posts_df
    # Empty CTA only when there is nothing to show and no error either
    if df is None and not st.session_state.posts_error:
        render_empty_state(
            "Select markaz type and Apply",
            "Choose District → Tehsil → Male / Female / Secondary Wing, then Apply to build the wide posts table.",
        )
        return

    if df is None:
        return

    if df.empty:
        st.warning(
            "No schools (or no post rows) found for this markaz type selection."
        )
        return

    meta = st.session_state.posts_meta or {}
    post_types = [
        c[0]
        for c in df.columns.to_list()
        if isinstance(c, tuple)
        and c[0] not in ("EMIS Code", "School Name")
        and c[1] == "Vacant"
    ]
    post_sums = sum_wide_post_metrics(df)

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    r1c1.metric("Schools", meta.get("school_count", len(df)))
    r1c2.metric("Markazes", meta.get("markaz_count", "—"))
    r1c3.metric("Post types", len(post_types))
    r1c4.metric("Markaz type", meta.get("markaz_type", "—"))

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    r2c1.metric("Total posts", post_sums["Total"])
    r2c2.metric("Total filled", post_sums["Filled"])
    r2c3.metric("Total vacant", post_sums["Vacant"])
    r2c4.metric(
        "Fill rate",
        f"{(100 * post_sums['Filled'] / post_sums['Total']):.0f}%"
        if post_sums["Total"]
        else "—",
    )

    failures = st.session_state.get("posts_failures") or []
    if failures:
        st.warning(
            f"{len(failures)} school(s) still failed after "
            f"{meta.get('max_attempts', MAX_ATTEMPTS)} attempts × "
            f"final retry pass. Rows are kept marked "
            f"[FETCH FAILED]. Details: "
            + "; ".join(
                f"{f.get('label') or f.get('emis')}: {f.get('error')}"
                for f in failures[:8]
            )
            + ("…" if len(failures) > 8 else "")
        )

    tehsil_labels = _labels(st.session_state.tehsils, "")
    tehsil_name = tehsil_labels.get(meta.get("tehsil_id", ""), "")
    st.markdown(
        f"""
        <div class="results-bar">
          <span class="results-bar-title">Wide posts grid</span>
          <span class="results-bar-meta">{html.escape(str(tehsil_name))} · {html.escape(str(meta.get('markaz_type', '')))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_wide_table(df)

    flat = flatten_wide_columns(df)
    st.download_button(
        "Download CSV",
        data=flat.to_csv(index=False).encode("utf-8"),
        file_name=f"sanctioned_posts_{meta.get('markaz_type', 'all').lower().replace(' ', '_')}.csv",
        mime="text/csv",
    )


def main() -> None:
    _init_state()
    st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)
    client = get_client()

    section = render_sidebar()
    render_chrome()
    apply_clicked = render_filter_bar(client)
    selection = current_selection()

    if section == "Student Data":
        render_student_section(selection, apply_clicked)
    elif section == "Teacher / Staff Data":
        render_teacher_section(selection, apply_clicked)
    else:
        render_posts_section(client, selection, apply_clicked)


if __name__ == "__main__":
    main()
