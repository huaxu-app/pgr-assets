import gc
import io
import shutil
import tempfile
import unittest
import weakref

from UnityPy.files import BundleFile, SerializedFile

from pgr_assets.lazyenv import MEM_FACTOR, LazyEnv

SIZES = {"a": 100, "b": 200, "c": 400}
FLAT: dict[str, list[str]] = {"a": [], "b": [], "c": []}


class FakeStore:
    def __init__(self, sizes: dict[str, int], cache_dir: str):
        self._sizes = sizes
        self.cache_dir = cache_dir

    def size(self, bundle: str) -> int:
        return self._sizes.get(bundle, 0)

    def ensure(self, bundle: str) -> None:
        pass

    def open(self, bundle: str) -> io.BytesIO:
        return io.BytesIO(b"")


class FakeSerialized(SerializedFile):
    def __init__(self):
        self._cache = {"stale": 1}


class FakeRawReader:
    """
    A bundle's .resS node: registered as a cab, not a SerializedFile.
    """


class FakeBundleFile(BundleFile):
    def __init__(self, name: str):
        self.files = {
            f"CAB-{name}": FakeSerialized(),
            f"CAB-{name}.resS": FakeRawReader(),
        }


class FakeEnv(LazyEnv):
    def __init__(self, store, catalog, graph, budget_mb=2048):
        super().__init__(store, catalog, budget_mb=budget_mb)
        self._graph = graph
        self.parsed: list[str] = []

    def load_assets(self, assets, open_f):
        for name in assets:
            open_f(name)
            self.parsed.append(name)
            self.files[name] = FakeBundleFile(name)
            for cab, f in self.files[name].files.items():
                self.register_cab(cab, f)

    def _queue_deps(self, loaded):
        for name in loaded:
            for dep in self._graph.get(name, []):
                if dep not in self._lru and dep in self._catalog:
                    self._pending.add(dep)


class EnvTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def env(self, graph, resident_bytes=None):
        budget_mb = (
            2048 if resident_bytes is None else resident_bytes * MEM_FACTOR / 1e6
        )
        return FakeEnv(FakeStore(SIZES, self.dir), set(graph), graph, budget_mb)


class ResidencyTest(EnvTestCase):
    def test_evicts_least_recent_first(self):
        env = self.env(FLAT, resident_bytes=600)
        env.require("a")
        env.require("b")
        env.require("c")
        self.assertNotIn("a", env._lru)
        self.assertEqual(["b", "c"], list(env._lru))

    def test_pins_survive_until_the_target_ends(self):
        env = self.env(FLAT, resident_bytes=300)
        env.require("a")
        with env.pin("a"):
            env.require("b")
            env.require("c")
            self.assertIn("a", env._lru)
            self.assertGreater(env.resident_bytes, env._budget)
        self.assertLessEqual(env.resident_bytes, env._budget)


class LivenessTest(EnvTestCase):
    def test_eviction_frees_the_reader(self):
        env = self.env(FLAT, resident_bytes=600)
        env.require("a")
        ref = weakref.ref(env.files["a"].files["CAB-a"])

        env.require("b")
        env.require("c")
        gc.collect()
        self.assertIsNone(ref())


if __name__ == "__main__":
    unittest.main()
