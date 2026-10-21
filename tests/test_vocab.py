from voz.vocab import Rule, Vocab, parse_dictionary


def test_parse_plain_and_mapped():
    r = parse_dictionary("Tenants2Guest\nowner res => OwnerRez\n# comment\n\n")
    assert r == [Rule(None, "Tenants2Guest"), Rule("owner res", "OwnerRez")]


def test_exact_mapping_applies(tmp_voz):
    v = Vocab.from_text("owner res => OwnerRez")
    assert v.apply("log into owner res today.") == "log into OwnerRez today."


def test_exact_canonical_fixes_case(tmp_voz):
    v = Vocab.from_text("Higgsfield")
    assert v.apply("open higgsfield.") == "open Higgsfield."


def test_fuzzy_single_word(tmp_voz):
    v = Vocab.from_text("Higgsfield")
    assert v.apply("render it in hicksfield tonight") == "render it in Higgsfield tonight"


def test_fuzzy_multiword_window(tmp_voz):
    v = Vocab.from_text("Tenants2Guest")
    assert v.apply("tenants to guest is growing") == "Tenants2Guest is growing"


def test_fuzzy_keeps_trailing_punctuation(tmp_voz):
    v = Vocab.from_text("Tenants2Guest")
    assert v.apply("I run tenants to guest, a rental business.") == "I run Tenants2Guest, a rental business."


def test_real_words_are_not_fuzzed(tmp_voz):
    v = Vocab.from_text("Claude")
    assert v.apply("cloud cover and clod") == "cloud cover and clod"


def test_non_words_are_fuzzed(tmp_voz):
    v = Vocab.from_text("Claude")
    assert v.apply("ask klaude about it") == "ask Claude about it"


def test_short_tokens_never_fuzzed(tmp_voz):
    v = Vocab.from_text("Tito")
    assert v.apply("to do it") == "to do it"


def test_special_chars_in_entry(tmp_voz):
    v = Vocab.from_text("C++\nTenants2Guest\n(beta) => beta")
    assert v.apply("c++ and (beta) here") == "C++ and beta here"


def test_words_lists_canonicals(tmp_voz):
    v = Vocab.from_text("owner res => OwnerRez\nHiggsfield\nHiggsfield")
    assert v.words() == ["OwnerRez", "Higgsfield"]


def test_learn_records_rule_and_new_proper_noun(tmp_voz):
    v = Vocab.from_text("")
    rules = v.learn("send it to ximena at the hyper frames kit", "send it to Ximena at the HyperFrames kit")
    assert Rule("hyper frames", "HyperFrames") in rules
    assert "Ximena" in v.words() and "HyperFrames" in v.words()
    assert Vocab.load().apply("the hyper frames kit") == "the HyperFrames kit"


def test_learn_ignores_identical_text(tmp_voz):
    v = Vocab.from_text("")
    assert v.learn("same words here", "same words here") == []


def test_add_word_persists(tmp_voz):
    v = Vocab.from_text("")
    v.add_word("OwnerRez")
    assert "OwnerRez" in Vocab.load().words()


# ---- regressions from the whole-branch review -----------------------------
from voz import config as _config
from voz.config import SEED_DICTIONARY

ORDINARY = [
    "I used Nano Banana to make it",
    "Deal Flow is live now",
    "Casually Historic is my channel",
    "the guest parked in the driveway",
    "she parked and walked in",
    "we saw three sedans parked out front",
    "she whispers to me",
    "I instantly knew to wear shorts",
    "bring clay and new reels",
    "the wilder side of town",
    "a whisper of wind",
]


def test_seed_dictionary_leaves_ordinary_sentences_alone(tmp_voz):
    v = Vocab.from_text("\n".join(SEED_DICTIONARY))
    for s in ORDINARY:
        assert v.apply(s) == s


def test_multiword_entries_still_case_fix_and_keep_following_words(tmp_voz):
    v = Vocab.from_text("Deal Flow\nNano Banana")
    assert v.apply("deal flow is live and nano banana is cheap") == "Deal Flow is live and Nano Banana is cheap"


def test_proper_name_entries_still_case_fix(tmp_voz):
    v = Vocab.from_text("Claude\nJennifer")
    assert v.apply("ask claude and jennifer") == "ask Claude and Jennifer"


def test_common_word_entries_only_fix_via_explicit_mapping(tmp_voz):
    v = Vocab.from_text("Instantly\ninstantly.ai => Instantly")
    assert v.apply("I instantly knew; we use instantly.ai daily") == "I instantly knew; we use Instantly daily"


def test_inflected_real_words_are_not_fuzzed(tmp_voz):
    v = Vocab.from_text("Parakeet\nSeedance\nWhisper")
    assert v.apply("they parked two sedans and she whispers") == "they parked two sedans and she whispers"


def test_learn_ignores_plain_rewording(tmp_voz):
    v = Vocab.from_text("")
    assert v.learn("I will send it tomorrow. The guest wants a late checkout.",
                   "I will send it on Monday. The guest wants an early checkout.") == []
    assert v.learn("that is good", "that is great") == []
    assert v.apply("see you tomorrow, that is good") == "see you tomorrow, that is good"
    assert "Monday" not in v.words()


def test_learn_keeps_sound_alike_and_name_fixes(tmp_voz):
    v = Vocab.from_text("")
    rules = v.learn("send it to hicks field and owner res, then ping ximena",
                    "send it to Higgsfield and OwnerRez, then ping Ximena")
    assert Rule("hicks field", "Higgsfield") in rules and Rule("owner res", "OwnerRez") in rules
    assert "Ximena" in v.words()


def test_learn_accepts_correction_into_a_dictionary_word(tmp_voz):
    v = Vocab.from_text("Tenants2Guest")
    assert Rule("tenants to guests", "Tenants2Guest") in v.learn("tenants to guests is growing", "Tenants2Guest is growing")


def test_forget_learned_clears_memory_and_file(tmp_voz):
    v = Vocab.from_text("")
    v.learn("log into owner res", "log into OwnerRez")
    assert v.learned and _config.LEARNED_PATH.exists()
    v.forget_learned()
    assert v.learned == [] and Vocab.load().learned == []
