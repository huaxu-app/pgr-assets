import unittest

from pgr_assets.models.scope.dorm import read_dorm_entries

ROOM = "Assets/Product/Role/Room/Prefab"


class DormNamesTest(unittest.TestCase):
    def test_uimodel_contexts_take_the_full_lowercased_id(self):
        styles = [{"Id": 1001, "Model": f"{ROOM}/R1LifuMd010011.prefab"}]
        uimodels = [
            {
                "Id": "R1LifuMd010011TX",
                "ModelPath": f"{ROOM}/R1LifuMd010011.prefab",
                "DisplayControllerPath": None,
                "UiDefaultAnimationPath": f"{ROOM}/R1LifuMd010011/Stand02.anim",
            }
        ]
        (entry,) = read_dorm_entries(styles, uimodels)
        self.assertEqual(["dorm", "r1lifumd010011tx"], list(entry.contexts))
