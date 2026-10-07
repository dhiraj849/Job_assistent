from app.browser.apply_button import ApplyButtonType, classify_apply_button


def test_naukri_apply():
    assert classify_apply_button(["Apply"]) == ApplyButtonType.NAUKRI_APPLY


def test_company_site_wins_over_plain_apply_text():
    assert classify_apply_button(["Apply on company site"]) == ApplyButtonType.COMPANY_SITE


def test_already_applied():
    assert classify_apply_button(["Applied"]) == ApplyButtonType.ALREADY_APPLIED


def test_whitespace_and_case_are_ignored():
    assert classify_apply_button(["  APPLY \n NOW "]) == ApplyButtonType.NAUKRI_APPLY


def test_no_known_button_is_unknown():
    assert classify_apply_button([]) == ApplyButtonType.UNKNOWN
    assert classify_apply_button(["Save", "Share"]) == ApplyButtonType.UNKNOWN
