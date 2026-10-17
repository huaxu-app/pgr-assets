import logging
import os
from collections import OrderedDict
from collections.abc import Collection, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

import UnityPy
from UnityPy.environment import simplify_name
from UnityPy.files import BundleFile

from pgr_assets.models.cabmap import CabMap
from pgr_assets.models.unity import list_dependencies, list_serialized_files
from pgr_assets.sources import SourceSet
from pgr_assets.store import BundleStore

logger = logging.getLogger("pgr-assets")

PREFETCH_WORKERS = 16

# Roughly how much a loaded bundle outweighs its file on disk.
MEM_FACTOR = 3


class ModelEnv(UnityPy.Environment):
    """
    A UnityPy environment that loads bundles on demand and evicts them under a
    byte budget.

    Bundles arrive by explicit `require`, which also pulls their declared
    dependencies one level deep. Pointers reaching further are resolved by
    `find_file`, which expands the pending frontier rather than searching the
    filesystem.

    This class owns and violates every piece of UnityPy internals. Read
    objects through `find_object` and `list_paths`. Don't touch `files`,
    `cabs`, `container` or `load_assets` themselves. `container` in particular
    rebuilds itself across every resident cab per access and derefs every
    preload table while doing so, which faults in the whole dependency closure.

    Or do, I'm not your mom and I don't particularly mind your code exploding on you.
    """

    def __init__(
        self,
        store: BundleStore,
        catalog: Collection[str],
        budget_mb: float = 2048,
    ) -> None:
        super().__init__(path="")
        self._store = store
        self._catalog = set(catalog)
        self._budget = int(budget_mb * 1e6 / MEM_FACTOR)
        self._lru: OrderedDict[str, int] = OrderedDict()
        self._pinned: set[str] = set()
        self._touched: set[str] = set()
        self._pending: set[str] = set()
        self._unavailable: set[str] = set()
        self._cab_map = CabMap(os.path.join(store.cache_dir, ".meta", "cabs.msgpack"))

    def __contains__(self, bundle: str) -> bool:
        return bundle.lower() in self._catalog

    def require(self, *bundles: str) -> None:
        """
        Make bundles resident and queue their declared dependencies.
        """
        self._touched.update(b.lower() for b in bundles)
        fresh = self._admit(bundles)
        self._queue_deps(fresh)
        self._trim(protect=frozenset(b.lower() for b in bundles))

    @contextmanager
    def pin(self, *bundles: str) -> Iterator[None]:
        """
        Pin bundles against eviction for one target's build, with `touched`
        starting over from them. Trims back to budget on the way out.
        """
        self._touched = {b.lower() for b in bundles}
        self._pinned.update(b.lower() for b in bundles)
        try:
            yield
        finally:
            self._pinned.clear()
            self._trim()

    @property
    def resident(self) -> frozenset[str]:
        return frozenset(self._lru)

    @property
    def resident_bytes(self) -> int:
        return sum(self._lru.values())

    @property
    def touched(self) -> frozenset[str]:
        return frozenset(self._touched)

    @property
    def sources(self) -> SourceSet:
        return self._store.sources

    def find_object(self, bundle: str, path: str) -> Any:
        """
        Read one object by container path out of a resident bundle.
        """
        self._touched.add(bundle.lower())
        for serialized in list_serialized_files(self.files[bundle.lower()]).values():
            pointer = serialized.container.container_dict.get(path)
            if pointer is not None:
                return pointer.read()

        raise KeyError(f"{path} not in {bundle}")

    def list_paths(self, bundle: str) -> list[str]:
        self._touched.add(bundle.lower())
        paths: list[str] = []
        for serialized in list_serialized_files(self.files[bundle.lower()]).values():
            paths += serialized.container.keys()
        return paths

    def find_file(self, name: str, is_dependency: bool = True) -> Any:
        """
        Resolve a pointer into a bundle that is not resident yet.

        Expands the pending frontier one level at a time until the cab shows up,
        instead of UnityPy's filesystem walk.
        """
        simple = simplify_name(name)
        cab = self.get_cab(simple)
        if cab is None:
            owner = self._cab_map.get(simple)
            if owner is not None and owner not in self._lru:
                self._queue_deps(self._admit([owner]))
            while (cab := self.get_cab(simple)) is None and self._pending:
                self._queue_deps(self._admit(sorted(self._pending)))
            if cab is None:
                raise FileNotFoundError(
                    f"No resident or reachable bundle provides {name}"
                )
            self._trim()
        if (owner := self._cab_map.get(simple)) is not None:
            self._touched.add(owner)
        return cab

    def _admit(self, bundles: Iterable[str]) -> list[str]:
        """
        Fetch and parse whichever of *bundles* are not resident. Returns those.
        """
        wanted = []
        for name in bundles:
            lowered = name.lower()
            if lowered in self._lru:
                self._lru.move_to_end(lowered)
                self._pending.discard(lowered)
                continue
            if lowered not in self._catalog:
                self._warn_unavailable(lowered)
                self._pending.discard(lowered)
                continue
            wanted.append(lowered)

        if not wanted:
            return []

        with ThreadPoolExecutor(PREFETCH_WORKERS) as pool:
            list(pool.map(self._store.ensure, wanted))

        fresh = []
        for name in wanted:
            self.load_assets([name], self._store.open)
            size = self._store.size(name)
            self._lru[name] = size
            self._lru.move_to_end(name)
            self._record_cabs(name)
            self._pending.discard(name)
            fresh.append(name)

            # Trim per bundle, protecting this batch. Otherwise a cold frontier
            # expansion pulls a whole BFS level before anything is enforced.
            self._trim(protect=frozenset(wanted))

        return fresh

    def _record_cabs(self, bundle: str) -> None:
        for cab in list_serialized_files(self.files[bundle]):
            self._cab_map[simplify_name(cab)] = bundle

    def _queue_deps(self, loaded: list[str]) -> None:
        """
        Record the declared dependencies of freshly loaded bundles as pending.
        """
        for name in loaded:
            for dep in list_dependencies(self.files[name]):
                if dep in self._lru:
                    continue
                if dep in self._catalog:
                    self._pending.add(dep)
                else:
                    self._warn_unavailable(dep)

    def _warn_unavailable(self, bundle: str) -> None:
        if bundle in self._unavailable:
            return
        self._unavailable.add(bundle)
        logger.warning(f"Dependency not in catalog: {bundle}")

    def close(self) -> None:
        self._cab_map.save()

    def _trim(self, protect: frozenset[str] = frozenset()) -> None:
        keep = self._pinned | protect
        while self.resident_bytes > self._budget:
            victim = next((b for b in self._lru if b not in keep), None)
            if victim is None:
                break
            self._drop(victim)

    def _drop(self, bundle: str) -> None:
        bundle_file = self.files.pop(bundle, None)
        if bundle_file is None:
            self._lru.pop(bundle, None)
            return

        # Every node registered as a cab has to go, not just the parsed ones.
        if isinstance(bundle_file, BundleFile):
            for cab in bundle_file.files:
                self.cabs.pop(simplify_name(str(cab)), None)
        for serialized in list_serialized_files(bundle_file).values():
            serialized._cache.clear()

        self._lru.pop(bundle, None)
