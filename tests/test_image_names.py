import unittest

from pgr_assets.image_names import (
    find_ambiguous_images,
    make_image_reference,
    resolve_image_stems,
)

CG = "assets/product/texture/image/bgcg/cg6701_50"
BGSTORY = "assets/product/texture/image/bgstory/bgstory1625"


class FindAmbiguousImagesTest(unittest.TestCase):
    def test_reports_only_stems_claimed_twice(self):
        found = find_ambiguous_images(
            [f"{CG}.jpg.ab", f"{CG}.png.ab", f"{BGSTORY}.jpg.ab"]
        )

        self.assertEqual({CG: ".jpg"}, found)

    def test_picks_one_winner_from_three_claims(self):
        found = find_ambiguous_images([f"{CG}.jpg.ab", f"{CG}.png.ab", f"{CG}.tga.ab"])

        self.assertEqual({CG: ".jpg"}, found)

    def test_collides_across_casing(self):
        found = find_ambiguous_images([f"{CG}.JPG.ab", f"{CG.upper()}.png.ab"])

        self.assertEqual({CG: ".jpg"}, found)

    def test_ignores_non_texture_and_non_image_bundles(self):
        found = find_ambiguous_images(
            [
                "assets/temp/bytes/client/movie.ab",
                "assets/product/texture/image/foo.ab",
            ]
        )

        self.assertEqual({}, found)


class ResolveImageStemsTest(unittest.TestCase):
    def test_unclaimed_stem_keeps_the_bare_name(self):
        self.assertEqual([BGSTORY], resolve_image_stems(f"{BGSTORY}.jpg", {}))

    def test_winner_gets_both_the_bare_and_qualified_name(self):
        self.assertEqual(
            [CG, f"{CG}.jpg"], resolve_image_stems(f"{CG}.jpg", {CG: ".jpg"})
        )

    def test_loser_only_gets_the_qualified_name(self):
        self.assertEqual([f"{CG}.png"], resolve_image_stems(f"{CG}.png", {CG: ".jpg"}))

    def test_drops_an_unrecognized_extension_from_an_uncontested_path(self):
        self.assertEqual(
            ["assets/product/common/grid"],
            resolve_image_stems("assets/product/common/grid.tga", {}),
        )

    def test_falls_back_to_the_bare_name_when_the_stem_is_unknown(self):
        # Collisions are keyed on bundle names, stems come from container paths.
        # Those agree today, and a disagreement must degrade, not corrupt.
        self.assertEqual([CG], resolve_image_stems(f"{CG}.jpg", {"other": ".jpg"}))


class MakeImageReferenceTest(unittest.TestCase):
    def test_matches_kennels_reference_form(self):
        self.assertEqual("image/bgcg/cg6701_50", make_image_reference(CG))


if __name__ == "__main__":
    unittest.main()
