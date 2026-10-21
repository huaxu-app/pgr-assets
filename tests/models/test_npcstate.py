import unittest

from pgr_assets.models.spawn.behavior import (
    ACTION,
    CASE,
    PARALLEL,
    SELECTOR,
    SEQUENCE,
    SWITCH,
)
from pgr_assets.models.spawn.fighttables import (
    Buff,
    FightTables,
    Magic,
    Npc,
    TreeNode,
    read_keyframe_magics,
)
from pgr_assets.models.spawn.npcstate import Facts, simulate_spawn


def _tables(nodes: dict[int, TreeNode], npcs: list[Npc] | None = None) -> FightTables:
    return FightTables(
        npcs=npcs or [],
        prefix_roots={10: 1},
        nodes=nodes,
        magic={
            100: Magic("AddBehavior", ("10",)),
            201: Magic("AddBuff", ("301",)),
            202: Magic("AddBuff", ("302",)),
            203: Magic("AddBuff", ("303",)),
            301000: Magic("HideJoint", ("WeaponCase1",)),
            302000: Magic("HideJoints", ("Hair2;Glove2",)),
            303000: Magic("HideJoint", ("Blink",)),
        },
        buffs={
            301: Buff((301000,), -1.0, 3010, ()),
            302: Buff((302000,), -1.0, 3020, ()),
            303: Buff((303000,), 0.15, 3030, ()),
        },
        skills={5: (202,)},
    )


class SpawnTest(unittest.TestCase):
    def test_only_the_taken_branch_hides_and_removals_by_kind_show_again(self):
        # form note is 0, so the first branch runs: hide case 1, then remove it, hide hair
        nodes = {
            1: TreeNode(PARALLEL, False, "", "", (2, 3)),
            2: TreeNode(ACTION, False, "DoSetInt", "2#7|0", ()),
            3: TreeNode(SELECTOR, False, "", "", (4, 7)),
            4: TreeNode(SEQUENCE, False, "", "", (5, 6, 8, 9)),
            5: TreeNode(ACTION, False, "CheckIntCompareInt", "2#7|0|1", ()),
            6: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ()),
            8: TreeNode(ACTION, False, "DoRemoveBuffByKindEx", "1#2001|3010|0", ()),
            9: TreeNode(ACTION, False, "DoCastSkill", "1#2001|5", ()),
            7: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ()),
        }
        state = simulate_spawn(_tables(nodes), [100])
        self.assertEqual({"Glove2", "Hair2"}, state.collect_hidden_tags())

    def test_expiring_buffs_and_other_targets_do_not_count(self):
        nodes = {
            1: TreeNode(PARALLEL, False, "", "", (2, 3)),
            2: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|203", ()),
            3: TreeNode(ACTION, False, "DoMagic", "2#9|2#9|0|201", ()),
        }
        self.assertEqual(
            set(), simulate_spawn(_tables(nodes), [100]).collect_hidden_tags()
        )

    def test_a_seeded_fact_picks_the_skin_branch(self):
        nodes = {
            1: TreeNode(SEQUENCE, False, "", "", (2, 3, 4)),
            2: TreeNode(ACTION, False, "DoGetNpcFashionId", "1#2001|1#95105", ()),
            3: TreeNode(ACTION, False, "CheckInt", "1#95105|6006104|1", ()),
            4: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ()),
        }
        self.assertEqual(
            set(), simulate_spawn(_tables(nodes), [100]).collect_hidden_tags()
        )
        self.assertEqual(
            {"WeaponCase1"},
            simulate_spawn(
                _tables(nodes), [100], Facts(fashion_id=6006104)
            ).collect_hidden_tags(),
        )

    def test_a_negative_note_key_is_written_and_read_back(self):
        nodes = {
            1: TreeNode(SEQUENCE, False, "", "", (2, 3, 4, 5)),
            2: TreeNode(ACTION, False, "DoSetInt", "2#-1064|1", ()),
            3: TreeNode(ACTION, False, "CheckNote", "2#-1064", ()),
            4: TreeNode(ACTION, False, "CheckInt", "2#-1064|1|1", ()),
            5: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ()),
        }
        self.assertEqual(
            {"WeaponCase1"}, simulate_spawn(_tables(nodes), [100]).collect_hidden_tags()
        )

    def test_unknown_predicate_blocks_its_branch(self):
        nodes = {
            1: TreeNode(SEQUENCE, False, "", "", (2, 3)),
            2: TreeNode(ACTION, False, "CheckNpcInRange", "1#2001|3", ()),
            3: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ()),
        }
        self.assertEqual(
            set(), simulate_spawn(_tables(nodes), [100]).collect_hidden_tags()
        )

    def test_a_switch_case_on_a_note_and_a_relational_case(self):
        nodes = {
            1: TreeNode(SEQUENCE, False, "", "", (2, 3)),
            2: TreeNode(ACTION, False, "DoSetInt", "1#7|3", ()),
            3: TreeNode(SWITCH, False, "DoSwitchCode", "1#7", (4, 6)),
            4: TreeNode(CASE, False, "DoCaseCode", "1", (5,)),
            5: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ()),
            6: TreeNode(CASE, False, "DoCaseCode", ">2", (7,)),
            7: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|202", ()),
        }
        self.assertEqual(
            {"Glove2", "Hair2"},
            simulate_spawn(_tables(nodes), [100]).collect_hidden_tags(),
        )

    def test_nobody_is_mid_show_at_spawn_and_negative_flips_it(self):
        nodes = {
            1: TreeNode(SELECTOR, False, "", "", (2, 4)),
            2: TreeNode(SEQUENCE, False, "", "", (3,)),
            3: TreeNode(ACTION, False, "DoCheckNpcShowState", "1#2001|1#11243001", ()),
            4: TreeNode(SEQUENCE, False, "", "", (5, 6)),
            5: TreeNode(ACTION, True, "DoCheckNpcShowStateEx", "1#2001", ()),
            6: TreeNode(ACTION, False, "DoMagic", "1#2001|1#2001|0|201", ()),
        }
        self.assertEqual(
            {"WeaponCase1"}, simulate_spawn(_tables(nodes), [100]).collect_hidden_tags()
        )


class KeyframeTest(unittest.TestCase):
    def test_entry_magics_go_in_frame_order_and_guarded_ones_stay_out(self):
        keys = [
            "100|Magic|190841|0|",
            "0|Effect|FxBorn|||",
            "45|Magic|190843|0|",
            "10|Magic|182394|0|",
        ]
        conditions = ["nil", "nil", "nil", "1823960"]
        self.assertEqual([190843, 190841], read_keyframe_magics(keys, conditions))
