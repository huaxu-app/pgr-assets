import concurrent.futures
import hashlib
import logging
import os

import UnityPy
from tqdm.auto import tqdm

from extractors.spine.extractor import extract_spine
from sources import SourceSet
from .helpers import build_source_set, BaseArgs

logger = logging.getLogger('pgr-assets')


def download_env_bundle(bundle: str, env_dir: str, sources: SourceSet):
    os.makedirs(os.path.join(env_dir, os.path.dirname(bundle)), exist_ok=True)
    out_file = os.path.join(env_dir, bundle)

    if os.path.exists(out_file):
        with open(out_file, 'rb') as f:
            sha1 = hashlib.sha1(f.read()).hexdigest()
        sha1_expect = sources.bundle_sha1(bundle)
        if sha1 == sha1_expect:
            return

    with open(out_file, 'wb') as f:
        f.write(sources.find_bundle(bundle))


def download_env(env_dir: str, sources: SourceSet):
    logger.info(f'Downloading Unity environment to {env_dir}')
    bundles = [b for b in sources.list_all_bundles() if 'spine' in b]

    errors = False
    with concurrent.futures.ProcessPoolExecutor(max_workers=None) as executor:
        futures = [executor.submit(download_env_bundle, bundle, env_dir, sources) for bundle in bundles]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Failed to process bundle: {e}")
                errors = True

    if errors:
        raise Exception('Failed to download all bundles')


class SpinesCommand(BaseArgs):
    env_dir: str = '.env'  # Directory to use for storing the Unity environment
    output: str  # Directory to output the extracted spines to
    only_login: bool = False

    def configure(self) -> None:
        self.set_defaults(func=spines_cmd)


def spines_cmd(args: SpinesCommand):
    sources = build_source_set(args)

    download_env(args.env_dir, sources)
    env = UnityPy.Environment(args.env_dir)

    all_prefabs = {k: v for k, v in env.container.items() if k.endswith('.prefab')}
    if args.only_login:
        all_prefabs = {'assets/product/ui/spine/spinelogin.prefab': all_prefabs['assets/product/ui/spine/spinelogin.prefab']}

    for k, v in all_prefabs.items():
        name = k.removeprefix('assets/product/ui/spine/').removesuffix('.prefab')
        if name == 'spinelogin':
            name += '/%d.%d' % sources.version()[:2]
        logger.info('Extracting spine from %s', name)
        extract_spine(name, v.read(), args.output)
