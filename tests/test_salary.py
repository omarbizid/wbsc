from decimal import Decimal

import pytest

from jobintel.normalize.salary import extract_salary_from_text, normalize_structured


@pytest.mark.parametrize(
    "text, lo, hi, cur, period, inferred",
    [
        ("Salary: £42,500 - £55,000 + incentive awards", 42500, 55000, "GBP", "year", True),
        ("We pay £100,000 to £130,000 per annum", 100000, 130000, "GBP", "year", False),
        ("£121,600-164,600 + Incentive Awards", 121600, 164600, "GBP", "year", True),
        ("£150,000 - £200, 000 + Equity", 150000, 200000, "GBP", "year", True),
        ("Base salary of £50,000", 50000, 50000, "GBP", "year", True),
        ("€48,000 - €63,000 per annum", 48000, 63000, "EUR", "year", False),
        ("$190,900—$253,750 USD", 190900, 253750, "USD", "year", True),
        ("£35k - £45k DOE", 35000, 45000, "GBP", "year", True),
        ("£30-40k", 30000, 40000, "GBP", "year", True),
        ("Day rate: £450 - £550 per day", 450, 550, "GBP", "day", False),
        ("£12.50 - £14.00 per hour", Decimal("12.50"), Decimal("14.00"), "GBP", "hour", False),
    ],
)
def test_extracts_advertised_salary(text, lo, hi, cur, period, inferred):
    s = extract_salary_from_text(text)
    assert s is not None
    assert (s.min, s.max, s.currency, s.period, s.period_inferred) == (
        Decimal(lo), Decimal(hi), cur, period, inferred)
    assert s.source == "text"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Competitive salary and benefits",
        "£1,000 a year for books, training courses and conferences",
        "£1,000 learning budget each year",
        "A £2,503 overnight allowance",
        "We raised £50,000,000 in our Series C funding round",
        "£67,000 Total OTE (base salary + commission)",
        "Up to £500 home office equipment budget",
        "We serve 10,000 customers",
    ],
)
def test_no_salary_is_not_invented(text):
    assert extract_salary_from_text(text) is None


def test_benefit_before_real_salary_is_skipped():
    text = "£1,000 a year for books.\nSalary: £40,000 - £45,000"
    s = extract_salary_from_text(text)
    assert (s.min, s.max) == (40000, 45000)


def test_structured_salary_keeps_missing_currency_missing():
    s = normalize_structured(30000, 35000, None, "per annum")
    assert s.currency is None and s.period == "year"


def test_structured_salary_absent():
    assert normalize_structured(None, None, "GBP", None) is None
    assert normalize_structured(0, 0, "GBP", None) is None
