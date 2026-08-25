from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

_lock = Lock()
_MAX_EVENTS = 80

_state: dict[str, Any] = {
    "running": False,
    "progress": None,
    "last_result": None,
    "error": None,
    "cancel_requested": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_event(progress: dict[str, Any], message: str, *, phase: str | None = None) -> None:
    events = list(progress.get("events") or [])
    events.append(
        {
            "at": _now(),
            "phase": phase or progress.get("phase") or "info",
            "message": message,
        }
    )
    progress["events"] = events[-_MAX_EVENTS:]


def reset_for_crawl(
    locations: list[str], industry: str | None, max_pages: int | None
) -> None:
    with _lock:
        _state["running"] = True
        _state["error"] = None
        _state["cancel_requested"] = False
        progress = {
            "phase": "queued",
            "message": "Crawl queued — starting shortly",
            "why": "Job accepted into sequential queue (one request at a time).",
            "location": None,
            "location_index": 0,
            "locations_total": len(locations),
            "locations": locations,
            "industry": industry,
            "page": 0,
            "max_pages": max_pages,
            "pages_crawled": 0,
            "jobs_found": 0,
            "jobs_new": 0,
            "delay_seconds": None,
            "delay_remaining": None,
            "delay_reason": None,
            "updated_at": _now(),
            "events": [],
        }
        _append_event(progress, "Crawl accepted into polite queue", phase="queued")
        _state["progress"] = progress


def update_progress(**fields: Any) -> None:
    with _lock:
        progress = _state.get("progress") or {}
        log_message = fields.pop("log", None)
        progress.update(fields)
        progress["updated_at"] = _now()
        if log_message:
            _append_event(
                progress,
                str(log_message),
                phase=str(fields.get("phase") or progress.get("phase") or "info"),
            )
        _state["progress"] = progress


def bump_jobs(*, found: int = 0, new: int = 0) -> None:
    with _lock:
        progress = _state.get("progress") or {}
        progress["jobs_found"] = int(progress.get("jobs_found") or 0) + found
        progress["jobs_new"] = int(progress.get("jobs_new") or 0) + new
        progress["updated_at"] = _now()
        _state["progress"] = progress


def request_cancel() -> None:
    with _lock:
        if not _state["running"]:
            return
        _state["cancel_requested"] = True
        progress = _state.get("progress") or {}
        progress["message"] = "Cancelling — stopping after the current request…"
        progress["why"] = (
            "User requested cancel. Finishing the in-flight request, then "
            "stopping cleanly (no partial pages left dangling)."
        )
        progress["updated_at"] = _now()
        _append_event(
            progress, "Cancel requested by user", phase=progress.get("phase") or "info"
        )
        _state["progress"] = progress


def is_cancel_requested() -> bool:
    with _lock:
        return bool(_state.get("cancel_requested"))


def finish(
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with _lock:
        _state["running"] = False
        _state["last_result"] = result
        _state["error"] = error
        _state["cancel_requested"] = False
        progress = _state.get("progress") or {}
        progress["phase"] = "done" if not error else "error"
        progress["message"] = error or "Crawl finished"
        progress["why"] = (
            "Stopped with an error."
            if error
            else "All queued pages processed. Duplicates skipped by job_id."
        )
        progress["delay_seconds"] = None
        progress["delay_remaining"] = None
        progress["delay_reason"] = None
        progress["updated_at"] = _now()
        _append_event(
            progress,
            error or "Crawl finished successfully",
            phase=progress["phase"],
        )
        _state["progress"] = progress


def snapshot() -> dict[str, Any]:
    with _lock:
        return deepcopy(_state)


def is_running() -> bool:
    with _lock:
        return bool(_state["running"])
