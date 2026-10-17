import unittest

from pgr_assets.models.context import convert_rotation, resolve_joint
from pgr_assets.models.prefab import Node, ObjectTag
from pgr_assets.models.scope.characters import CharacterEntry, read_contexts


def _nodes(*spec: tuple[str, int | None]) -> list[Node]:
    return [Node(name=name, parent=parent) for name, parent in spec]


class ResolveJointTest(unittest.TestCase):
    def test_tag_wins_even_over_a_node_with_the_wanted_name(self):
        nodes = _nodes(("Root", None), ("WeaponCase2", 0), ("WeaponCase3", 0))
        tags = [ObjectTag(name="WeaponCase2", nodes=[2])]
        self.assertEqual(2, resolve_joint("WeaponCase2", nodes, tags))

    def test_a_repeated_tag_resolves_to_the_last_row(self):
        nodes = _nodes(("Root", None), ("WeaponCase2", 0), ("WeaponCase3", 0))
        tags = [
            ObjectTag(name="WeaponCase2", nodes=[1]),
            ObjectTag(name="WeaponCase2", nodes=[2]),
        ]
        self.assertEqual(2, resolve_joint("WeaponCase2", nodes, tags))

    def test_without_a_tag_the_shallowest_name_wins(self):
        nodes = _nodes(
            ("Root", None),
            ("Bip001", 0),
            ("Prop1", 1),
            ("WeaponCase1", 2),
            ("WeaponCase1", 1),
        )
        self.assertEqual(4, resolve_joint("WeaponCase1", nodes, []))


class SkillMountTest(unittest.TestCase):
    def test_the_ex_case_rides_with_its_mount_and_is_none_elsewhere(self):
        nodes = _nodes(
            ("Root", None),
            ("Bip001", 0),
            ("WeaponCase1", 1),
            ("Bip001Prop1", 1),
            ("WeaponCaseEx1", 3),
            ("WeaponCase2", 1),
        )
        entry = CharacterEntry(id="r3twob", model_path="r3twob.prefab")
        fight, menu = read_contexts(entry, nodes, [], set(), ())
        self.assertEqual(
            [(m.slot, m.node, m.skill_node) for m in fight.mounts],
            [(1, 2, 4), (2, 5, None)],
        )
        self.assertEqual([m.skill_node for m in menu.mounts], [4, None])


class ConvertRotationTest(unittest.TestCase):
    def test_unity_yaw_turns_the_other_way_in_gltf(self):
        x, y, z, w = convert_rotation((0.0, 90.0, 0.0))
        self.assertAlmostEqual(0.0, x)
        self.assertAlmostEqual(-(0.5**0.5), y, places=6)
        self.assertAlmostEqual(0.0, z)
        self.assertAlmostEqual(0.5**0.5, w, places=6)
