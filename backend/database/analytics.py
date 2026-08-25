from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models import Job

Granularity = Literal["day", "week", "month"]

_DEFAULT_LOOKBACK: dict[str, int] = {"day": 30, "week": 12, "month": 12}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day_expr(dialect: str, column: Any) -> Any:
    if dialect == "sqlite":
        return func.strftime("%Y-%m-%d", column)
    return func.to_char(func.date_trunc("day", column), "YYYY-MM-DD")


def _period_key(value: date, granularity: Granularity) -> str:
    if granularity == "day":
        return value.isoformat()
    if granularity == "week":
        iso = value.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return f"{value.year}-{value.month:02d}"


def _generate_periods(
    since: date, until: date, granularity: Granularity
) -> list[str]:
    if granularity == "day":
        cursor = since
        out: list[str] = []
        while cursor <= until:
            out.append(_period_key(cursor, granularity))
            cursor += timedelta(days=1)
        return out

    if granularity == "week":
        cursor = since - timedelta(days=since.weekday())
        out = []
        while cursor <= until:
            out.append(_period_key(cursor, granularity))
            cursor += timedelta(weeks=1)
        return out

    cursor = date(since.year, since.month, 1)
    out = []
    while cursor <= until:
        out.append(_period_key(cursor, granularity))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return out


def _bucket_daily(
    daily: list[tuple[str, int]], granularity: Granularity
) -> list[tuple[str, int]]:
    if granularity == "day":
        return daily
    totals: dict[str, int] = defaultdict(int)
    for day_str, count in daily:
        try:
            d = date.fromisoformat(day_str)
        except ValueError:
            continue
        totals[_period_key(d, granularity)] += count
    return sorted(totals.items())


def _merge_timeline(
    rows: list[tuple[str, int]],
    since: date,
    until: date,
    granularity: Granularity,
) -> list[dict[str, Any]]:
    counts = {period: count for period, count in rows}
    periods = _generate_periods(since, until, granularity)
    return [{"period": p, "count": int(counts.get(p, 0))} for p in periods]


class JobAnalytics:
    """Aggregate job posting counts from stored crawl data."""

    def __init__(self, session: Session) -> None:
        self.session = session
        bind = session.get_bind()
        self.dialect = bind.dialect.name if bind is not None else "sqlite"

    def _filters(
        self,
        *,
        portal: str | None,
        location: str | None,
        industry: str | None,
        since: datetime,
    ) -> list[Any]:
        clauses: list[Any] = [Job.is_active.is_(True), Job.posted_at >= since]
        if portal:
            clauses.append(Job.source_portal == portal)
        if location:
            clauses.append(Job.search_location == location)
        if industry:
            clauses.append(func.lower(Job.industry) == industry.lower())
        return clauses

    def _daily_rows(
        self,
        *,
        portal: str | None,
        location: str | None,
        industry: str | None,
        since: datetime,
        city: str | None = None,
    ) -> list[tuple[str, int]]:
        day = _day_expr(self.dialect, Job.posted_at)
        clauses = self._filters(
            portal=portal, location=location, industry=industry, since=since
        )
        if city:
            clauses.append(Job.search_location == city)

        stmt = (
            select(day.label("period"), func.count().label("count"))
            .where(*clauses)
            .group_by(day)
            .order_by(day)
        )
        rows = self.session.execute(stmt).all()
        return [(str(r.period), int(r.count or 0)) for r in rows if r.period]

    def fetch(
        self,
        *,
        granularity: Granularity = "day",
        portal: str | None = None,
        location: str | None = None,
        industry: str | None = None,
        lookback: int | None = None,
        top_cities: int = 8,
    ) -> dict[str, Any]:
        periods = lookback or _DEFAULT_LOOKBACK[granularity]
        until_dt = _utc_now()
        if granularity == "day":
            since_date = (until_dt - timedelta(days=max(1, periods) - 1)).date()
        elif granularity == "week":
            since_date = (until_dt - timedelta(weeks=max(1, periods) - 1)).date()
        else:
            since_date = date(
                until_dt.year,
                max(1, until_dt.month - (periods - 1)),
                1,
            )
        since_dt = datetime.combine(since_date, datetime.min.time(), tzinfo=timezone.utc)

        base_clauses = self._filters(
            portal=portal, location=location, industry=industry, since=since_dt
        )

        total_in_range = int(
            self.session.execute(
                select(func.count()).select_from(Job).where(*base_clauses)
            ).scalar()
            or 0
        )
        total_all_time = int(
            self.session.execute(
                select(func.count())
                .select_from(Job)
                .where(Job.is_active.is_(True))
            ).scalar()
            or 0
        )

        daily_total = self._daily_rows(
            portal=portal,
            location=location,
            industry=industry,
            since=since_dt,
        )
        bucketed_total = _bucket_daily(daily_total, granularity)
        timeline = _merge_timeline(
            bucketed_total, since_date, until_dt.date(), granularity
        )

        city_stmt = (
            select(Job.search_location, func.count().label("count"))
            .where(*base_clauses, Job.search_location.is_not(None))
            .group_by(Job.search_location)
            .order_by(func.count().desc())
        )
        city_rows = self.session.execute(city_stmt).all()
        city_totals = [
            {"city": str(r.search_location), "count": int(r.count or 0)}
            for r in city_rows
            if r.search_location
        ]

        by_city: list[dict[str, Any]] = []
        if not location:
            for row in city_totals[:top_cities]:
                city_key = row["city"]
                daily_city = self._daily_rows(
                    portal=portal,
                    location=location,
                    industry=industry,
                    since=since_dt,
                    city=city_key,
                )
                bucketed_city = _bucket_daily(daily_city, granularity)
                city_timeline = _merge_timeline(
                    bucketed_city, since_date, until_dt.date(), granularity
                )
                by_city.append(
                    {
                        "city": city_key,
                        "total": row["count"],
                        "timeline": city_timeline,
                    }
                )

        portal_stmt = (
            select(Job.source_portal, func.count().label("count"))
            .where(*base_clauses)
            .group_by(Job.source_portal)
            .order_by(func.count().desc())
        )
        portal_rows = self.session.execute(portal_stmt).all()
        by_portal = [
            {"portal": str(r.source_portal), "count": int(r.count or 0)}
            for r in portal_rows
        ]

        peak = max((p["count"] for p in timeline), default=0)
        avg = round(total_in_range / max(len(timeline), 1), 1)

        return {
            "granularity": granularity,
            "lookback": periods,
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "total_in_range": total_in_range,
            "total_all_time": total_all_time,
            "average_per_period": avg,
            "peak_period_count": peak,
            "timeline": timeline,
            "city_totals": city_totals,
            "by_city": by_city,
            "by_portal": by_portal,
        }
