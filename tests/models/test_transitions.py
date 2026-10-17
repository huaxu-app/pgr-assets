import unittest

from pgr_assets.models.transitions import (
    WILDCARD,
    Transitions,
    WildcardRule,
    index_rows,
)

ROWS = [
    (0, "", "Born", 0.0),
    (0, "", "Stand1", 0.1),
    (0, "", "Attack02", 0.2),
    (0, "Attack01", "Attack02", 0.05),
    (0, "Attack01", "Stand1", 0.1),
    (1, "", "Stand1", 0.3),
]


def transition_duration(
    transitions: Transitions, layer: int, source: str | None, target: str
) -> float:
    """
    The engine's GetAnimationTransitionInternal, both paths, straight off the rows.
    """
    buckets = transitions.layers.get(layer)
    if buckets is None or not target:
        return transitions.default
    source = source or WILDCARD
    if transitions.wildcard is WildcardRule.FALLBACK:
        for key in (source, WILDCARD):
            found = buckets.get(key, {}).get(target)
            if found is not None:
                return found
        return transitions.default
    bucket = buckets.get(source)
    if bucket is None:
        bucket = buckets.get(WILDCARD)
    if bucket is None:
        return transitions.default
    return bucket.get(target, transitions.default)


class TransitionsTest(unittest.TestCase):
    def test_classic_lookup_gives_up_inside_the_source_bucket(self):
        # A bucket for the state left exists, so the wildcard is never consulted.
        table = Transitions(0.1, WildcardRule.OWN_ROW_ONLY, index_rows(ROWS))
        self.assertEqual(transition_duration(table, 0, "Attack01", "Attack02"), 0.05)
        self.assertEqual(transition_duration(table, 0, "Attack01", "Born"), 0.1)
        self.assertEqual(transition_duration(table, 0, "Stand1", "Attack02"), 0.2)
        self.assertEqual(transition_duration(table, 0, None, "Born"), 0.0)
        self.assertEqual(transition_duration(table, 2, "Stand1", "Born"), 0.1)

    def test_new_path_falls_back_to_the_wildcard_per_target(self):
        table = Transitions(0.1, WildcardRule.FALLBACK, index_rows(ROWS))
        self.assertEqual(transition_duration(table, 0, "Attack01", "Born"), 0.0)
        self.assertEqual(transition_duration(table, 0, "Attack01", "Attack02"), 0.05)
        self.assertEqual(transition_duration(table, 0, "Attack01", "Death"), 0.1)

    def test_the_resolved_table_answers_like_either_path(self):
        def lookup(row, layer, source, target):
            rows = row["layers"][layer] if layer < len(row["layers"]) else {}
            for key in (source or "*", "*"):
                found = rows.get(key, {}).get(target)
                if found is not None:
                    return found
            return row["default"]

        states = [None, "Attack01", "Stand1", "Death"]
        targets = ["Born", "Stand1", "Attack02", "Death"]
        for rule in WildcardRule:
            table = Transitions(0.1, rule, index_rows(ROWS))
            row = table.as_dict()
            for layer in (0, 1, 2):
                for source in states:
                    for target in targets:
                        self.assertEqual(
                            transition_duration(table, layer, source, target),
                            lookup(row, layer, source, target),
                            (rule, layer, source, target),
                        )
