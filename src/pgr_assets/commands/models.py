import logging
from contextlib import closing

from pgr_assets.commands.helpers import BaseArgs, build_source_set
from pgr_assets.models.env import ModelEnv
from pgr_assets.models.export import COMPRESS_QUALITY, export_models
from pgr_assets.models.scope import SCOPES
from pgr_assets.models.tables import Tables
from pgr_assets.models.texture import TEXTURE_ENCODINGS
from pgr_assets.store import BundleStore

logger = logging.getLogger("pgr-assets")


class ModelsCommand(BaseArgs):
    filters: list[str]
    scope: str = "all"
    output: str | None = None
    force: bool = False
    compress: str = "off"
    textures: str = "webp"

    def configure(self) -> None:
        super().configure()
        self.add_argument(
            "filters",
            nargs="*",
            help="target ids or substrings, OR-combined. e.g. r5sailinnamd010011 or r5sailinna",
        )
        self.add_argument(
            "--output",
            default=None,
            help="Write each target's glTF and manifest under <dir>/<ModelPath>/",
        )
        self.add_argument(
            "--force",
            action="store_true",
            help="Rebuild every selected target, ignoring the build cache",
        )
        self.add_argument(
            "--compress",
            choices=list(COMPRESS_QUALITY),
            default="off",
            help="Brotli the glb and every json."
            " low is fast, high is publish-time only",
        )
        self.add_argument(
            "--textures",
            choices=list(TEXTURE_ENCODINGS),
            default="webp",
            help="Texture encoding. webp-lossless skips the lossy allowlist",
        )
        self.add_argument(
            "--scope",
            choices=list(SCOPES),
            default="all",
            help="all: every model.tab.bytes row."
            " characters: only the rows a fashion reaches."
            " weapons: the equipmodel weapon prefabs."
            " dorm: the room chibis from dormcharacterstyle and uimodel",
        )
        self.set_defaults(func=models_cmd)


def models_cmd(args: ModelsCommand) -> None:
    resolved = build_source_set(args)
    resolved.sources.warm()
    catalog = {b.lower() for b in resolved.sources.list_all_bundles()}
    scope = SCOPES[args.scope]

    with closing(
        ModelEnv(BundleStore(resolved.sources, args.cache_dir), catalog)
    ) as env:
        tables = Tables(env, resolved.version)
        registry = scope.load_registry(tables)
        selected = registry.select(args.filters)
        if args.output is None:
            for entry in selected:
                print(scope.describe(entry))
        elif selected:
            export_models(
                env,
                tables,
                selected,
                args.output,
                scope,
                force=args.force,
                compress=args.compress,
                textures=TEXTURE_ENCODINGS[args.textures],
            )

    reach = (
        f" ({len(registry.characters)} reachable from fashion)"
        if 0 < len(registry.characters) < len(registry)
        else ""
    )
    logger.info(f"{len(selected)} of {len(registry)} targets{reach}")
