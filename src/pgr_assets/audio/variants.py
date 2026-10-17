import json
import os
import tempfile

SIDECAR = ".variants.json"
AGGREGATE = "variants.json"

Variants = dict[str, dict[str, list[str]]]


def _write_json(path: str, data: dict) -> None:
    # Replace only after closing a complete file so interrupted writes preserve it.
    with tempfile.TemporaryDirectory(dir=os.path.dirname(path)) as dirname:
        temporary = os.path.join(dirname, "variants.json")
        with open(temporary, "w") as handle:
            json.dump(data, handle, sort_keys=True)
        os.replace(temporary, path)


def write_bank_variants(dirname: str, variants: dict[str, list[str]]) -> None:
    """Save bank variants for aggregation on subsequent cached runs."""
    path = os.path.join(dirname, SIDECAR)
    if variants:
        _write_json(path, variants)
    elif os.path.exists(path):
        os.remove(path)


def collect_variants(audio_dir: str) -> Variants:
    found: Variants = {}
    for dirname, _, files in os.walk(audio_dir):
        if SIDECAR in files:
            bank = os.path.relpath(dirname, audio_dir).replace(os.sep, "/")
            with open(os.path.join(dirname, SIDECAR)) as handle:
                found[bank] = json.load(handle)
    return found


def write_aggregate(audio_dir: str) -> Variants:
    found = collect_variants(audio_dir)
    os.makedirs(audio_dir, exist_ok=True)
    _write_json(os.path.join(audio_dir, AGGREGATE), found)
    return found
