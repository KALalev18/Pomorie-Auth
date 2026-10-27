"""City dashboard: where issues are, how fast authorities act, what fines and rewards cost.

Connects as the read-only ``dashboard`` role, which can read the ``analytics`` marts and
nothing else (no identity, raw or operational tables).

    streamlit run src/pomorie/dashboard/app.py
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]
import psycopg
import streamlit as st

from pomorie.config import get_settings

# Reference data-viz palette (validated for CVD separation in light and dark mode).
SERIES_1 = "#2a78d6"  # blue: the single-series and sequential hue
SERIES_2 = "#eb6834"  # orange: second series only
SEQUENTIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#104281"]
CRITICAL = "#d03b3b"

CATEGORY_LABELS = {
    "illegal_parking": "Illegal parking",
    "littering": "Littering",
    "illegal_dumping": "Illegal dumping",
    "broken_infrastructure": "Broken infrastructure",
    "street_lighting": "Street lighting",
    "noise": "Noise",
    "damaged_greenery": "Damaged greenery",
    "abandoned_vehicle": "Abandoned vehicle",
}
AUTHORITY_LABELS = {
    "traffic_police": "Traffic police",
    "police": "Police",
    "municipality_cleanliness": "Municipality: cleanliness",
    "municipality_infrastructure": "Municipality: infrastructure",
    "municipality_environment": "Municipality: environment",
}


@st.cache_data(ttl=300)
def query(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with psycopg.connect(get_settings().dashboard_dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [c.name for c in cur.description or []]
        return pd.DataFrame(cur.fetchall(), columns=columns)


@st.cache_data(ttl=300)
def query_one(sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    with psycopg.connect(get_settings().dashboard_dsn) as conn:
        return conn.execute(sql, params).fetchone() or ()


def style(fig: go.Figure, height: int = 320) -> go.Figure:
    """Recessive axes and grid, no chart junk; text stays in theme ink, not series colour."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        showlegend=False,
        hoverlabel={"font_size": 13},
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", title=None, zeroline=False)
    fig.update_traces(marker_line_width=0, selector={"type": "bar"})
    return fig


def period_filter(alias: str = "") -> str:
    """SQL filter for the selected period and categories (params: start, end, categories)."""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}date_key BETWEEN %s AND %s AND {prefix}category = ANY(%s)"


def tile(column: Any, label: str, value: str, help_text: str) -> None:
    column.metric(label, value, help=help_text)


