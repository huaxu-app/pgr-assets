from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from pgr_assets.models.clips import ClipSource
from pgr_assets.tables import TableRow


@dataclass(frozen=True)
class ModelEntry:
    """
    One buildable target. Each scope extends it with what its tables know.
    """

    # A model_key for characters, the lowered prefab stem for weapons and chibis.
    id: str
    model_path: str

    def list_clip_sources(self) -> list[ClipSource]:
        return []


class Registry[E: ModelEntry]:
    def __init__(
        self,
        entries: Iterable[E],
        characters: Collection[str] = (),
        parts: Mapping[str, Collection[str]] | None = None,
    ):
        self._entries = {entry.id: entry for entry in entries}
        # The entries a character reaches, where the scope knows.
        self.characters = frozenset(characters).intersection(self._entries)
        # Picking a main picks what the game hangs on it
        self._parts = {
            main: sorted(set(targets).intersection(self._entries))
            for main, targets in (parts or {}).items()
        }

    def __len__(self) -> int:
        return len(self._entries)

    def select(self, filters: Sequence[str] = ()) -> list[E]:
        """
        Filters OR together as substrings. An exact id selects only itself.
        """
        if not filters:
            return [self._entries[i] for i in sorted(self._entries)]

        picked: set[str] = set()
        for raw in filters:
            wanted = raw.strip().lower()
            if wanted in self._entries:
                picked.add(wanted)
                continue
            picked.update(i for i in self._entries if wanted in i)
        picked.update(part for main in list(picked) for part in self._parts.get(main, ()))
        return [self._entries[i] for i in sorted(picked)]


def read_text(row: TableRow, column: str) -> str | None:
    value = row.get(column)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def read_paths(row: TableRow, column: str) -> tuple[str, ...]:
    value = row.get(column)
    if not isinstance(value, list):
        return ()
    return tuple(p.strip().lower() for p in value if isinstance(p, str) and p.strip())


def resolve_stem(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".prefab").removesuffix(".controller")
