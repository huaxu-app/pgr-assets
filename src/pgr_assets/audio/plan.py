from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from pgr_assets.audio.cuegraph import (
    SEQ_LAYERED_TYPES,
    SEQ_RANDOM_TYPES,
    SEQ_SONG_LIST,
    Effects,
    Node,
    Sequence,
    Synth,
    Track,
    Waveform,
)

SONG_FLOOR_SECONDS = 30
FALLBACK_LABELS = {"step": "road"}

RANDOM_IN_MIX = "random takes inside a mix fixed to their first take"
PITCH_LOSS = "pitch shift not applied"
FADE_LOSS = "volume fade not applied"
PLAIN_KEPT = (
    "plain file keeps the first track's waveform, which a mute or branch leaves out"
)


@dataclass(frozen=True)
class Layer:
    waveform: int
    delay_ms: int
    gain: float


@dataclass(frozen=True)
class WaveInfo:
    samples: int
    rate: int
    loops: bool


@dataclass(frozen=True)
class Rendition:
    """An output file with a cue-name suffix, empty for the plain file."""

    suffix: str
    layers: tuple[Layer, ...]


@dataclass
class CuePlan:
    renditions: list[Rendition] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)
    variants: list[str] = field(default_factory=list)
    losses: list[str] = field(default_factory=list)


Choice = tuple[str, str] | None


@dataclass
class _Pass:
    mute: bool
    notes: set[str] = field(default_factory=set)


def _note(effects: Effects, notes: set[str]) -> None:
    if effects.pitched:
        notes.add(PITCH_LOSS)
    if effects.time_volume:
        notes.add(FADE_LOSS)


def _tracks(node: Node | None) -> Iterator[Track]:
    if isinstance(node, Synth):
        for item in node.items:
            yield from _tracks(item)
    elif isinstance(node, Sequence):
        for track in node.tracks:
            yield track
            yield from _tracks(track.target)


def _effects(node: Node | None) -> Iterator[Effects]:
    if isinstance(node, Synth):
        yield node.effects
        for item in node.items:
            yield from _effects(item)
    elif isinstance(node, Sequence):
        yield node.effects
        for track in node.tracks:
            yield track.effects
            yield from _effects(track.target)


def _first_waveform(node: Node | None) -> int | None:
    while node is not None and not isinstance(node, Waveform):
        if isinstance(node, Synth):
            node = node.items[0] if node.items else None
        else:
            node = node.tracks[0].target if node.tracks else None
    return None if node is None else node.index


def _plays(track: Track, choice: Choice, mute: bool) -> bool:
    if mute and track.muted:
        return False
    if track.condition is None or choice is None:
        return True
    if track.condition[0] != choice[0]:
        return True
    return track.condition[1] == choice[1]


def _flatten(
    node: Node, choice: Choice, run: _Pass, delay: int = 0, gain: float = 1.0
) -> list[Layer]:
    if isinstance(node, Waveform):
        return [Layer(node.index, delay, gain)]
    _note(node.effects, run.notes)
    gain *= node.effects.gain
    if isinstance(node, Synth):
        return [
            layer
            for item in node.items
            for layer in _flatten(item, choice, run, delay, gain)
        ]
    tracks = [t for t in node.tracks if _plays(t, choice, run.mute)]
    if node.type not in SEQ_LAYERED_TYPES:
        if len(tracks) > 1:
            run.notes.add(RANDOM_IN_MIX)
        tracks = tracks[:1]
    layers: list[Layer] = []
    for track in tracks:
        if track.target is None:
            continue
        _note(track.effects, run.notes)
        layers += _flatten(
            track.target,
            choice,
            run,
            delay + track.delay_ms,
            gain * track.effects.gain,
        )
    return layers


def _switch(tree: Sequence) -> tuple[str | None, list[str]]:
    labels: dict[str, list[str]] = {}
    for track in _tracks(tree):
        if track.condition is not None:
            seen = labels.setdefault(track.condition[0], [])
            if track.condition[1] not in seen:
                seen.append(track.condition[1])
    best = max(labels.items(), key=lambda item: len(item[1]), default=None)
    if best is None or len(best[1]) < 2:
        return None, []
    return best


def _stem(track: Track) -> bool:
    return track.effects.game_volume or any(
        e.game_volume for e in _effects(track.target)
    )


def _long_loop(layers: list[Layer], waves: Mapping[int, WaveInfo]) -> bool:
    return bool(layers) and all(
        waves[layer.waveform].loops
        and waves[layer.waveform].samples
        >= SONG_FLOOR_SECONDS * waves[layer.waveform].rate
        for layer in layers
    )


def _parts(
    tree: Sequence, waves: Mapping[int, WaveInfo], run: _Pass
) -> list[tuple[Layer, ...]] | None:
    """Split stems or songs by track, recording losses only when split."""
    tracks = [
        t for t in tree.tracks if _plays(t, None, run.mute) and t.target is not None
    ]
    if len(tracks) < 2:
        return None
    local = _Pass(run.mute)
    parts: list[list[Layer]] = []
    for track in tracks:
        assert track.target is not None
        _note(track.effects, local.notes)
        parts.append(
            _flatten(track.target, None, local, track.delay_ms, track.effects.gain)
        )
    stems = tree.type in SEQ_LAYERED_TYPES and any(_stem(t) for t in tracks)
    songs = tree.type == SEQ_SONG_LIST or (
        tree.type in SEQ_RANDOM_TYPES and all(_long_loop(p, waves) for p in parts)
    )
    if not (stems or songs):
        return None
    run.notes |= local.notes
    return [_standalone(p, keep_delay=True) for p in parts if p]