def main() -> None:
    st.set_page_config(page_title="Pomorie Reports", page_icon=":round_pushpin:", layout="wide")
    st.title("Pomorie civic reports")
    st.caption(
        "Synthetic data only. Authorities and rewards are simulated; nothing is sent to real "
        "police or municipality systems. Map data © OpenStreetMap contributors."
    )

    first, last = query_one("SELECT min(date_key), max(date_key) FROM analytics.fct_cases")
    if first is None:
        st.info("No data yet. Seed it with: docker compose run --rm demo")
        return

    # Filters: one row above the charts.
    left, right = st.columns([1, 2])
    picked = left.date_input("Reported between", (first, last), min_value=first, max_value=last)
    start, end = picked if isinstance(picked, tuple) and len(picked) == 2 else (first, last)
    categories = right.multiselect(
        "Categories",
        options=list(CATEGORY_LABELS),
        default=list(CATEGORY_LABELS),
        format_func=lambda c: CATEGORY_LABELS[c],
    )
    if not categories:
        st.warning("Pick at least one category.")
        return
    params = (start, end, categories)
    where = period_filter()

    cases, reports, median_hours, breach_rate, fines_paid_eur = query_one(
        f"""
        SELECT count(*) AS cases,
               sum(report_count) AS reports,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY hours_to_decision) AS median_hours,
               avg(sla_breached::int) AS breach_rate,
               sum(fine_cents) FILTER (WHERE fine_paid) / 100.0 AS fines_paid_eur
        FROM analytics.fct_cases WHERE {where}
        """,
        params,
    )
    (rewards,) = query_one(
        f"""
        SELECT coalesce(sum(l.amount_cents), 0) / 100.0 AS eur
        FROM analytics.fct_reward_ledger l JOIN analytics.fct_cases c USING (case_id)
        WHERE l.txn_kind = 'reward_accrual' AND l.account_kind = 'expense'
          AND {period_filter("c")}
        """,
        params,
    )

    cols = st.columns(6)
    tile(cols[0], "Reports", f"{int(reports or 0):,}", "Accepted reports in the period.")
    tile(cols[1], "Cases", f"{int(cases):,}", "Reports merged by deduplication into issues.")
    tile(
        cols[2],
        "Median time to decision",
        f"{float(median_hours or 0):.1f} h",
        "From routing to the authority's first decision.",
    )
    tile(
        cols[3],
        "SLA breached",
        f"{float(breach_rate or 0):.0%}",
        "Cases decided after their category's deadline.",
    )
    tile(cols[4], "Fines paid", f"€{float(fines_paid_eur or 0):,.0f}", "Simulated fines, paid.")
    tile(
        cols[5],
        "Rewards accrued",
        f"€{float(rewards):,.0f}",
        "Simulated reporter rewards (double-entry ledger).",
    )

    st.subheader("Where issues are reported")
    points = query(f"SELECT lat, lon, category FROM analytics.fct_reports WHERE {where}", params)
    heat = px.density_map(
        points,
        lat="lat",
        lon="lon",
        radius=5,
        zoom=11,
        center={"lat": 42.60, "lon": 27.59},
        opacity=0.75,
        map_style="open-street-map",
        color_continuous_scale=SEQUENTIAL,
    )
    heat.update_layout(
        height=460, margin={"l": 0, "r": 0, "t": 0, "b": 0}, coloraxis_showscale=False
    )
    heat.update_traces(hovertemplate="Report density<extra></extra>")
    st.plotly_chart(heat, use_container_width=True)

    a, b = st.columns(2)
    with a:
        st.subheader("Cases by category")
        by_cat = query(
            f"SELECT category, count(*) AS cases FROM analytics.fct_cases WHERE {where}"
            " GROUP BY 1 ORDER BY 2",
            params,
        )
        by_cat["label"] = by_cat["category"].map(CATEGORY_LABELS)
        fig = px.bar(by_cat, x="cases", y="label", orientation="h", text="cases")
        fig.update_traces(
            marker_color=SERIES_1,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x:,} cases<extra></extra>",
        )
        st.plotly_chart(style(fig), use_container_width=True)

    with b:
        st.subheader("SLA breaches by authority")
        sla = query(
            f"""
            SELECT authority, avg(sla_breached::int) AS breach_rate,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY hours_to_decision) AS median_h,
                   count(*) AS cases
            FROM analytics.fct_cases WHERE {where} GROUP BY 1 ORDER BY 2
            """,
            params,
        )
        sla["label"] = sla["authority"].map(AUTHORITY_LABELS)
        fig = px.bar(
            sla,
            x="breach_rate",
            y="label",
            orientation="h",
            text="breach_rate",
            custom_data=["median_h", "cases"],
        )
        fig.update_traces(
            marker_color=SERIES_1,
            texttemplate="%{x:.0%}",
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>%{x:.0%} breached · median %{customdata[0]:.1f} h · "
            "%{customdata[1]:,} cases<extra></extra>",
        )
        fig.update_xaxes(tickformat=".0%")
        st.plotly_chart(style(fig), use_container_width=True)

    st.subheader("Reports per week")
    st.caption("Complete ISO weeks only; a partial week would read as a drop in reports.")
    weekly = query(
        f"SELECT date_trunc('week', date_key)::date AS week, count(*) AS reports"
        f" FROM analytics.fct_reports WHERE {where} GROUP BY 1"
        " HAVING date_trunc('week', min(date_key)) >= %s::date"
        " AND date_trunc('week', min(date_key)) + interval '6 days' <= %s::date ORDER BY 1",
        (*params, start, end),
    )
    fig = px.line(weekly, x="week", y="reports", markers=True)
    fig.update_traces(
        line={"color": SERIES_1, "width": 2},
        marker={"size": 8},
        hovertemplate="Week of %{x|%d %b}: %{y:,} reports<extra></extra>",
    )
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(style(fig, 280), use_container_width=True)

    c, d = st.columns(2)
    with c:
        st.subheader("Fines paid and rewards accrued per month")
        money = query(
            f"""
            WITH fines AS (
                SELECT date_trunc('month', f.paid_at)::date AS month,
                       sum(f.amount_cents) / 100.0 AS eur
                FROM analytics.fct_fines f JOIN analytics.fct_cases c USING (case_id)
                WHERE f.is_paid AND {period_filter("c")}
                GROUP BY 1),
            rewards AS (
                SELECT date_trunc('month', l.created_at)::date AS month,
                       sum(l.amount_cents) / 100.0 AS eur
                FROM analytics.fct_reward_ledger l JOIN analytics.fct_cases c USING (case_id)
                WHERE l.txn_kind = 'reward_accrual' AND l.account_kind = 'expense'
                  AND {period_filter("c")}
                GROUP BY 1)
            SELECT month, 'Fines paid' AS measure, eur FROM fines
            UNION ALL SELECT month, 'Rewards accrued', eur FROM rewards
            ORDER BY 1
            """,
            params + params,
        )
        fig = px.bar(
            money,
            x="month",
            y="eur",
            color="measure",
            barmode="group",
            color_discrete_sequence=[SERIES_1, SERIES_2],
        )
        fig.update_traces(hovertemplate="%{x|%B %Y}: €%{y:,.0f}<extra>%{fullData.name}</extra>")
        fig.update_xaxes(tickformat="%b %Y", dtick="M1")
        fig = style(fig)
        fig.update_layout(showlegend=True, legend={"orientation": "h", "y": 1.08, "title": None})
        st.plotly_chart(fig, use_container_width=True)

    with d:
        st.subheader("Repeat hotspots")
        st.caption("Streets with the most cases in the period.")
        hotspots = query(
            f"""
            SELECT coalesce(street, '(no named street)') AS street, settlement,
                   count(*) AS cases, sum(report_count) AS reports,
                   mode() WITHIN GROUP (ORDER BY category) AS top_category
            FROM analytics.fct_cases WHERE {where} AND street IS NOT NULL
            GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10
            """,
            params,
        )
        hotspots["top_category"] = hotspots["top_category"].map(CATEGORY_LABELS)
        st.dataframe(hotspots, hide_index=True, use_container_width=True)

    st.subheader("Input quality")
    st.caption("Events the pipeline rejected, by stage and reason (all time).")
    dq = query(
        "SELECT stage, primary_reason AS reason, sum(events) AS events"
        " FROM analytics.dq_dead_letter_daily GROUP BY 1, 2 ORDER BY 3 DESC"
    )
    st.dataframe(dq, hide_index=True, use_container_width=True)

    with st.expander("Case data (table view)"):
        st.dataframe(
            query(f"SELECT * FROM analytics.fct_cases WHERE {where} LIMIT 2000", params),
            hide_index=True,
            use_container_width=True,
        )
    st.caption(f"Data through {last:%d %b %Y}. Built {date.today():%d %b %Y}.")


main()
