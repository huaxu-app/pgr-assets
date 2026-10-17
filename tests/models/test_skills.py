import unittest

from pgr_assets.models.skills import map_skill_states


class SkillStatesTest(unittest.TestCase):
    def test_join(self) -> None:
        states = map_skill_states(
            character_groups=[(1531005, [1535060, 1535160, 1535180, 1535220])],
            group_skills={
                1535060: [153506],
                1535160: [153516],
                1535180: [153518],
                1535220: [153522],
            },
            level_subskills=[
                (15350601, [112510, 112511, 112512]),
                (15350602, [112510, 112511, 112512]),
                (15351601, [112501, 112527]),
                (15351801, [112523]),
                (15352201, []),
            ],
            animations={
                112501: "Attack01",
                112510: "Attack21",
                112511: "Attack21",
                112512: "Attack21",
                112523: "Attack21",
                112527: "Attack41",
            },
        )
        self.assertEqual(
            states,
            {
                1531005: {
                    "Attack21": (153506, 153518),
                    "Attack01": (153516,),
                    "Attack41": (153516,),
                }
            },
        )

    def test_leap_follows_normal(self) -> None:
        states = map_skill_states(
            character_groups=[(1521003, [1522010]), (1521003, [1522280])],
            group_skills={1522010: [152201], 1522280: [152228]},
            level_subskills=[(15220101, [1]), (15222801, [2, 3])],
            animations={1: "Attack11", 2: "Attack11", 3: "Executioner01"},
        )
        self.assertEqual(
            states,
            {1521003: {"Attack11": (152201, 152228), "Executioner01": (152228,)}},
        )


if __name__ == "__main__":
    unittest.main()
