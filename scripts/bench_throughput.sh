#!/usr/bin/env bash
# Processor throughput: replay the same generated history with N consumers.
#
#   scripts/bench_throughput.sh 1
#   scripts/bench_throughput.sh 4
#
# Needs the compose stack up and a seeded demo (docker compose run --rm demo). It clears
# the processed tables (not the ledger, which is append-only: reset with down -v instead),
# rewinds the consumer group and measures how long the processor takes to land every report.
# The Dagster daemon is paused and the outcomes topic skipped, so scheduled jobs and outcome
# replays (whose cases were just truncated) cannot disturb the measurement.
set -euo pipefail
consumers="${1:-1}"
psql() { docker compose exec -T postgres psql -U pomorie -d pomorie -tAc "$1"; }

expected=$(docker compose exec -T redpanda rpk topic describe reports.submitted.v1 -p \
  | awk 'NR>1 {sum += $NF} END {print sum}')

docker compose stop processor dagster-daemon >/dev/null
psql "TRUNCATE ops.reports, ops.case_status_history, ops.fines, ops.cases,
      raw.report_events, raw.dead_letter CASCADE" >/dev/null
docker compose exec -T redpanda rpk group seek pomorie-processor --to start \
  --topics reports.submitted.v1 >/dev/null
docker compose exec -T redpanda rpk group seek pomorie-processor --to end \
  --topics authority.outcomes.v1 >/dev/null
docker compose up -d --no-deps --scale processor="$consumers" processor >/dev/null

until [ "$(psql "SELECT (SELECT count(*) FROM raw.report_events)
                      + (SELECT count(*) FROM raw.dead_letter
                         WHERE kafka_topic = 'reports.submitted.v1')")" -ge "$expected" ]; do
  sleep 2
done

psql "SELECT '$consumers consumer(s): ' || count(*) || ' reports in '
       || round(extract(epoch FROM max(processed_at) - min(processed_at))::numeric, 1)
       || ' s = ' || round(count(*) / extract(epoch FROM max(processed_at) - min(processed_at))::numeric)
       || ' reports/s, ' || (SELECT count(*) FROM ops.cases) || ' cases'
      FROM ops.reports"
docker compose up -d --no-deps --scale processor=1 processor >/dev/null
docker compose start dagster-daemon >/dev/null
