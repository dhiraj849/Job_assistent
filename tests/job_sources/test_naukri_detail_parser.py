"""parse_job_detail on REAL saved Naukri detail pages (no network).

Fixtures come from scripts/inspect_job_page.py (trimmed live pages,
2026-10-07). If Naukri changes its markup, re-capture and re-run these.
"""

import re
from datetime import date
from pathlib import Path

import pytest

from app.job_sources.naukri_detail_parser import (
    MIN_DESCRIPTION_CHARS,
    DetailParseError,
    html_to_text,
    parse_job_detail,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "naukri"
JSON_LD = re.compile(r'<script type="application/ld\+json">.*?</script>', re.S)
JD_SECTION = re.compile(r'<section class="styles_job-desc-container.*</section>', re.S)


def page(job_id: int) -> str:
    return (FIXTURES / f"job_detail_{job_id}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("job_id", [34, 37, 39])
def test_live_pages_give_a_full_description(job_id):
    result = parse_job_detail(page(job_id))

    assert result.details.source == "json_ld"
    # The search-card snippet we had before is ~90 chars.
    assert len(result.description) > 500
    assert "<" not in result.description  # HTML stripped
    assert result.details.skills


def test_all_details_of_one_page():
    details = parse_job_detail(page(34)).details

    assert details.salary == "15-25 Lacs P.A"
    assert details.experience_months == 72
    assert details.employment_type == "Full Time, Permanent"
    assert details.industry == "IT Services & Consulting"
    assert details.department == "Engineering - Software & QA"
    assert details.role == "Software Development - Other"
    assert details.education == "Any Graduate"
    assert details.date_posted == date(2026, 9, 25)
    assert details.valid_through == date(2026, 12, 24)
    assert "Jira" in details.skills


def test_not_disclosed_salary_is_none():
    assert parse_job_detail(page(37)).details.salary is None


def test_description_keeps_lines_and_list_items():
    description = parse_job_detail(page(34)).description

    assert description.startswith("Python Developer\nExperience: 6years to 10 Years\n")
    assert "\n- Ability to build efficient APIs using Python frameworks.\n" in description


def test_without_json_ld_falls_back_to_the_rendered_jd():
    html = JSON_LD.sub("", page(37))
    result = parse_job_detail(html)

    assert result.details.source == "dom"
    # Same text as the JSON-LD path, only without the extra fields.
    assert result.description == parse_job_detail(page(37)).description
    assert result.details.salary is None and result.details.skills == []


def test_broken_json_ld_falls_back_instead_of_crashing():
    html = page(39).replace('"@type":"JobPosting"', '"@type":"JobPosting",,', 1)
    assert parse_job_detail(html).details.source == "dom"


def test_page_without_any_jd_raises_a_clear_error():
    html = JD_SECTION.sub("", JSON_LD.sub("", page(34)))

    with pytest.raises(DetailParseError, match="no job description found"):
        parse_job_detail(html)


def test_near_empty_jd_is_an_error_not_a_saved_blank():
    html = (
        '<script type="application/ld+json">{"@type": "JobPosting", "description": "<p>Hi</p>"}</script>'
        '<div class="styles_JDC__dang-inner-html__x1"> </div>'
    )
    with pytest.raises(DetailParseError):
        parse_job_detail(html)
    assert MIN_DESCRIPTION_CHARS > len("Hi")


def test_fallback_class_must_be_the_prefix_before_the_hash():
    # A longer class sharing the prefix (no "__" after it) is not the JD.
    html = '<div class="styles_JDC__dang-inner-html-other">' + "x " * 100 + "</div>"
    with pytest.raises(DetailParseError):
        parse_job_detail(html)


def test_html_to_text_decodes_entities_and_skips_scripts():
    assert html_to_text("<p>R&amp;D</p><script>var a=1</script><br/>Next") == "R&D\nNext"
