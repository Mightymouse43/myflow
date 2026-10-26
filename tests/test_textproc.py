from voz.config import Config
from voz.textproc import join_prefix, apply_spoken_commands, clean, collapse_repeats, remove_fillers, tidy

F = ["um", "uh", "erm", "hmm", "you know"]


def test_removes_fillers_case_and_punct():
    assert remove_fillers("Um, so I think, uh, we should go.", F) == "So I think we should go."


def test_filler_inside_word_untouched():
    assert remove_fillers("The drum and the humming.", F) == "The drum and the humming."


def test_multiword_filler():
    assert remove_fillers("It was, you know, fine.", F) == "It was fine."


def test_multiword_filler_kept_when_it_is_a_real_phrase():
    assert remove_fillers("Do you know the way?", F) == "Do you know the way?"


def test_filler_at_end_takes_its_punctuation_back():
    assert remove_fillers("We did it, um.", F) == "We did it."


def test_collapse_repeats():
    assert collapse_repeats("I I think the the plan is is good") == "I think the plan is good"


def test_repeat_keeps_intentional_pairs():
    assert collapse_repeats("that that") == "that"  # documented tradeoff
    assert collapse_repeats("bye bye") == "bye bye"  # allowlist: bye, very, no, so


def test_spoken_newline_and_paragraph():
    assert apply_spoken_commands("first point new line second point new paragraph third") == "first point\nsecond point\n\nthird"


def test_spoken_command_with_whisper_style_punctuation():
    assert apply_spoken_commands("First point. New line. Second point") == "First point.\nSecond point"


def test_tidy_capitalises_and_ends():
    assert tidy("hello there. how are you") == "Hello there. How are you."


def test_tidy_leaves_short_fragments_alone():
    assert tidy("ok") == "Ok"


def test_clean_pipeline():
    cfg = Config()
    assert clean("um so the the plan new line is good", cfg) == "So the plan\nis good."


def test_clean_respects_toggles():
    cfg = Config(remove_fillers=False, spoken_commands=False)
    assert clean("um new line go", cfg) == "Um new line go."


# ---- join_prefix: what goes between the text already in the field and the new dictation ----

def test_join_adds_a_space_after_a_sentence_end():
    assert join_prefix(".", "I believe we do.") == " "
    assert join_prefix("?", "Yes.") == " "


def test_join_adds_a_space_after_a_letter_or_comma():
    assert join_prefix("e", "Two") == " "
    assert join_prefix(",", "and then") == " "


def test_join_adds_nothing_after_whitespace_or_at_the_start_of_a_field():
    assert join_prefix(" ", "Hello") == ""
    assert join_prefix("\n", "Hello") == ""
    assert join_prefix("", "Hello") == ""


def test_join_adds_nothing_when_the_caret_context_is_unknown():
    assert join_prefix(None, "Hello") == ""


def test_join_adds_nothing_after_an_opening_bracket_or_quote():
    assert join_prefix("(", "Hello") == ""
    assert join_prefix('"', "Hello") == ""


def test_join_adds_nothing_before_a_spoken_newline_or_empty_text():
    assert join_prefix(".", "\nNext point") == ""
    assert join_prefix(".", "") == ""


# ---- spoken quotes (Carlos, 2026-10-26): "say X" and "quote X end quote" ------------------------------------

from voz.textproc import apply_quotes


def test_explicit_quote_command():
    assert apply_quotes("quote hold my cup end quote") == '"hold my cup".'
    assert apply_quotes("Quote, hold my cup, end quote.") == '"hold my cup".'
    assert apply_quotes("make the sign read open quote wet paint close quote and leave it") == 'make the sign read "wet paint" and leave it'
    assert apply_quotes("it says quote hi there unquote, then stops") == 'it says "hi there", then stops'


def test_say_shortcut_quotes_to_the_end_of_the_clause():
    assert apply_quotes("I would like it to say hold my cup") == 'I would like it to say "hold my cup".'
    assert apply_quotes("Instead of putting the end, we actually make it say Happy Halloween.") == \
        'Instead of putting the end, we actually make it say "Happy Halloween".'
    assert apply_quotes("The card says happy birthday, and then the hand draws the webs.") == \
        'The card says "happy birthday", and then the hand draws the webs.'
    assert apply_quotes("it should say hold my cup, then a new line") == 'it should say "hold my cup", then a new line'
    assert apply_quotes("have the button say get started?") == 'have the button say "get started"?'


def test_say_shortcut_leaves_ordinary_uses_of_say_alone():
    for line in ("I'd say 10 seconds is enough.", "Let's say we do it tomorrow.", "People say it's hard.",
                 "Or how about saying it's that time of the year again but like in spooky letters.",
                 "I would say the second one.", "They say the show is good."):
        assert apply_quotes(line) == line, line


def test_say_shortcut_gives_up_on_a_long_unpunctuated_tail():
    long = "make it say " + " ".join(["word"] * 13)
    assert apply_quotes(long) == long


def test_say_shortcut_does_not_double_quote_an_explicit_quote():
    assert apply_quotes("make it say quote hold my cup end quote") == 'make it say "hold my cup".'


def test_clean_pipeline_quotes_and_capitalises():
    assert clean("um we actually make it say happy halloween", Config()) == 'We actually make it say "happy halloween".'
    assert clean("make it say hi there", Config(spoken_commands=False)) == "Make it say hi there."
