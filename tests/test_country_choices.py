from app.phone import country_choices


def test_returns_code_and_localized_label_sorted():
    en = country_choices("en")
    codes = [c for c, _ in en]
    assert "EE" in codes and "RU" in codes and "US" in codes
    labels = {c: lbl for c, lbl in en}
    assert labels["EE"] == "Estonia (EE)"
    assert [l.lower() for _, l in en] == sorted(l.lower() for _, l in en)


def test_localizes_to_interface_language():
    ru = dict(country_choices("ru"))
    assert ru["EE"] == "Эстония (EE)"


def test_unknown_locale_falls_back_to_english_names():
    out = country_choices("zz")
    assert dict(out)["EE"].endswith("(EE)")
