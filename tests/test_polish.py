from voz.polish import Polisher, build_prompt


def test_prompt_contains_words_examples_and_text():
    p = build_prompt("um send it to higgsfield", ["Higgsfield", "Tenants2Guest"], ["Earlier dictation one.", "Another one."])
    assert "Higgsfield" in p and "Tenants2Guest" in p
    assert "Earlier dictation one." in p
    assert "um send it to higgsfield" in p


def test_polisher_uses_injected_generate_and_strips_wrapping():
    pol = Polisher(generate=lambda prompt: '  "Send it to Higgsfield."  \n\nNote: fixed casing')
    assert pol.polish("send it to higgsfield", ["Higgsfield"], []) == "Send it to Higgsfield."


def test_polisher_falls_back_on_exception():
    def boom(prompt):
        raise RuntimeError("no model")
    pol = Polisher(generate=boom)
    assert pol.polish("keep this text", [], []) == "keep this text"


def test_polisher_falls_back_on_runaway_output():
    pol = Polisher(generate=lambda prompt: "this is a much much much longer rewrite than the short input ever was at all")
    assert pol.polish("short input here", [], []) == "short input here"


def test_polisher_falls_back_on_empty_output():
    pol = Polisher(generate=lambda prompt: "")
    assert pol.polish("short input here", [], []) == "short input here"


def test_polisher_keeps_newlines_from_input_when_model_drops_them():
    pol = Polisher(generate=lambda prompt: "First point. Second point.")
    assert pol.polish("first point\nsecond point", [], []) == "first point\nsecond point"


def test_available_reflects_mlx_lm(monkeypatch):
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert Polisher.available() is False
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert Polisher.available() is True
