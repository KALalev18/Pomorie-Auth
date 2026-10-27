"""FastAPI service.

The API does as little as possible synchronously: validate, pseudonymise, store photos,
publish the event, answer 202. Everything else happens in the stream processor, so a slow
database or a burst of reports never makes the app hang.

    uvicorn pomorie.api.app:app
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from pomorie import kafka, photos
from pomorie.config import get_settings
from pomorie.contracts import REPORT_SUBMITTED, categories, validate
from pomorie.db import connect
from pomorie.privacy import plate_hash


class ReportIn(BaseModel):
    reporter_id: uuid.UUID
    category: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    occurred_at: datetime | None = None
    description: str | None = Field(default=None, max_length=1000)
    plate: str | None = Field(default=None, max_length=16)
    app_version: str | None = Field(default=None, max_length=32)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in categories():
            raise ValueError(f"unknown category, expected one of {categories()}")
        return value


class ReporterIn(BaseModel):
    display_name: str = Field(max_length=80)
    email: EmailStr


class ReviewIn(BaseModel):
    decision: Literal["approved", "rejected"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    kafka.ensure_topics()
    photos.ensure_bucket()
    app.state.producer = kafka.make_producer()
    yield
    app.state.producer.flush(10)


app = FastAPI(title="Pomorie Reports API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def db() -> Any:
    with connect(autocommit=True) as conn:
        yield conn


DB = Annotated[psycopg.Connection, Depends(db)]


def build_event(
    report: ReportIn, event_id: uuid.UUID, photo_keys: list[str], platform: str
) -> dict[str, Any]:
    now = datetime.now(UTC)
    event: dict[str, Any] = {
        "schema": "report.submitted/1",
        "event_id": str(event_id),
        "occurred_at": (report.occurred_at or now).isoformat(),
        "received_at": now.isoformat(),
        "reporter_id": str(report.reporter_id),
        "category": report.category,
        "location": {"lat": report.lat, "lon": report.lon},
        "client": {"platform": platform},
    }
    if report.accuracy_m is not None:
        event["location"]["accuracy_m"] = report.accuracy_m
    if report.description:
        event["description"] = report.description
    if photo_keys:
        event["photo_keys"] = photo_keys
    if report.plate and (hashed := plate_hash(report.plate)):
        event["plate_hash"] = hashed
    if report.app_version:
        event["client"]["app_version"] = report.app_version
    return event


@app.post("/reports", status_code=status.HTTP_202_ACCEPTED)
async def submit_report(
    report: Annotated[str, Form(description="ReportIn as JSON")],
    photo_files: Annotated[list[UploadFile] | None, File(alias="photos")] = None,
    idempotency_key: Annotated[uuid.UUID | None, Header()] = None,
) -> dict[str, str]:
    try:
        parsed = ReportIn.model_validate_json(report)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, json.loads(exc.json())) from exc

    # A retried request with the same Idempotency-Key produces the same event_id, and the
    # pipeline ignores an event_id it has already stored.
    event_id = idempotency_key or uuid.uuid4()
    keys = []
    for upload in (photo_files or [])[:5]:
        try:
            keys.append(await run_in_threadpool(photos.store_photo, event_id, await upload.read()))
        except photos.InvalidPhoto as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    event = build_event(parsed, event_id, keys, platform="web")
    if errors := validate(REPORT_SUBMITTED, event):  # producer-side contract check
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, errors)
    await run_in_threadpool(
        kafka.publish, app.state.producer, get_settings().reports_topic, parsed.category, event
    )
    return {"event_id": str(event_id), "status": "accepted"}


@app.get("/reports/{event_id}")
def report_status(event_id: uuid.UUID, conn: DB) -> dict[str, Any]:
    """What the reporter sees: where their report is, without anyone else's data."""
    row = conn.execute(
        "SELECT r.case_id, c.status, c.authority, c.report_count, c.sla_due_at, c.needs_review"
        " FROM ops.reports r JOIN ops.cases c USING (case_id) WHERE r.report_id = %s",
        [event_id],
    ).fetchone()
    if row:
        case_id, case_status, authority, count, sla_due_at, needs_review = row
        return {
            "event_id": str(event_id),
            "case_id": str(case_id),
            "status": case_status,
            "authority": authority,
            "reports_on_case": count,
            "sla_due_at": sla_due_at.isoformat(),
            "under_review": needs_review,
        }
    rejected = conn.execute(
        "SELECT reasons FROM raw.dead_letter WHERE event_id = %s", [event_id]
    ).fetchone()
    if rejected:
        return {"event_id": str(event_id), "status": "rejected", "reasons": rejected[0]}
    return {"event_id": str(event_id), "status": "processing"}


@app.post("/reporters", status_code=status.HTTP_201_CREATED)
def register_reporter(reporter: ReporterIn, conn: DB) -> dict[str, str]:
    reporter_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO identity.reporters (reporter_id, display_name, email) VALUES (%s, %s, %s)",
        [reporter_id, reporter.display_name, reporter.email],
    )
    return {"reporter_id": str(reporter_id)}


@app.post("/reporters/{reporter_id}/erasure", status_code=status.HTTP_202_ACCEPTED)
def request_erasure(reporter_id: uuid.UUID, conn: DB) -> dict[str, Any]:
    """GDPR Art. 17. Processed by the erasure job, which propagates it through the pipeline."""
    (request_id,) = conn.execute(
        "INSERT INTO identity.erasure_requests (reporter_id) VALUES (%s) RETURNING request_id",
        [reporter_id],
    ).fetchone() or (None,)
    return {"request_id": request_id, "status": "queued"}


def require_reviewer(x_reviewer_token: Annotated[str, Header()]) -> None:
    if x_reviewer_token != get_settings().reviewer_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "reviewer token required")


@app.get("/review/cases", dependencies=[Depends(require_reviewer)])
def review_queue(conn: DB) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT case_id, category, review_reasons, first_reported_at FROM ops.cases"
        " WHERE needs_review AND review_decision IS NULL ORDER BY first_reported_at LIMIT 100"
    ).fetchall()
    return [
        {"case_id": str(c), "category": cat, "reasons": reasons, "reported_at": at.isoformat()}
        for c, cat, reasons, at in rows
    ]


@app.post("/review/cases/{case_id}", dependencies=[Depends(require_reviewer)])
def review_case(case_id: uuid.UUID, review: ReviewIn, conn: DB) -> dict[str, str]:
    updated = conn.execute(
        "UPDATE ops.cases SET review_decision = %s, reviewed_at = now(), updated_at = now()"
        " WHERE case_id = %s AND needs_review AND review_decision IS NULL",
        [review.decision, case_id],
    ).rowcount
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no pending review for this case")
    return {"case_id": str(case_id), "decision": review.decision}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
