import unittest

from pgr_assets.models.partnpc import ROOT, PartLink, join_fight_links, join_menu_links


class JoinFightLinksTest(unittest.TestCase):
    def test_nanami_and_friends(self):
        npc_models = {
            1054: "r4yongyechaobotmd010021",
            1055: "r4yongyechaomd010011",
            1056: "r4yongyechaomd010021",
            8544: "mb1huoshachairmd010001",
            8541: "mb1huoshamd010001",
            8400: "mb1hadisimd010001",
        }
        npc_parts = [
            (1055, 1054, "Bip001Spine1"),
            (1056, 1054, "Bip001Spine1"),
            (8541, 8544, "HuoshaSitCase"),
            (84001, 8400, "Bip001LHand"),
        ]
        overrides = [
            (1055, "r4yongyechaobotmd010011", "r4yongyechaomd010011"),
            (1055, "r4yongyechaobotmd010021", "r4yongyechaomd010021"),
        ]
        models = set(npc_models.values()) | {"r4yongyechaobotmd010011"}

        links = join_fight_links(npc_models, npc_parts, overrides, models)

        self.assertEqual(
            {
                "r4yongyechaobotmd010011": [PartLink("r4yongyechaomd010011", "Bip001Spine1")],
                "r4yongyechaobotmd010021": [PartLink("r4yongyechaomd010021", "Bip001Spine1")],
                "mb1huoshachairmd010001": [PartLink("mb1huoshamd010001", "HuoshaSitCase")],
            },
            links,
        )


    def test_two_parts_share_the_root(self):
        npc_models = {8048: "mortal", 8049: "mortalleft", 8050: "mortalright"}
        links = join_fight_links(
            npc_models, [(8049, 8048, ROOT), (8050, 8048, ROOT)], [], set(npc_models.values())
        )
        self.assertEqual(
            {"mortal": [PartLink("mortalleft", ROOT), PartLink("mortalright", ROOT)]}, links
        )

    def test_player_model_skips_a_borrowing_boss(self):
        npc_models = {5014: "jetavie", 5026: "commander"}
        models = {"jetavie", "commander"}
        rows = [(5026, 5014, ROOT)]
        self.assertEqual({}, join_fight_links(npc_models, rows, [], models, {"jetavie": {13410022, 1331}}))
        self.assertEqual(
            {"jetavie": [PartLink("commander", ROOT)]},
            join_fight_links(npc_models, rows, [], models, {"jetavie": {5014}}),
        )


class JoinMenuLinksTest(unittest.TestCase):
    def test_default_rows_with_both_models(self):
        rows = [
            ("r4yongyechaobotmd010011", "Default", "r4yongyechaobotmd010011", "r4yongyechaomd010011"),
            ("r4yongyechaobotmd010011", "UiMain", None, "r4yongyechaomd010011"),
            ("r4yongyechaobotmd010021", "UiMain", None, "r4yongyechaomd010021"),
        ]
        models = {"r4yongyechaobotmd010011", "r4yongyechaomd010011", "r4yongyechaomd010021"}

        self.assertEqual(
            {"r4yongyechaobotmd010011": [PartLink("r4yongyechaomd010011", ROOT)]},
            join_menu_links(rows, models),
        )


if __name__ == "__main__":
    unittest.main()
