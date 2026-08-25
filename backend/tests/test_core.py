from __future__ import annotations

from config.portals import get_portal_config
from core.date_parser import parse_unix_timestamp
from extractors.naukrigulf import NaukrigulfExtractor, _as_bool


def test_locations_and_it_industry():
    cfg = get_portal_config("naukrigulf")
    locs = cfg.resolve_locations(["dubai", "abu-dhabi", "riyadh", "qatar", "kuwait"])
    assert [l.key for l in locs] == ["dubai", "abu-dhabi", "riyadh", "qatar", "kuwait"]
    it = cfg.resolve_industry("it")
    assert it is not None
    assert it.cluster_ind == "25"


def test_parse_unix():
    dt = parse_unix_timestamp("1787312066")
    assert dt is not None
    assert dt.year >= 2026


def test_bool_parse():
    assert _as_bool("true") is True
    assert _as_bool("false") is False


def test_normalize_job_shape():
    from config.portals import NaukrigulfConfig

    ext = NaukrigulfExtractor.__new__(NaukrigulfExtractor)
    ext.config = NaukrigulfConfig()
    loc = ext.config.locations["dubai"]
    job = NaukrigulfExtractor._normalize(
        ext,
        {
            "jobId": "210826000735",
            "designation": "Technical Business Analyst",
            "jdURL": "technical-business-analyst-jobs-in-dubai",
            "latestPostedDate": "1787307475",
            "company": {"id": "277626", "name": "Finclutech Ltd FZCO"},
            "compensation": {"MinCtc": "$15,001", "MaxCtc": "$30,000", "IsCtcHidden": "false"},
            "isPremium": "false",
            "isSponsoredJob": False,
        },
        location=loc,
        industry="IT",
    )
    assert job is not None
    assert job.title == "Technical Business Analyst"
    assert job.company_name == "Finclutech Ltd FZCO"
    assert job.url.startswith("https://www.naukrigulf.com/")
    assert job.salary == "$15,001 - $30,000"
    assert job.search_location == "dubai"