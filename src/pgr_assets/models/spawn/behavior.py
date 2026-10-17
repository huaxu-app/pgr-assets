import operator
from collections.abc import Callable

from pgr_assets.models.spawn.fighttables import FightTables

ACTION, SELECTOR, SEQUENCE, PARALLEL, RANDOM, LOOP, SWITCH, CASE = range(8)
COMPARE = {
    1: operator.eq,
    2: operator.gt,
    3: operator.ge,
    4: operator.lt,
    5: operator.le,
}
NOTE_PREDICATES = ("CheckInt", "CheckIntCompareInt", "CheckFixCompareFix")
NOTE_SETTERS = ("DoSetInt", "DoSetNpcId", "DoSetMagicId", "DoSetFix", "DoSetNpcNote")
LOOP_CAP = 64
SCOPES = "12345"
# Every tree run gets this scope fresh and hands it back when done.
TREE_SCOPE = "1"

Notes = dict[int, float]


class Notebook:
    def __init__(self) -> None:
        self.scopes: dict[str, Notes] = {scope: {} for scope in SCOPES}

    def _slot(self, token: str) -> tuple[Notes, int] | None:
        """
        The notes and key a scope#key token points at, the key signed as
        XStringToInt2.GetInt reads it.
        """
        scope, _, key = token.strip().partition("#")
        notes = self.scopes.get(scope)
        if notes is None or not key.removeprefix("-").isdecimal():
            return None
        return notes, int(key)

    def value(self, token: str) -> float | None:
        if "#" in token:
            slot = self._slot(token)
            return None if slot is None else slot[0].get(slot[1])
        try:
            return float(token)
        except ValueError:
            return None

    def store(self, token: str, value: float) -> None:
        if slot := self._slot(token):
            slot[0][slot[1]] = value


Handler = Callable[[str, list[str], Notebook], bool | None]


class Interpreter:
    def __init__(self, tables: FightTables, handler: Handler) -> None:
        self.tables = tables
        self.handler = handler

    def run_setup(self, behavior_id: int, notebook: Notebook) -> None:
        """
        PrefixRoot, which the fight runs once when the behavior is added.
        """
        if root := self.tables.prefix_roots.get(behavior_id):
            self._run_tree(root, notebook)

    def _run_tree(self, root: int, notebook: Notebook) -> None:
        saved = notebook.scopes[TREE_SCOPE]
        notebook.scopes[TREE_SCOPE] = {}
        try:
            self.run(root, notebook)
        finally:
            notebook.scopes[TREE_SCOPE] = saved

    def run(self, node_id: int, notebook: Notebook) -> bool:
        node = self.tables.nodes.get(node_id)
        if node is None:
            return False
        if node.kind == ACTION:
            return self.action(node.name, node.param, notebook) != node.negative
        # Random goes in authored order. Spawn hides came out the same either way.
        if node.kind in (SELECTOR, RANDOM):
            return any(self.run(c, notebook) for c in node.children)
        if node.kind == SEQUENCE:
            return all(self.run(c, notebook) for c in node.children)
        if node.kind == PARALLEL:
            for c in node.children:
                self.run(c, notebook)
            return True
        if node.kind == LOOP:
            for _ in range(LOOP_CAP):
                if not all(self.run(c, notebook) for c in node.children):
                    break
            return True
        if node.kind == SWITCH:
            for c in node.children:
                case = self.tables.nodes.get(c)
                if (
                    case
                    and case.kind == CASE
                    and self.matches(node.param, case.param, notebook)
                ):
                    return all(self.run(g, notebook) for g in case.children)
            return False
        # Anything else plays a sequence and hopes for the best.
        return all(self.run(c, notebook) for c in node.children)

    def matches(self, switch: str, case: str, notebook: Notebook) -> bool:
        case = case.strip()
        op = operator.eq
        for prefix, candidate in (
            ("<=", operator.le),
            (">=", operator.ge),
            ("<", operator.lt),
            (">", operator.gt),
            ("=", operator.eq),
        ):
            if case.startswith(prefix):
                op, case = candidate, case[len(prefix) :].strip()
                break
        value, wanted = notebook.value(switch), notebook.value(case)
        if value is None or wanted is None:
            return op is operator.eq and switch.strip() == case
        return op(value, wanted)

    def action(self, name: str, param: str, notebook: Notebook) -> bool:
        parts = param.split("|")
        if name in NOTE_PREDICATES:
            if len(parts) < 3:
                return False
            a, b, how = (notebook.value(p) for p in parts[:3])
            if a is None or b is None or how is None or int(how) not in COMPARE:
                return False
            return COMPARE[int(how)](a, b)
        if name == "CheckNote":
            return notebook.value(parts[0]) is not None
        if name in NOTE_SETTERS:
            if len(parts) >= 2 and (v := notebook.value(parts[1])) is not None:
                notebook.store(parts[0], v)
            return True
        if name == "DoAddInt":
            if len(parts) >= 3:
                a, b = notebook.value(parts[1]), notebook.value(parts[2])
                if a is not None and b is not None:
                    notebook.store(parts[0], a + b)
            return True
        handled = self.handler(name, parts, notebook)
        if handled is not None:
            return handled
        # Nobody knows this one. A check fails, anything else just gets on with it.
        return not name.startswith("Check")
