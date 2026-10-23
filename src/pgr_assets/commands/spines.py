import logging

from tqdm.auto import tqdm
from UnityPy import classes
from UnityPy.enums import ClassIDType

from pgr_assets.asset_paths import SPINE_BUNDLE_PREFIX, SPINE_PREFAB_PREFIX
from pgr_assets.extractors.spine import quirks
from pgr_assets.extractors.spine.extractor import extract_spine
from pgr_assets.lazyenv import LazyEnv

from .helpers import BaseArgs, open_lazy_env

logger = logging.getLogger("pgr-assets")

LOGIN_PREFAB = "spinelogin"
LOGIN_BUNDLE = SPINE_BUNDLE_PREFIX + ".ab"


class SpinesCommand(BaseArgs):
    output: str  # Directory to output the extracted spines to
    only_login: bool = False
    with_json: bool = False

    def configure(self) -> None:
        super().configure()
        self.set_defaults(func=spines_cmd)


def read_prefab(env: LazyEnv, bundle: str, name: str) -> classes.GameObject:
    path = SPINE_PREFAB_PREFIX + name + ".prefab"
    return env.find_object(bundle, path, ClassIDType.GameObject)


def list_prefabs(env: LazyEnv, bundle: str) -> list[str]:
    return [
        path.removeprefix(SPINE_PREFAB_PREFIX).removesuffix(".prefab")
        for path in env.list_paths(bundle)
        if path.startswith(SPINE_PREFAB_PREFIX) and path.endswith(".prefab")
    ]


def spines_cmd(args: SpinesCommand) -> None:
    owners: dict[str, str] = {}

    with open_lazy_env(args) as (resolved, env):
        major, minor = resolved.version[:2]
        login_name = f"{LOGIN_PREFAB}/{major}-{minor}"
        bundles = (
            [LOGIN_BUNDLE]
            if args.only_login
            else sorted(b for b in env.catalog if b.startswith(SPINE_BUNDLE_PREFIX))
        )

        for bundle in tqdm(bundles):
            with env.pin(bundle):
                env.require(bundle)
                for prefab in list_prefabs(env, bundle):
                    owners[prefab] = bundle
                    if args.only_login and prefab != LOGIN_PREFAB:
                        continue
                    if (
                        quirks.should_skip(prefab)
                        or quirks.find_glue(prefab) is not None
                    ):
                        continue
                    name = login_name if prefab == LOGIN_PREFAB else prefab
                    logger.info("Extracting spine from %s", name)
                    try:
                        extract_spine(
                            name,
                            [read_prefab(env, bundle, prefab)],
                            args.output,
                            write_json=args.with_json,
                        )
                    except Exception:
                        logger.exception(f"Failed to extract {name}")

        if args.only_login:
            return

        # Glued layers can sit in different bundles, so they wait until every
        # owner is known
        for glue in quirks.quirks_glue.values():
            layers = [
                (owners[layer], layer) for layer in glue.layers if layer in owners
            ]
            if len(layers) != len(glue.layers):
                logger.warning(f"Glue {glue.name} is missing layers, skipping")
                continue
            logger.info("Quirk triggered: glue %s", glue.name)
            layer_bundles = sorted({bundle for bundle, _ in layers})
            with env.pin(*layer_bundles):
                env.require(*layer_bundles)
                try:
                    extract_spine(
                        glue.name,
                        [read_prefab(env, bundle, layer) for bundle, layer in layers],
                        args.output,
                        write_json=args.with_json,
                    )
                except Exception:
                    logger.exception(f"Failed to extract {glue.name}")
