import unittest

from pgr_assets.models.fashion import Fashion, index_characters
from pgr_assets.models.registry import ModelEntry, Registry
from pgr_assets.models.scope.characters import (
    CharacterEntry,
    attach_ui_rows,
    pick_default_context,
)
from pgr_assets.models.scope.weapons import resolve_show_rotations

PREFAB = "Assets/Product/Role/WeaponPrefab"
CHARA = "Assets/Product/Role/CharaterPrefab"


def transform(index: int, screen: str, rotation: tuple[float, float, float]) -> dict:
    x, y, z = rotation
    return {
        "IndexId": index,
        "UiName": screen,
        "RotationX": x,
        "RotationY": y,
        "RotationZ": z,
    }


class ShowRotationsTest(unittest.TestCase):
    def test_two_classes_keep_the_first(self):
        models = [{"Id": 10, "ModelName": {1: f"{PREFAB}/E1GunMd030011.prefab"}}]
        transforms = [
            transform(1, "UiEquipDetail", (50.0, 0.0, 20.0)),
            transform(2, "UiEquipDetail", (0.0, 90.0, 0.0)),
        ]
        with self.assertLogs("pgr-assets", "WARNING"):
            found = resolve_show_rotations(models, [(10, 2), (10, 1)], transforms)
        self.assertEqual({"e1gunmd030011": (50.0, 0.0, 20.0)}, found)


class FashionCharactersTest(unittest.TestCase):
    def test_model_two_characters_reach_is_dropped(self):
        fashions = [
            Fashion(1, 10, "shared"),
            Fashion(2, 20, "shared"),
            Fashion(3, 10, "own"),
            Fashion(4, 10, "own"),
        ]
        self.assertEqual({"own": 10}, index_characters(fashions))

class RegistryPartsTest(unittest.TestCase):
    def test_select_pulls_parts_in(self):
        registry = Registry(
            [ModelEntry(i, f"{i}.prefab") for i in ("a", "b", "c")], parts={"a": {"c", "gone"}}
        )
        self.assertEqual(["a", "c"], [e.id for e in registry.select(["a"])])
        self.assertEqual(["b"], [e.id for e in registry.select(["b"])])



def ui_row(row_id: str, stem: str, hides: tuple[str, ...] = ()) -> dict:
    return {
        "Id": row_id,
        "ModelPath": f"{CHARA}/{stem}.prefab",
        "HXModelPath": None,
        "ControllerPath": None,
        "DisplayControllerPath": None,
        "UiDefaultAnimationPath": f"{CHARA}/{stem}/UiStand1.anim",
        "HideNodeName": list(hides),
    }


class AttachUiRowsTest(unittest.TestCase):
    def test_rows_land_on_their_prefab_with_raw_names(self):
        known = [
            CharacterEntry(
                id="mb1bossmd010001",
                model_path=f"{CHARA}/Mb1BossMd010001.prefab".lower(),
            )
        ]
        rows = [
            ui_row("Mb1BossMd010001UI", "Mb1BossMd010001", ("Mb1BossMd010002Wing",)),
            ui_row("Mb1BossMd010001UI2", "Mb1BossMd010001", ("Mb1BossMd010001Body",)),
        ]
        (entry,) = attach_ui_rows(rows, known)
        self.assertEqual(
            ["mb1bossmd010001ui", "mb1bossmd010001ui2"], [r.id for r in entry.ui_rows]
        )
        self.assertEqual(("Mb1BossMd010002Wing",), entry.ui_rows[0].hide_names)

    def test_a_ui_only_prefab_gets_an_entry_with_every_row(self):
        rows = [
            ui_row("Mb1SoloMd010001UI1", "Mb1SoloMd010001"),
            ui_row("Mb1SoloMd010001UI2", "Mb1SoloMd010001"),
        ]
        (entry,) = attach_ui_rows(rows, [])
        self.assertEqual("mb1solomd010001", entry.id)
        self.assertEqual(2, len(entry.ui_rows))

    def test_rows_outside_charaterprefab_are_ignored(self):
        row = ui_row("R1RoomMd000001TX", "R1RoomMd000001")
        row["ModelPath"] = "Assets/Product/Role/Room/Prefab/R1RoomMd000001.prefab"
        self.assertEqual([], attach_ui_rows([row], []))


class DefaultContextTest(unittest.TestCase):
    def test_order_is_stem_then_ui_then_ui1_then_menu(self):
        cases = [
            ("mb1amd010001", "mb1amd010001", {"mb1amd010001", "mb1amd010001ui"}),
            ("mb1bmd010001ui", "mb1bmd010001", {"mb1bmd010001ui2", "mb1bmd010001ui"}),
            ("mb1cmd010001ui1", "mb1cmd010001", {"mb1cmd010001ui2", "mb1cmd010001ui1"}),
            ("menu", "mb1dmd010001", {"mb1dmd010001dw"}),
            ("menu", "mb1emd010001", set()),
        ]
        for wanted, stem, rows in cases:
            path = f"{CHARA}/{stem}.prefab"
            names = {"fight", "menu", *rows}
            self.assertEqual(wanted, pick_default_context(path, rows, names))

    def test_a_deduped_row_opens_menu_not_the_next_row(self):
        path = f"{CHARA}/mb1fmd010001.prefab"
        rows = {"mb1fmd010001ui", "mb1fmd010001ui1"}
        names = {"fight", "menu", "mb1fmd010001ui1"}
        self.assertEqual("menu", pick_default_context(path, rows, names))
