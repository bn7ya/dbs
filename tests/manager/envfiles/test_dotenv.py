from __future__ import annotations

import pytest

from dbs.manager.envfiles.dotenv import Diff, diff, key_names, parse


def test_names_come_from_assignments_in_the_order_they_appear():
    content = b"SECRET_KEY=abc\nDEBUG=0\nexport DATABASE_URL=postgres://db/app\n"

    assert key_names(content) == ["SECRET_KEY", "DEBUG", "DATABASE_URL"]


def test_blank_lines_and_comments_are_skipped():
    content = b"\n# SECRET_KEY=commented\n   # INDENTED=comment\n\t\nA=1\n#B=2\n"

    assert key_names(content) == ["A"]


@pytest.mark.parametrize(
    "line",
    [
        b"just some words",
        b"BARE_KEY",
        b"export ONLY_EXPORTED",
        b"=no name",
        b"1STARTS_WITH_DIGIT=x",
        b"HAS SPACE=x",
        b"bad$name=x",
        b"-dash=x",
        b"[section]",
        b"KEY: yaml",
    ],
)
def test_a_line_that_is_not_an_assignment_is_ignored_and_the_next_is_read(line):
    assert key_names(b"BEFORE=1\n" + line + b"\nAFTER=2\n") == ["BEFORE", "AFTER"]


def test_a_name_may_hold_letters_digits_underscores_dots_and_dashes():
    content = b"_private=1\nlower=2\nA1=3\napp.name=4\nfeature-flag=5\n"

    assert key_names(content) == ["_private", "lower", "A1", "app.name", "feature-flag"]


def test_a_name_longer_than_255_characters_is_not_a_name():
    assert key_names(b"A" * 255 + b"=1\n" + b"B" * 256 + b"=2\n") == ["A" * 255]


def test_spaces_and_tabs_around_the_assignment_are_allowed():
    content = b"  A=1\n\tB = 2\nexport\tC\t=\t3\n   export   D=4\n"

    assert parse(content) == {"A": "1", "B": "2", "C": "3", "D": "4"}


def test_export_alone_is_a_name_like_any_other():
    assert parse(b"export=1\nexported=2\n") == {"export": "1", "exported": "2"}


def test_a_name_given_twice_keeps_its_first_place_and_its_last_value():
    content = b"A=first\nB=2\nA=last\n"

    assert key_names(content) == ["A", "B"]
    assert parse(content) == {"A": "last", "B": "2"}


def test_an_empty_file_has_no_names():
    assert key_names(b"") == []


def test_a_byte_order_mark_and_windows_line_endings_are_read_through():
    assert parse(b"\xef\xbb\xbfA=1\r\nB=2\r\n") == {"A": "1", "B": "2"}


def test_an_unquoted_value_ends_at_a_comment_after_whitespace():
    content = (
        b"A=value # a comment\nB=value#not-a-comment\nC=  spaced  \nD=\nE= #only\n"
    )

    assert parse(content) == {
        "A": "value",
        "B": "value#not-a-comment",
        "C": "spaced",
        "D": "",
        "E": "#only",
    }


def test_a_quoted_value_keeps_hashes_and_spaces_inside_its_quotes():
    content = b"A=\"pa ss # word\"\nB='it # is'  # comment\nC=\"\"\nD=''\n"

    assert parse(content) == {"A": "pa ss # word", "B": "it # is", "C": "", "D": ""}


def test_in_double_quotes_a_backslash_keeps_the_next_character():
    assert parse(b'A="say \\"hi\\" # still"\nB="ends with \\\\"\n') == {
        "A": 'say \\"hi\\" # still',
        "B": "ends with \\\\",
    }


def test_single_quotes_are_literal():
    assert parse(b"A='C:\\path\\'\nB=2\n") == {"A": "C:\\path\\", "B": "2"}


def test_a_double_quoted_value_may_span_lines():
    content = (
        b'KEY="-----BEGIN KEY-----\nMIIBOgIBAAJB\n# not a comment\nNOT=a key\n'
        b'-----END KEY-----"\nAFTER=1\n'
    )

    assert parse(content) == {
        "KEY": "-----BEGIN KEY-----\nMIIBOgIBAAJB\n# not a comment\nNOT=a key\n-----END KEY-----",
        "AFTER": "1",
    }


def test_a_single_quoted_value_may_span_lines():
    assert parse(b"A='one\nTWO=2'\nB=3\n") == {"A": "one\nTWO=2", "B": "3"}


def test_a_quote_that_never_closes_makes_its_line_garbage_and_the_rest_is_read():
    content = b'BROKEN="never closed\nNEXT=1\nLAST=2\n'

    assert parse(content) == {"NEXT": "1", "LAST": "2"}


def test_anything_but_a_comment_after_the_closing_quote_makes_the_assignment_garbage():
    content = b'A="one"two\nB="multi\nline" junk\nC=3\nD="ok"   # fine\nE=\'ok\'#fine\n'

    assert parse(content) == {"C": "3", "D": "ok", "E": "ok"}


@pytest.mark.parametrize(
    "value",
    [b"$HOME", b"${HOME}", b"$(rm -rf /)", b"`id`", b"${A:-default}", b"~/path", b"*"],
)
def test_nothing_is_ever_evaluated_or_expanded(monkeypatch, value):
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("A", "expanded")

    assert parse(b"A=1\nV=" + value + b"\n") == {"A": "1", "V": value.decode()}
    assert parse(b'V="' + value + b'"\n') == {"V": value.decode()}


def test_bytes_that_are_not_utf8_are_compared_as_they_are():
    assert parse(b"A=\xff\nB=\xfe\n")["A"] != parse(b"A=\xfe\n")["A"]
    assert key_names(b"A=\xff\xfe\nB=2\n") == ["A", "B"]


def test_a_diff_names_what_was_added_removed_and_changed_and_never_a_value():
    old = b"KEEP=same\nCHANGE=old-secret\nGONE=x\n"
    new = b"NEW=y\nCHANGE=new-secret\nKEEP=same\n"

    assert diff(old, new) == Diff(added=["NEW"], removed=["GONE"], changed=["CHANGE"])


def test_the_same_file_has_no_differences():
    content = b"A=1\nB='two'\n"

    assert diff(content, content) == Diff(added=[], removed=[], changed=[])


def test_quoting_the_same_value_or_moving_a_comment_is_not_a_change():
    old = b"A=value\nB=two # old note\n"
    new = b"# a new comment\nB='two'   # new note\nA=\"value\"\n"

    assert diff(old, new) == Diff(added=[], removed=[], changed=[])


def test_a_diff_compares_the_last_value_of_a_name_given_twice():
    assert diff(b"A=1\nA=2\n", b"A=2\n") == Diff(added=[], removed=[], changed=[])
    assert diff(b"A=2\n", b"A=2\nA=3\n") == Diff(added=[], removed=[], changed=["A"])


def test_each_list_follows_the_order_of_its_file():
    old = b"Z=1\nY=1\nX=1\nW=1\n"
    new = b"W=2\nC=1\nX=2\nB=1\n"

    assert diff(old, new) == Diff(
        added=["C", "B"], removed=["Z", "Y"], changed=["W", "X"]
    )
