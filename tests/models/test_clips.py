import gc
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from pgr_assets.lazyenv import LazyEnv
from pgr_assets.models.clips import read_clips
from pgr_assets.models.controllers import _find_nearest, read_controller
from pgr_assets.models.files import Publisher
from pgr_assets.models.manifest import walk_ui_chain
from pgr_assets.models.scope.characters import CharacterEntry
from pgr_assets.models.webclip import ClipWriter

CONTROLLER = "assets/product/role/animation/r/r/r.controller"
CONTROLLER_AB = "assets/product/role/animation/r/r.ab"


def _read(env, entry):
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(1) as pool:
        writer = ClipWriter(Publisher(tmp, 0, pool), [], set(), {}, set())
        return read_clips(env, entry.id, entry.list_clip_sources(), [""], writer)


def node(clip_id):
    return SimpleNamespace(data=SimpleNamespace(m_ClipID=clip_id))


def blend_tree(*clip_ids):
    nodes = [node(c) for c in clip_ids]
    if len(nodes) > 1:
        # A Simple1D root over the rest, thresholds 0, 1, 2...
        children = list(range(1, len(nodes)))
        nodes[0].data.m_ChildIndices = children
        nodes[0].data.m_BlendType = 0
        nodes[0].data.m_BlendEventID = 0
        nodes[0].data.m_Blend1dData = SimpleNamespace(
            data=SimpleNamespace(
                m_ChildThresholdArray=[float(i) for i in range(len(children))]
            )
        )
    return SimpleNamespace(data=SimpleNamespace(m_NodeArray=nodes))


def transition(destination, *conditions):
    """
    conditions: (mode, parameter hash, threshold) triples.
    """
    return SimpleNamespace(
        data=SimpleNamespace(
            m_DestinationState=destination,
            m_ConditionConstantArray=[
                SimpleNamespace(
                    data=SimpleNamespace(
                        m_ConditionMode=mode,
                        m_EventID=event,
                        m_EventThreshold=threshold,
                    )
                )
                for mode, event, threshold in conditions
            ],
        )
    )


def state(name_id, *clip_ids, transitions=()):
    return SimpleNamespace(
        data=SimpleNamespace(
            m_NameID=name_id,
            m_FullPathID=name_id,
            m_TransitionConstantArray=list(transitions),
            m_BlendTreeConstantArray=[blend_tree(*clip_ids)] if clip_ids else [],
            m_Speed=1.0,
            m_CycleOffset=0.0,
            m_Mirror=False,
        )
    )


def layer(binding, machine_index, mask=()):
    return SimpleNamespace(
        data=SimpleNamespace(
            m_Binding=binding,
            m_StateMachineIndex=machine_index,
            m_LayerBlendingMode=0,
            m_DefaultWeight=1.0,
            m_SkeletonMask=SimpleNamespace(data=SimpleNamespace(m_Data=list(mask))),
            m_StateMachineMotionSetIndex=0,
            m_StateMachineSynchronizedLayerIndex=0,
        )
    )


def machine(*states, default=0):
    return SimpleNamespace(
        data=SimpleNamespace(m_StateConstantArray=list(states), m_DefaultState=default)
    )


def controller(tos, layers, machines, clips, parameters=(), bools=(), ints=()):
    """
    parameters: (hash, type, index) triples into bools or ints.
    """
    return SimpleNamespace(
        m_TOS=tos,
        m_AnimationClips=clips,
        m_Controller=SimpleNamespace(
            m_LayerArray=layers,
            m_StateMachineArray=machines,
            m_Values=SimpleNamespace(
                data=SimpleNamespace(
                    m_ValueArray=[
                        SimpleNamespace(m_ID=key, m_Type=kind, m_Index=index)
                        for key, kind, index in parameters
                    ]
                )
            ),
            m_DefaultValues=SimpleNamespace(
                data=SimpleNamespace(
                    m_FloatValues=[], m_BoolValues=list(bools), m_IntValues=list(ints)
                )
            ),
        ),
    )


class FakeClip:
    def __init__(self, name):
        self.m_Name = name
        self.object_reader = SimpleNamespace(
            assets_file=SimpleNamespace(name="CAB-a"), path_id=1
        )
        self.m_ClipBindingConstant = SimpleNamespace(genericBindings=[])
        self.m_SampleRate = 30.0


