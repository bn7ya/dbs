import pytest

from dbs.manager.menu.kit.keys import Decoder, Key


def keys(*chunks):
    decoder = Decoder()
    found = []
    for chunk in chunks:
        found += decoder.feed(chunk)
    return found + decoder.flush()


@pytest.mark.parametrize(
    "sequence, name",
    [
        (b"\x1b[A", "up"),
        (b"\x1b[B", "down"),
        (b"\x1b[C", "right"),
        (b"\x1b[D", "left"),
        (b"\x1bOA", "up"),
        (b"\x1b[H", "home"),
        (b"\x1b[F", "end"),
        (b"\x1b[1~", "home"),
        (b"\x1b[4~", "end"),
        (b"\x1b[5~", "pageup"),
        (b"\x1b[6~", "pagedown"),
        (b"\x1b[3~", "delete"),
        (b"\x1b[Z", "backtab"),
        (b"\x1bOP", "f1"),
        (b"\x1b[15~", "f5"),
        (b"\r", "enter"),
        (b"\n", "enter"),
        (b"\t", "tab"),
        (b"\x7f", "backspace"),
        (b"\x08", "backspace"),
    ],
)
def test_a_terminal_sequence_is_one_named_key(sequence, name):
    assert keys(sequence) == [Key(name)]


def test_letters_arrive_as_text():
    assert keys(b"ab") == [Key("char", "a"), Key("char", "b")]


def test_a_control_letter_is_the_letter_with_control():
    assert keys(b"\x03") == [Key("char", "c", ctrl=True)]


def test_a_lone_escape_is_the_escape_key():
    assert keys(b"\x1b") == [Key("escape")]


def test_escape_then_a_letter_in_one_read_is_the_letter_with_alt():
    assert keys(b"\x1bx") == [Key("char", "x", alt=True)]


def test_a_sequence_split_between_two_reads_is_still_one_key():
    assert keys(b"\x1b[", b"A") == [Key("up")]


def test_a_modified_arrow_keeps_its_name_and_its_modifier():
    assert keys(b"\x1b[1;5C") == [Key("right", ctrl=True)]


def test_a_character_split_between_two_reads_is_put_together():
    encoded = "ع".encode()

    assert keys(encoded[:1], encoded[1:]) == [Key("char", "ع")]


def test_an_unknown_sequence_is_dropped_whole():
    assert keys(b"\x1b[99~a") == [Key("char", "a")]


def test_bracketed_paste_arrives_as_one_paste():
    assert keys(b"\x1b[200~one\ntwo\x1b[201~x") == [
        Key("paste", "one\ntwo"),
        Key("char", "x"),
    ]


def test_a_paste_split_across_reads_is_put_together():
    assert keys(b"\x1b[200~on", b"e\x1b[20", b"1~") == [Key("paste", "one")]


def test_lines_arriving_in_one_read_without_paste_marks_are_a_paste_not_enter():
    assert keys(b"first\nsecond") == [Key("paste", "first\nsecond")]


def test_text_then_enter_in_one_read_is_typed_and_entered():
    assert keys(b"ok\r") == [Key("char", "o"), Key("char", "k"), Key("enter")]
