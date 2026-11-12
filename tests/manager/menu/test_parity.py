import argparse
import inspect
import re

import pytest

from dbs.manager import cli
from dbs.manager.menu import commands, meanings
from dbs.manager.menu.commands import MANY, SWITCH, VALUE
from dbs.manager.menu.screens import catalogue, sections
from dbs.manager.terminal.dispatch import handler_of

VERBS = commands.catalogue()
SCRIPT_ONLY = {
    "--json",
    "--as",
    "--password-stdin",
    "--ssh-password-stdin",
    "--sudo-password-stdin",
    "--passphrase-stdin",
    "--data-dir",
    "--database-url",
    "--yes",
    "--confirm-name",
}


def leaves(parser, path=()):
    branches = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not branches:
        return [path]
    return [
        leaf
        for name, child in branches[0].choices.items()
        for leaf in leaves(child, (*path, name))
    ]


def named(verb):
    return verb.name


def test_every_command_of_the_manager_is_in_the_menu():
    every = set(leaves(cli.build_parser()))

    assert {verb.path for verb in VERBS} == every
    assert {verb.path for verb in catalogue.offered()} == every - {("menu",)}


@pytest.mark.parametrize("verb", VERBS, ids=named)
def test_every_argument_a_form_offers_says_what_it_is(verb):
    unexplained = [
        argument.key
        for argument in meanings.offered(verb)
        if argument.kind != SWITCH
        and not argument.choices
        and argument.key not in meanings.SPECIFIC.get(verb.path, {})
        and argument.key not in meanings.COMMON
    ]

    assert unexplained == []


@pytest.mark.parametrize("verb", VERBS, ids=named)
def test_a_form_never_offers_what_only_a_script_needs(verb):
    offered = {argument.key for argument in meanings.offered(verb)}

    assert offered.isdisjoint(SCRIPT_ONLY)
    assert not any(key.endswith("-stdin") for key in offered)


@pytest.mark.parametrize("verb", [verb for verb in VERBS if verb.inside], ids=named)
def test_every_command_run_inside_the_menu_has_its_handler(verb):
    args = argparse.Namespace(handler=verb.handler)

    assert callable(handler_of(args))


def test_only_the_slices_commands_run_inside_the_menu():
    outside = {verb.path[0] for verb in VERBS if not verb.inside}

    assert outside == {
        "run",
        "paths",
        "createuser",
        "password",
        "account",
        "export",
        "import",
        "menu",
    }


def test_the_parser_holds_only_kinds_of_argument_a_form_knows():
    kinds = {argument.kind for verb in VERBS for argument in verb.arguments}

    assert kinds == {VALUE, SWITCH, MANY}


def test_a_secret_is_never_an_option_with_a_value():
    typed = [
        (verb.name, argument.key)
        for verb in VERBS
        for argument in meanings.offered(verb)
        if argument.kind != SWITCH
        and any(word in argument.key for word in ("password", "passphrase", "secret"))
    ]

    assert typed == []


def test_values_become_the_words_of_the_command():
    verb = commands.verb("backup", "restore")
    values = {"<backup>": "12", "--mode": "merge", "--real": True, "--to": ""}

    assert commands.words(verb, values) == [
        "backup",
        "restore",
        "--mode=merge",
        "--real",
        "12",
    ]
    assert commands.shown("django_dbs", verb, values) == (
        "django_dbs backup restore --mode=merge --real 12"
    )


def test_several_values_repeat_the_option_or_follow_each_other():
    plan = commands.verb("plan", "add")
    take = commands.verb("backup", "take")

    assert commands.words(plan, {"--path": ["/srv/a", "/srv/b"]})[-2:] == [
        "--path=/srv/a",
        "--path=/srv/b",
    ]
    assert commands.words(take, {"<applications>": ["shop", "blog"]}) == [
        "backup",
        "take",
        "shop",
        "blog",
    ]


def test_the_parser_gives_the_same_arguments_as_the_typed_command():
    verb = commands.verb("activity", "list")

    args = commands.parsed(verb, {"--status": "failed", "--limit": "5"})
    typed = cli.build_parser().parse_args(
        ["activity", "list", "--status", "failed", "--limit", "5"]
    )

    assert vars(args) == vars(typed)


