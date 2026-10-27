"""Measure the pipeline against the generator's ground truth (``eval.report_labels``).

Deduplication is scored pairwise, the standard way to evaluate clustering: every pair of
reports is either placed in the same case or not, and either describes the same real
issue or not.

    precision = pairs correctly merged / all pairs merged
    recall    = pairs correctly merged / all pairs that should have been merged

Pair counts come from group sizes (n reports in a group form n(n-1)/2 pairs), so the
query stays linear in the number of reports.

    python -m pomorie.evaluation
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from pomorie.db import connect

DEDUP_SQL = """
WITH labelled AS (
    SELECT r.case_id, l.true_issue_id
    FROM ops.reports r JOIN eval.report_labels l ON l.event_id = r.report_id
),
pairs AS (
    SELECT
        (SELECT coalesce(sum(n * (n - 1) / 2), 0) FROM
            (SELECT count(*) AS n FROM labelled GROUP BY case_id, true_issue_id) g) AS tp,
        (SELECT coalesce(sum(n * (n - 1) / 2), 0) FROM
            (SELECT count(*) AS n FROM labelled GROUP BY case_id) g) AS merged,
        (SELECT coalesce(sum(n * (n - 1) / 2), 0) FROM
            (SELECT count(*) AS n FROM labelled GROUP BY true_issue_id) g) AS should
)
SELECT tp, merged, should,
       (SELECT count(*) FROM labelled) AS reports,
       (SELECT count(DISTINCT case_id) FROM labelled) AS cases,
       (SELECT count(DISTINCT true_issue_id) FROM labelled) AS true_issues
FROM pairs
"""

FRAUD_SQL = """
SELECT
    count(*) FILTER (WHERE cardinality(r.fraud_flags) > 0 AND l.is_abusive),
    count(*) FILTER (WHERE cardinality(r.fraud_flags) > 0),
    count(*) FILTER (WHERE l.is_abusive)
FROM ops.reports r JOIN eval.report_labels l ON l.event_id = r.report_id
"""

VALIDATION_SQL = """
SELECT l.scenario,
       count(*) FILTER (WHERE r.report_id IS NOT NULL) AS accepted,
       count(*) FILTER (WHERE d.event_id IS NOT NULL) AS rejected
FROM eval.report_labels l
LEFT JOIN ops.reports r ON r.report_id = l.event_id
LEFT JOIN raw.dead_letter d ON d.event_id = l.event_id
GROUP BY l.scenario ORDER BY l.scenario
"""


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def evaluate(conn: psycopg.Connection) -> dict[str, Any]:
    tp, merged, should, reports, cases, issues = conn.execute(DEDUP_SQL).fetchone() or (0,) * 6
    flagged_abusive, flagged, abusive = conn.execute(FRAUD_SQL).fetchone() or (0, 0, 0)
    validation = {
        scenario: {"accepted": acc, "rejected": rej}
        for scenario, acc, rej in conn.execute(VALIDATION_SQL).fetchall()
    }
    return {
        "dedup": {
            "reports": reports,
            "cases": cases,
            "true_issues": issues,
            "precision": _ratio(int(tp), int(merged)),
            "recall": _ratio(int(tp), int(should)),
        },
        "fraud_flags": {
            "flagged_reports": flagged,
            "abusive_reports": abusive,
            "precision": _ratio(flagged_abusive, flagged),
            "recall": _ratio(flagged_abusive, abusive),
        },
        "validation_by_scenario": validation,
    }


def main() -> None:
    with connect() as conn:
        print(json.dumps(evaluate(conn), indent=2, default=str))


if __name__ == "__main__":
    main()
