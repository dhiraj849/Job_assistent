"""Answers I type in the fill review (no browser, no AI)."""

import asyncio

import pytest

from app.browser.company_portal import FormField
from app.browser.company_site_page import FormWatch
from scripts import company_form_cli
from scripts.company_form_cli import FilledForm, _ask_own, _own_value, current_values

EXPERIENCE = FormField(
    kind="select", label="Total Experience",
    options=("Select", "1-2 Years", "1-3 Years", "1-4 Years", "3+ Years", "5-8 Years"),
)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("1-4 years", "1-4 Years"), ("1-4", "1-4 Years"), ("3", "3+ Years"), ("1-", None), ("7", None), ("", None)],
)
def test_own_value_names_one_option(typed, expected):
    assert _own_value(EXPERIENCE, typed) == expected


def test_ask_own_asks_again_until_it_fits(monkeypatch):
    typed = iter(["1-", "1-4"])

    async def fake_ask(_prompt):
        return next(typed)

    monkeypatch.setattr(company_form_cli, "ask", fake_ask)
    assert asyncio.run(_ask_own(EXPERIENCE, "> ")) == "1-4 Years"


class ClearedPage:
    """A form page that cleared itself after a fetch() submit (zaax.com)."""

    url = "https://www.zaax.com/submit-resume/"

    async def evaluate(self, _js, _form_index):
        return [{"name": "gender", "id": "gender", "type": "select-one", "value": ""}]


def filled_on(page):
    return FilledForm(target=page, form_index=0, url=ClearedPage.url, mapped=[])


def test_values_seen_at_submit_win_over_a_cleared_form():
    watch = FormWatch()
    watch._report(None, [{"name": "gender", "id": "gender", "type": "select-one", "value": "Female"}])

    values = asyncio.run(current_values(filled_on(ClearedPage()), watch))

    assert values[0]["value"] == "Female"


def test_without_a_report_the_form_is_read_now():
    values = asyncio.run(current_values(filled_on(ClearedPage()), FormWatch()))
    assert values[0]["value"] == ""
