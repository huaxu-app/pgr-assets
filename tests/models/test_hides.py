import unittest

from pgr_assets.models.fashion import Fashion
from pgr_assets.models.spawn.behavior import ACTION
from pgr_assets.models.spawn.fighttables import Npc, TreeNode
from pgr_assets.models.spawn.hides import collect_spawn_hides
from tests.models.test_npcstate import _tables


class SpawnHidesTest(unittest.TestCase):
    def test_only_the_characters_own_npc_rows_count(self):
        # npc 20011 belongs to character 2001, npc 555 is a story version reusing the model
        nodes = {1: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ())}
        tables = _tables(
            nodes, [Npc(20011, 7, "r1model", (100,)), Npc(555, 7, "r1model", (202,))]
        )
        self.assertEqual(
            {"r1model": ("WeaponCase1",)},
            collect_spawn_hides(tables, [Fashion(6001, 2001, "r1model")]),
        )