def _standalone(layers: list[Layer], keep_delay: bool) -> tuple[Layer, ...]:
    """Normalize gain relative to the loudest layer.

    Remove leading delay from lone layers outside stem or song sets.
    """
    if len(layers) == 1 and not keep_delay:
        return (Layer(layers[0].waveform, 0, 1.0),)
    top = max((layer.gain for layer in layers), default=1.0) or 1.0
    return tuple(Layer(l.waveform, l.delay_ms, round(l.gain / top, 4)) for l in layers)


def _losses(notes: set[str], layer_counts: list[int]) -> list[str]:
    losses = sorted(n for n in notes if n != RANDOM_IN_MIX)
    if RANDOM_IN_MIX in notes and any(count > 1 for count in layer_counts):
        losses.append(RANDOM_IN_MIX)
    return losses


def _plain_rendition(waveform: int) -> Rendition:
    return Rendition("", (Layer(waveform, 0, 1.0),))


def plan_cue(tree: Sequence | None, waves: Mapping[int, WaveInfo]) -> CuePlan:
    """Plan cue files, ignoring mutes when they would leave no audio.

    This fallback preserves an extracted file. Native playback is unverified.
    """
    if tree is None:
        return CuePlan()
    plan = _plan(tree, waves, mute=True)
    if not plan.renditions and any(t.muted for t in _tracks(tree)):
        return _plan(tree, waves, mute=False)
    return plan


def plan_blocks(trees: list[Sequence]) -> CuePlan:
    """Keep each segment's first waveform, deduplicating and numbering outputs."""
    found: list[int] = []
    for waveform in map(_first_waveform, trees):
        if waveform is not None and waveform not in found:
            found.append(waveform)
    if len(found) == 1:
        return CuePlan([_plain_rendition(found[0])])
    return CuePlan(
        [Rendition(f"_{n}", (Layer(w, 0, 1.0),)) for n, w in enumerate(found)]
    )


def _plan(tree: Sequence, waves: Mapping[int, WaveInfo], mute: bool) -> CuePlan:
    run = _Pass(mute)
    _note(tree.effects, run.notes)
    plain = _first_waveform(tree)
    selector, labels = _switch(tree)
    if selector is not None:
        return _branches(tree, selector, labels, plain, run)

    parts = _parts(tree, waves, run)
    if parts is not None:
        plan = CuePlan([Rendition(f".{n}", p) for n, p in enumerate(parts, 1)])
        plan.variants = [str(n) for n in range(1, len(parts) + 1)]
        if parts:
            plan.links[""] = ".1"
        plan.losses = _losses(run.notes, [len(p) for p in parts])
        return plan

    layers = _standalone(_flatten(tree, None, run), keep_delay=False)
    plan = CuePlan(losses=_losses(run.notes, [len(layers)]))
    if not layers:
        return plan
    if plain is not None and all(l.waveform != plain for l in layers):
        # Preserve the first waveform at the existing plain-file path.
        plan.renditions.append(_plain_rendition(plain))
        plan.losses.append(PLAIN_KEPT)
    else:
        plan.renditions.append(Rendition("", layers))
    return plan


def _branches(
    tree: Sequence, selector: str, labels: list[str], plain: int | None, run: _Pass
) -> CuePlan:
    by_label = {
        label: _standalone(_flatten(tree, (selector, label), run), keep_delay=False)
        for label in labels
    }
    playable = [label for label in labels if by_label[label]]
    plan = CuePlan(losses=_losses(run.notes, [len(by_label[l]) for l in playable]))
    if len({by_label[label] for label in playable}) <= 1:
        if playable:
            plan.renditions.append(Rendition("", by_label[playable[0]]))
        return plan

    file_of: dict[tuple[Layer, ...], str] = {}
    suffixes: set[str] = set()
    for label in playable:
        layers, suffix = by_label[label], "." + label.lower()
        if suffix in suffixes:
            raise RuntimeError(f"switch label {label!r} collides with another label")
        suffixes.add(suffix)
        if layers in file_of:
            plan.links[suffix] = file_of[layers]
        else:
            file_of[layers] = suffix
            plan.renditions.append(Rendition(suffix, layers))
    plan.variants = [label.lower() for label in playable]

    lowered = {label.lower(): label for label in playable}
    default = lowered.get(FALLBACK_LABELS.get(selector.lower(), ""))
    if default is None:
        default = next(
            (l for l in playable if any(x.waveform == plain for x in by_label[l])),
            None,
        )
    if default is None and plain is not None:
        plan.renditions.append(_plain_rendition(plain))
        plan.losses.append(PLAIN_KEPT)
        return plan
    plan.links[""] = file_of[by_label[default or playable[0]]]
    return plan
