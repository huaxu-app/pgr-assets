import unittest

from pgr_assets.models.prefab import Node, resolve_transform_paths


def tree(*parents: int | None) -> list[Node]:
    return [Node(f"n{i}", parent) for i, parent in enumerate(parents)]


class TransformPathTest(unittest.TestCase):
    def test_siblings_sharing_a_name_still_get_distinct_paths(self):
        nodes = tree(None, 0, 0, 1, 2)
        for node in nodes[1:]:
            node.name = "Hair"
        nodes[1].name, nodes[2].name = "Left", "Right"
        self.assertEqual(
            ["", "Left", "Right", "Left/Hair", "Right/Hair"],
            resolve_transform_paths(nodes),
        )


if __name__ == "__main__":
    unittest.main()
