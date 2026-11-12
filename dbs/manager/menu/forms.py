from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from . import commands, meanings, pickers, plain, running
from .app import Screen
from .commands import MANY, SWITCH, Argument, Verb
from .kit import layout, text, theme
from .kit.canvas import Area, Canvas
from .kit.dialogs import Ask, Choice, Confirm, Pick
from .kit.fields import TextInput
from .kit.keys import Key
from .results import Outcome

LABEL_WIDEST = 40
ADD = object()
DONE = object()
DESTRUCTIVE = ("remove", "delete")
NO_CHOICE = ""


def launch(
    app: Any,
    verb: Verb,
    values: Mapping[str, Any],
    title: str = "",
    answers: Optional[Mapping[str, str]] = None,
) -> Optional[Outcome]:
    reason = meanings.NAMED_BECAUSE.get(verb.path)
    if reason is not None:
        app.tell(verb.name, f"{reason}\n\n{commands.shown(app.program, verb, values)}")
        return None
    question = meanings.ASKS_FIRST.get(verb.path)
    if question and not app.modal(Confirm(title or verb.name, question, danger=True)):
        return None
    if not verb.inside:
        return plain.run(app, verb, values)
    return running.run(app, verb, values, title=title, answers=answers)


class FormScreen(Screen):
    def __init__(
        self,
        app: Any,
        verb: Verb,
        values: Optional[Mapping[str, Any]] = None,
        title: str = "",
        fixed: Sequence[str] = (),
    ) -> None:
        super().__init__(app)
        self.verb = verb
        self.title = title or verb.name
        self.fixed = tuple(fixed)
        self.values: dict[str, Any] = dict(values or {})
        self.fields = [
            argument
            for argument in meanings.offered(verb)
            if argument.key not in self.fixed
        ]
        self.inputs = {
            argument.key: TextInput(str(self.values.get(argument.key) or ""))
            for argument in self.fields
            if self._typed(argument)
        }
        self.secrets = {
            argument.key: TextInput(masked=True)
            for argument in self.fields
            if argument.key in meanings.SECRETS
        }
        self.inputs.update(self.secrets)
        self.cursor = 0
        self.offset = 0
        self.problem = ""

    def _typed(self, argument: Argument) -> bool:
        return argument.kind not in (SWITCH, MANY) and not argument.choices

    def answers(self) -> dict[str, str]:
        return {
            meanings.SECRETS[key].prompt: field.value
            for key, field in self.secrets.items()
            if field.value
        }

    @property
    def current(self) -> Optional[Argument]:
        return self.fields[self.cursor] if self.cursor < len(self.fields) else None

    @property
    def destructive(self) -> bool:
        return self.verb.path[-1] in DESTRUCTIVE

    def collected(self) -> dict[str, Any]:
        found = dict(self.values)
        for key, field in self.inputs.items():
            found[key] = field.value.strip()
        for key, field in self.secrets.items():
            found[key] = bool(field.value)
        return found

    def draw(self, canvas: Canvas, area: Area) -> Optional[tuple[int, int]]:
        canvas.put(area.x, area.y, self.verb.help, theme.MUTED, area.columns)
        footer = 5
        body = area.inset(top=2, bottom=footer)
        width = min(
            max((text.width(self._label(field)) for field in self.fields), default=0),
            LABEL_WIDEST,
        )
        self._scroll(body.rows)
        cursor = None
        for line, argument in enumerate(
            self.fields[self.offset : self.offset + body.rows]
        ):
            index = self.offset + line
            found = self._draw_field(
                canvas, body, body.y + line, argument, width, index == self.cursor
            )
            cursor = found or cursor
        self._draw_foot(canvas, Area(area.x, body.bottom, area.columns, footer))
        return cursor

    def _draw_field(
        self, canvas, body, y, argument, width, active
    ) -> Optional[tuple[int, int]]:
        style = theme.ACCENT if active else theme.BASE
        if active:
            canvas.put(body.x, y, self.app.glyphs.pointer, theme.ACCENT)
        canvas.put(body.x + 2, y, self._label(argument), style, width)
        x = body.x + 2 + width + 2
        room = body.right - x
        if argument.key in self.inputs:
            field = self.inputs[argument.key]
            cursor = field.draw(canvas, x, y, room, active, self.app.terminal.unicode)
            if not field.value and not commands.absent(argument.default):
                box = theme.FIELD_ACTIVE if active else theme.FIELD
                canvas.put(
                    x + 2,
                    y,
                    f"{argument.default} if left empty",
                    theme.MUTED.over(box.bg),
                    room - 3,
                )
            return cursor
        box = theme.FIELD_ACTIVE if active else theme.FIELD
        canvas.fill(Area(x, y, room, 1), box)
        canvas.put(x + 1, y, self._shown(argument), box, room - 2)
        return None

    def _draw_foot(self, canvas: Canvas, area: Area) -> None:
        argument = self.current
        note = argument.help if argument is not None else "Enter runs it."
        if argument is not None and argument.key in self.secrets:
            note = meanings.SECRET_NOTE
        if argument is not None and pickers.can_pick(self.verb, argument):
            note = f"{note} Enter chooses from a list.".strip()
        layout.paragraph(
            canvas, Area(area.x, area.y + 1, area.columns, 2), note, theme.MUTED
        )
        if self.problem:
            layout.notice(
                canvas, area.row(3), self.app.glyphs, theme.DANGER, self.problem
            )
        else:
            command = commands.shown(self.app.program, self.verb, self.collected())
            canvas.put(
                area.x, area.y + 3, f"Runs: {command}", theme.MUTED, area.columns
            )
        on_button = self.cursor == len(self.fields)
        label = "  Run  "
        if self.destructive:
            style = theme.DANGER_BUTTON if on_button else theme.DANGER_IDLE
        else:
            style = theme.BUTTON if on_button else theme.BUTTON_IDLE
        canvas.put(area.x, area.y + 4, label, style)

    def _label(self, argument: Argument) -> str:
        return meanings.label(argument) + (" *" if argument.required else "")

    def _shown(self, argument: Argument) -> str:
        value = self.values.get(argument.key)
        if argument.kind == SWITCH:
            return self.app.glyphs.on + " Yes" if value else self.app.glyphs.off + " No"
        if argument.kind == MANY:
            return ", ".join(str(one) for one in value or ()) or "(none)"
        return str(value) if value else "(not set)"

    def _scroll(self, height: int) -> None:
        if height <= 0:
            return
        shown = min(self.cursor, len(self.fields) - 1)
        if shown < self.offset:
            self.offset = shown
        if shown >= self.offset + height:
            self.offset = shown - height + 1

    def key(self, key: Key) -> bool:
        self.problem = ""
        argument = self.current
        if key.name in ("down", "tab"):
            self.cursor = min(self.cursor + 1, len(self.fields))
        elif key.name in ("up", "backtab"):
            self.cursor = max(self.cursor - 1, 0)
        elif key.name == "escape":
            return False
        elif argument is None:
            if key.name == "enter":
                self.submit()
        elif key.name == "enter":
            self._entered(argument)
        elif argument.key in self.inputs:
            self.inputs[argument.key].key(key)
        elif key.is_text() and key.text == " ":
            self._entered(argument)
        elif key.name in ("left", "right") and argument.choices:
            self._cycle(argument, 1 if key.name == "right" else -1)
        return True

    def _entered(self, argument: Argument) -> None:
        if argument.key in self.secrets:
            self.cursor += 1
        elif argument.kind == SWITCH:
            self.values[argument.key] = not self.values.get(argument.key)
        elif argument.choices:
            self._choose(argument)
        elif pickers.can_pick(self.verb, argument):
            self._pick(argument)
        elif argument.kind == MANY:
            self._edit_many(argument)
        else:
            self.cursor += 1

    def _choose(self, argument: Argument) -> None:
        choices = [Choice(choice, choice) for choice in argument.choices]
        if not argument.required:
            choices.insert(0, Choice("(not set)", NO_CHOICE))
        current = self.values.get(argument.key)
        chosen = self.app.modal(
            Pick(meanings.label(argument), choices, chosen=[current] if current else ())
        )
        if chosen is not None:
            self.values[argument.key] = chosen

    def _cycle(self, argument: Argument, step: int) -> None:
        options = (
            list(argument.choices)
            if argument.required
            else [NO_CHOICE, *argument.choices]
        )
        current = self.values.get(argument.key) or NO_CHOICE
        index = options.index(current) if current in options else 0
        self.values[argument.key] = options[(index + step) % len(options)]

    def _pick(self, argument: Argument) -> None:
        chosen = pickers.pick(self.app, self.verb, argument, self.collected())
        if chosen is pickers.NOTHING:
            return
        self.values[argument.key] = chosen
        if argument.key in self.inputs:
            self.inputs[argument.key].set(str(chosen))

    def _edit_many(self, argument: Argument) -> None:
        values = list(self.values.get(argument.key) or ())
        while True:
            choices = [
                Choice(str(value), value, "Enter removes it") for value in values
            ]
            choices += [Choice("Add one", ADD), Choice("Done", DONE)]
            chosen = self.app.modal(
                Pick(
                    meanings.label(argument),
                    choices,
                    chosen=[ADD],
                    message=argument.help,
                )
            )
            if chosen is None or chosen is DONE:
                break
            if chosen is ADD:
                typed = self.app.modal(Ask(meanings.label(argument), argument.help))
                if typed:
                    values.append(typed)
            else:
                values.remove(chosen)
        self.values[argument.key] = values

    def problem_in(self, values: Mapping[str, Any]) -> str:
        for argument in self.verb.arguments:
            if (
                argument.required
                and commands.absent(values.get(argument.key))
                and argument.key not in meanings.HIDDEN
            ):
                return f"{meanings.label(argument)} is needed."
        rule = meanings.ONE_OF.get(self.verb.path)
        if rule is not None and all(
            commands.absent(values.get(key)) for key in rule[0]
        ):
            return rule[1]
        try:
            commands.parsed(self.verb, values)
        except commands.Refused as refused:
            return _sentence(str(refused))
        return ""

    def submit(self) -> None:
        values = self.collected()
        self.problem = self.problem_in(values)
        if self.problem:
            return
        answers = self.answers()
        for field in self.secrets.values():
            field.set("")
        outcome = launch(self.app, self.verb, values, self.title, answers)
        if outcome is None or not outcome.ok or self not in self.app.stack:
            return
        closing = self.app.top is self
        self.app.stack.remove(self)
        if closing:
            self.app.top.resumed()

    def hints(self) -> Sequence[tuple[str, str]]:
        return (("↑↓", "Move"), ("Enter", "Choose or run"), ("Space", "Switch"))


def _sentence(message: str) -> str:
    message = message.strip()
    return message[:1].upper() + message[1:] if message else message
