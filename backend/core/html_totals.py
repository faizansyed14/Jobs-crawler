from __future__ import annotations

import re


def largest_jobs_found_count(
    html: str,
    pattern: re.Pattern[str],
    *,
    k_suffix_group: int | None = None,
) -> int | None:
    """Return the largest job-count matched in HTML (avoids small sidebar snippets)."""
    best: int | None = None
    for m in pattern.finditer(html):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if k_suffix_group is not None and m.group(k_suffix_group):
            if m.group(k_suffix_group).lower() == "k":
                value *= 1000
        count = int(value)
        if best is None or count > best:
            best = count
    return best
