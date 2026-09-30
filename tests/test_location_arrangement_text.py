import pytest

from jobintel.normalize.arrangement import classify_arrangement
from jobintel.normalize.location import parse_location
from jobintel.normalize.text import clean_company, clean_title, company_key, html_to_text


@pytest.mark.parametrize(
    "raw, is_uk, cities, country",
    [
        ("Cardiff, London or Remote (UK)", True, ["Cardiff", "London"], "GB"),
        ("Solihull, England, United Kingdom", True, ["Solihull"], "GB"),
        ("Remote - United Kingdom", True, [], "GB"),
        ("Dublin, Ireland; London, England", True, ["London"], "GB"),
        ("New York City, New York", False, [], "US"),   # must not match UK "York"
        ("Riga, Latvia", False, [], "LV"),
        ("São Paulo, Brazil", False, [], "BR"),
        ("Remote - EMEA", False, [], None),
        ("Newcastle upon Tyne", True, ["Newcastle upon Tyne"], "GB"),
        (None, False, [], None),
    ],
)
def test_parse_location(raw, is_uk, cities, country):
    info = parse_location(raw)
    assert (info.is_uk, info.cities, info.country) == (is_uk, cities, country)


def test_office_fallback_only_when_location_unrecognised():
    assert parse_location("Deliveroo", "London").is_uk
    # an explicit foreign location is never overridden by office metadata
    assert not parse_location("Riga, Latvia", "London").is_uk


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"location": "Remote UK"}, "remote"),
        ({"location": "London (Hybrid)"}, "hybrid"),
        ({"title": "Data Analyst - Hybrid", "location": "Leeds"}, "hybrid"),
        ({"description": "This role is fully remote within the UK."}, "remote"),
        ({"description": "Location: London, Bristol or Edinburgh (Hybrid working model)"},
         "hybrid"),
        ({"description": "You'll spend 3 days a week in the office."}, "hybrid"),
        ({"description": "You'll spend 2-3 days per week in the office."}, "hybrid"),
        ({"description": "You'll be 5 days a week in the office."}, "on-site"),
        ({"description": "Please note this is not a remote role."}, "on-site"),
        ({"description": "This is an office-based role in Manchester."}, "on-site"),
        # benefits / culture statements are not an arrangement
        ({"description": "Perks: on-site gym and on-site physio."}, "unknown"),
        ({"description": "30 days a year to work from anywhere in the world."}, "unknown"),
        ({"description": "We take a remote-friendly approach to collaboration."}, "unknown"),
        ({"description": "Great team, SQL and Python."}, "unknown"),
        ({"hint": "remote", "description": "5 days a week in the office"}, "remote"),
    ],
)
def test_classify_arrangement(kwargs, expected):
    assert classify_arrangement(**kwargs)[0] == expected


def test_html_to_text_keeps_list_items_separate_and_unescapes():
    html = "&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;li&gt;SQL&amp;nbsp;&lt;/li&gt;&lt;/ul&gt;"
    assert [ln for ln in html_to_text(html).split("\n") if ln] == ["Python", "SQL"]


def test_clean_names():
    assert clean_company("  Auto Trader Ltd ") == "Auto Trader"
    assert clean_company("Example Group PLC") == "Example"
    assert company_key("Auto Trader Limited") == company_key("auto trader")
    assert clean_title("Data Analyst (m/f/d)") == "Data Analyst"
    assert clean_title("Data Engineer - Remote") == "Data Engineer"
    assert clean_title("Analytics  Engineer") == "Analytics Engineer"
