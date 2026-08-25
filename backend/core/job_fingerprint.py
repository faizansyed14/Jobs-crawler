from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def job_content_fingerprint(
    *,
    source_portal: str,
    title: str,
    company_name: str,
    posted_at: datetime,
) -> str:
    """Stable hash for title + company + posted date (UTC day) per portal."""
    title_n = " ".join(title.strip().lower().split())
    company_n = " ".join(company_name.strip().lower().split())
    aware = posted_at
    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=timezone.utc)
    else:
        aware = aware.astimezone(timezone.utc)
    date_n = aware.date().isoformat()
    raw = f"{source_portal.strip().lower()}|{title_n}|{company_n}|{date_n}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