def test_a_value_that_starts_with_a_dash_arrives_as_typed():
    delete = commands.verb("files", "delete")
    listed = commands.verb("server", "list")
    take = commands.verb("backup", "take")

    assert (
        commands.parsed(delete, {"<application>": "shop", "<path>": "-weird"}).path
        == "-weird"
    )
    assert commands.parsed(listed, {"--search": "-x"}).search == "-x"
    assert commands.parsed(take, {"<applications>": ["-a", "shop"]}).applications == [
        "-a",
        "shop",
    ]
    assert commands.shown(
        "dbs", delete, {"<application>": "shop", "<path>": "-weird"}
    ) == ("dbs files delete -- shop -weird")


def test_what_the_parser_refuses_is_a_message_not_an_exit():
    verb = commands.verb("activity", "list")

    with pytest.raises(commands.Refused, match="invalid int value"):
        commands.parsed(verb, {"--limit": "many"})


def test_a_command_line_shown_is_quoted_for_a_shell():
    verb = commands.verb("server", "add")

    shown = commands.shown(
        "django_dbs", verb, {"<name>": "web 1", "--host": "10.0.0.5"}
    )

    assert shown == "django_dbs server add --host=10.0.0.5 'web 1'"


def keys_of(path):
    return {argument.key for argument in commands.verb(*path).arguments}


@pytest.mark.parametrize(
    "table",
    [meanings.SPECIFIC, meanings.ONE_OF, meanings.ASKS_FIRST, meanings.NAMED_BECAUSE],
)
def test_what_the_menu_says_about_a_command_names_a_real_one(table):
    paths = {verb.path for verb in VERBS}

    assert set(table) <= paths


def test_every_meaning_names_a_real_argument_and_a_real_owner():
    for path, known in meanings.SPECIFIC.items():
        keys = keys_of(path)
        assert set(known) <= keys, path
        assert {meaning.of for meaning in known.values() if meaning.of} <= keys, path
    for path, (keys, _) in meanings.ONE_OF.items():
        assert set(keys) <= keys_of(path), path
    assert meanings.SHOWS_SECRET | meanings.NAMED_ONLY <= {verb.path for verb in VERBS}


def actions():
    for name, listing in sections.LISTINGS.items():
        for action in (*listing.actions, *listing.adds):
            yield name, action


def test_every_section_lists_with_a_real_command():
    for name, listing in sections.LISTINGS.items():
        assert set(listing.fill) <= keys_of(listing.path), name


def test_every_action_of_a_section_fills_a_real_command():
    for name, action in actions():
        if action.listing:
            assert action.listing in sections.LISTINGS, (name, action.label)
        elif not action.opens:
            assert set(action.fill) <= keys_of(action.path), (name, action.label)


def test_an_action_run_at_once_fills_everything_its_command_needs():
    for name, action in actions():
        if not action.direct:
            continue
        verb = commands.verb(*action.path)
        needed = {
            argument.key for argument in meanings.offered(verb) if argument.required
        }
        rule = meanings.ONE_OF.get(verb.path)
        assert needed <= set(action.fill), (name, action.label)
        assert rule is None or set(rule[0]) & set(action.fill), (name, action.label)


def test_a_secret_a_form_takes_answers_the_question_its_command_asks():
    for key, secret in meanings.SECRETS.items():
        takers = [
            verb
            for verb in VERBS
            if key in {argument.key for argument in verb.arguments}
        ]
        assert takers, key
        for verb in takers:
            assert verb.argument(key).kind == SWITCH, (verb.name, key)
            source = inspect.getsource(
                inspect.getmodule(handler_of(argparse.Namespace(handler=verb.handler)))
            )
            assert f'"{secret.prompt}"' in source, (verb.name, key)


def test_every_question_for_a_secret_that_is_always_worded_the_same_has_its_field():
    asked = set()
    for verb in VERBS:
        if verb.inside:
            module = inspect.getmodule(
                handler_of(argparse.Namespace(handler=verb.handler))
            )
            asked |= set(
                re.findall(r'session\.secret\(\s*"([^"]+)"', inspect.getsource(module))
            )

    assert asked == {secret.prompt for secret in meanings.SECRETS.values()}
