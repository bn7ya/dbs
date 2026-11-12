from dbs.manager.menu.kit import text


def test_width_counts_wide_characters_twice_and_combining_marks_not_at_all():
    assert text.width("abc") == 3
    assert text.width("日本") == 4
    assert text.width("é") == 1


def test_a_long_text_is_cut_with_an_ellipsis_within_its_columns():
    assert text.clip("backup-of-the-shop", 10) == "backup-of…"
    assert text.width(text.clip("日本語のテキスト", 7)) <= 7


def test_a_text_that_fits_is_left_alone():
    assert text.clip("shop", 10) == "shop"


def test_fit_pads_to_the_columns_on_the_side_asked():
    assert text.fit("ab", 5) == "ab   "
    assert text.fit("ab", 5, "right") == "   ab"


def test_wrap_breaks_between_words_and_splits_a_word_too_long_for_a_line():
    assert text.wrap("take a backup now", 9) == ["take a", "backup", "now"]
    assert text.wrap("abcdefghij", 4) == ["abcd", "efgh", "ij"]


def test_an_escape_sequence_in_a_name_is_shown_and_never_sent():
    shown = text.safe("\x1b[31mred\x07")

    assert "\x1b" not in shown and "\x07" not in shown
    assert shown == "␛[31mred␇"


def test_a_line_break_in_a_name_is_shown_as_a_character():
    assert text.safe("a\nb") == "a␊b"
