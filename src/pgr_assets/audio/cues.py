from collections.abc import Iterable, Mapping
from typing import Any

from pgr_assets.audio.paths import cue_path, sheet_base_name

LANGUAGES = ("jp", "zh", "ca", "en")

Sound = str | dict[str, str]


class CueIndex:
    def __init__(self, cues: dict[int, str], voices: dict[int, list[int]]) -> None:
        self._cues = cues
        self._voices = voices

    @classmethod
    def from_rows(
        cls,
        sheets: Iterable[Mapping[str, Any]],
        cues: Iterable[Mapping[str, Any]],
        voices: Iterable[Mapping[str, Any]],
    ) -> "CueIndex":
        bases = {
            int(row["Id"]): sheet_base_name(row["CueSheetName"])
            for row in sheets
            if row.get("CueSheetName")
        }
        paths = {
            int(row["Id"]): cue_path(bases[int(row["CueSheetId"])], row["CueName"])
            for row in cues
            if int(row["CueSheetId"]) in bases and row.get("CueName")
        }
        return cls(
            paths,
            {
                int(row["Id"]): [int(c or 0) for c in row.get("Cvs") or ()]
                for row in voices
            },
        )

    def cue(self, cue_id: int) -> str | None:
        return self._cues.get(cue_id)

    def voice(self, cv_id: int) -> Sound | None:
        found: dict[str, str] = {}
        for language, cue_id in zip(LANGUAGES, self._voices.get(cv_id, ())):
            path = self._cues.get(cue_id)
            if path is not None:
                found[language] = path
        if not found:
            return None
        if len(set(found.values())) == 1:
            return next(iter(found.values()))
        return found