class FakePointer:
    def __init__(self, clip):
        self._clip = clip

    def deref(self):
        return self._clip.object_reader

    def read(self):
        return self._clip


class FakeEnv(LazyEnv):
    """
    Resolves from a dict. Deliberately does not call super().__init__, which
    would want a store and a cab map on disk.
    """

    def __init__(self, objects, bundles=None):
        self._objects = objects
        self._catalog = set(bundles) if bundles is not None else {b for b, _ in objects}

    def require(self, *bundles):
        pass

    def find_object(self, bundle, path, kind=None):
        # LazyEnv.find_object raises rather than returning None.
        return self._objects[bundle, path]


def one_state_controller(pointer):
    return controller(
        tos=[(10, "BaseLayer"), (20, "Stand1")],
        layers=[layer(10, 0)],
        machines=[machine(state(20, 0))],
        clips=[pointer],
    )


def entry_for(**columns):
    return CharacterEntry(id="x", model_path="x.prefab", **columns)


class UiChainTest(unittest.TestCase):
    def test_the_ui_fires_its_bool_and_leaves_the_rest_at_default(self):
        # Changestart01 waits on UiActionBegin, Change01 runs out into the loop. The
        # UiAnime branch wants a special animation id and the trigger never fires.
        obj = controller(
            tos=[
                (10, "Base Layer"),
                (20, "Changestart01"),
                (21, "Change01"),
                (22, "Change01Loop"),
                (23, "Special"),
                (30, "UiActionBegin"),
                (31, "UiAnime"),
                (32, "Interput"),
            ],
            layers=[layer(10, 0)],
            machines=[
                machine(
                    state(
                        20,
                        0,
                        transitions=[
                            transition(3, (6, 31, 4101.0)),
                            transition(1, (1, 30, 0.0), (6, 31, 0.0)),
                        ],
                    ),
                    state(21, 0, transitions=[transition(2)]),
                    state(22, 0, transitions=[transition(3, (1, 32, 0.0))]),
                    state(23, 0),
                    default=0,
                )
            ],
            clips=["a"],
            parameters=[(30, 4, 0), (31, 3, 0), (32, 9, 1)],
            bools=[False, False],
            ints=[0],
        )
        [(layer_info, _)] = read_controller(obj, "src", {})
        self.assertEqual(
            ["Changestart01", "Change01", "Change01Loop"],
            walk_ui_chain(dict(layer_info.ui_next), "Changestart01"),
        )


class DetachmentTest(unittest.TestCase):
    """
    The property the residency design rests on. Violating it changes no output
    and raises nothing, it only makes memory grow.
    """

    def test_the_inventory_reaches_no_object_from_the_env(self):
        clip = FakeClip("Stand1")
        obj = one_state_controller(FakePointer(clip))
        env = FakeEnv({(CONTROLLER_AB, CONTROLLER): obj})

        inventory = _read(env, entry_for(controller_path=CONTROLLER))
        self.assertEqual([e.name for e in inventory.entries], ["Stand1"])

        held = {id(o) for o in _reachable(inventory)}
        for leaked in (clip, obj, env):
            self.assertNotIn(id(leaked), held, f"{type(leaked).__name__} is retained")


def _reachable(root):
    seen: dict[int, object] = {}
    stack = [root]
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen[id(obj)] = obj
        if isinstance(obj, (type, types.ModuleType, types.FunctionType)):
            continue
        stack.extend(gc.get_referents(obj))
    return seen.values()


class DominantChildTest(unittest.TestCase):
    def test_the_roster_trees_at_their_default_of_one(self):
        self.assertEqual(1, _find_nearest([-20.0, 0.0, 20.0], 1.0))
        self.assertEqual(1, _find_nearest([-90.0, 0.0, 90.0], 1.0))
        # Dante's Attack163: 51% of the third child.
        self.assertEqual(2, _find_nearest([-180.0, -60.0, 60.0, 180.0], 1.0))

    def test_values_past_either_end_take_that_end(self):
        self.assertEqual(0, _find_nearest([-20.0, 0.0, 20.0], -50.0))
        self.assertEqual(2, _find_nearest([-20.0, 0.0, 20.0], 50.0))
