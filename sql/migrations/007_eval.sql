-- Ground truth written by the synthetic generator. The pipeline never reads this schema;
-- only the evaluation scripts do, to measure deduplication and fraud detection.
CREATE TABLE eval.report_labels (
    event_id       uuid PRIMARY KEY,
    true_issue_id  uuid,              -- reports of the same real issue share this id
    scenario       text NOT NULL,     -- normal, duplicate, spam, bad_gps, burst, ...
    is_abusive     boolean NOT NULL DEFAULT false
);
