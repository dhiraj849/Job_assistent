from html.parser import HTMLParser
from pathlib import Path

from app.browser.apply_button import ApplyButton, ApplyButtonType, classify_apply_button
from app.browser.naukri_selectors import APPLY_BUTTON_IDS, APPLY_SUCCESS_TEXT

FIXTURES = Path(__file__).parent.parent / "fixtures" / "naukri"


class _Buttons(HTMLParser):
    """Collect (id, text) of every <button> in a saved page, like read_apply_buttons."""

    def __init__(self):
        super().__init__()
        self.buttons: list[ApplyButton] = []
        self._current: list | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self._current = [dict(attrs).get("id") or "", ""]

    def handle_data(self, data):
        if self._current is not None:
            self._current[1] += data

    def handle_endtag(self, tag):
        if tag == "button" and self._current is not None:
            self.buttons.append(ApplyButton(self._current[0], self._current[1].strip()))
            self._current = None


def buttons_in(fixture: str) -> list[ApplyButton]:
    parser = _Buttons()
    parser.feed((FIXTURES / fixture).read_text(encoding="utf-8"))
    return parser.buttons


def test_live_company_site_page():
    buttons = buttons_in("company_site.html")

    # The verified id from the selector file is really on the live page.
    assert any(b.id in APPLY_BUTTON_IDS for b in buttons)
    assert classify_apply_button(buttons) == ApplyButtonType.COMPANY_SITE


def test_naukri_apply():
    assert classify_apply_button([ApplyButton("", "Apply")]) == ApplyButtonType.NAUKRI_APPLY


def test_company_site_wins_over_plain_apply_text():
    buttons = [ApplyButton("", "Apply"), ApplyButton("", "Apply on company site")]
    assert classify_apply_button(buttons) == ApplyButtonType.COMPANY_SITE


def test_already_applied_wins_over_everything():
    buttons = [ApplyButton("", "Apply"), ApplyButton("", "Applied")]
    assert classify_apply_button(buttons) == ApplyButtonType.ALREADY_APPLIED


def test_known_id_beats_text():
    # A renamed label must not turn a company-site button into a Naukri apply.
    assert classify_apply_button([ApplyButton("company-site-button", "Apply")]) == ApplyButtonType.COMPANY_SITE


def test_whitespace_and_case_are_ignored():
    assert classify_apply_button([ApplyButton("", "  APPLY \n NOW ")]) == ApplyButtonType.NAUKRI_APPLY


def test_no_known_button_is_unknown():
    assert classify_apply_button([]) == ApplyButtonType.UNKNOWN
    assert classify_apply_button([ApplyButton("", "Save"), ApplyButton("", "Share")]) == ApplyButtonType.UNKNOWN


def test_live_naukri_apply_page():
    buttons = buttons_in("naukri_apply.html")

    assert ApplyButton("apply-button", "Apply") in buttons
    assert classify_apply_button(buttons) == ApplyButtonType.NAUKRI_APPLY


def test_live_apply_confirmation_page_has_the_success_marker():
    html = (FIXTURES / "apply_success.html").read_text(encoding="utf-8")

    # APPLY_SUCCESS = <container> :has-text(<text>); check both parts on the live sample.
    assert 'class="acp-header-container"' in html
    assert f'class="job-title-text">{APPLY_SUCCESS_TEXT} ' in html
