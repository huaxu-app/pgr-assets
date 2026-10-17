import unittest

from pgr_assets.models.fashion import Fashion, index_characters
from pgr_assets.models.scope.weapons import resolve_show_rotations

PREFAB = "Assets/Product/Role/WeaponPrefab"


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
