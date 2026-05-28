import unittest

from pgr_assets.sources.obbstarter import _obb_resource_map


class ObbResourceMapTest(unittest.TestCase):
    def test_includes_matrix_blobs(self):
        names = ["assets/resource/matrix/abc123", "assets/resource/matrix/def456"]
        result = _obb_resource_map(names)
        self.assertEqual(result["abc123"], "assets/resource/matrix/abc123")
        self.assertEqual(result["def456"], "assets/resource/matrix/def456")

    def test_includes_resources_assets_when_present(self):
        names = ["assets/resource/matrix/abc123", "assets/bin/Data/resources.assets"]
        result = _obb_resource_map(names)
        self.assertEqual(result["resources.assets"], "assets/bin/Data/resources.assets")

    def test_omits_resources_assets_when_absent(self):
        names = ["assets/resource/matrix/abc123"]
        result = _obb_resource_map(names)
        self.assertNotIn("resources.assets", result)


if __name__ == "__main__":
    unittest.main()
