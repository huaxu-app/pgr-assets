import os
import argparse
import logging
import io
from typing import Dict, Tuple

import UnityPy
import msgpack
import requests
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

DECRYPTION_KEY = 'y5XPvqLOrCokWRIa'
LAUNCHER_CDN_BASE = 'https://prod-awscdn-gamestarter.kurogame.net/'
KURO_CDN_BASE = 'http://prod-encdn-akamai.kurogame.net/prod'

APP_ID = 'com.kurogame.punishing.grayraven.en.pc'
APP_PLATFORM = 'standalone'  # android, use standalone for PC

HG_GAME_ID = 143
HG_GAME_VERSION = 4


def get_bundle(path: str) -> UnityPy.Environment:
    resp = requests.get(path)
    if resp.status_code != 200:
        raise Exception(f"Failed to download bundle {path} - {resp.status_code}")
    return UnityPy.load(resp.content)


def get_json(path: str) -> dict:
    resp = requests.get(path)
    if resp.status_code != 200:
        raise Exception(f"Failed to download json {path} - {resp.status_code}")
    return resp.json()


def get_tab(path: str) -> pd.DataFrame:
    resp = requests.get(path)
    if resp.status_code != 200:
        raise Exception(f"Failed to download raw {path} - {resp.status_code}")
    return pd.read_csv(io.StringIO(resp.text), sep="\t")


def get_index(path: str) -> Dict[str, Tuple[str, str, int]]:
    env = get_bundle(path)
    return msgpack.loads(env.container['assets/temp/index.bytes'].read().script)[0]


def get_primary_blobs() -> Dict[str, str]:
    logger.info('Getting primary blobs')
    index = get_json(LAUNCHER_CDN_BASE + f'pcstarter/prod/game/G{HG_GAME_ID}/{HG_GAME_VERSION}/index.json')
    resource_base_path = index['default']['resourcesBasePath']
    resources = get_json(LAUNCHER_CDN_BASE + index['default']['resources'])

    resource_table = {}
    for resource in resources['resource']:
        blob = resource['dest'].split('/')[-1]
        # We don't use the md5 hashes, but they are in resource if we need them
        resource_table[blob] = LAUNCHER_CDN_BASE + resource_base_path + resource['dest']

    return resource_table


def get_patch_cdn_url(version: str) -> str:
    logger.info("Getting config from patch cdn")
    config = get_tab(KURO_CDN_BASE + f'/client/config/{APP_ID}/{version}/{APP_PLATFORM}/config.tab')
    application_version = config.loc[config.Key == "ApplicationVersion", "Value"].values[0]
    document_version = config.loc[config.Key == "DocumentVersion", "Value"].values[0]
    cdn = config.loc[config.Key == "PrimaryCdns", "Value"].values[0].split('|')[0]

    return '/'.join([
        cdn, 'client/patch', APP_ID, application_version, APP_PLATFORM, document_version, 'matrix'
    ])


def resolve_blob(bundle: str, index: Dict[str, Tuple[str, str, int]], launcher_blobs: Dict[str, str],
                 patch_cdn_base: str) -> str:
    blobname, _, _ = index[bundle]
    if blobname in launcher_blobs:
        logger.info(f"Bundle {bundle} - using launcher blob {blobname}")
        return launcher_blobs[blobname]

    logger.info(f"Bundle {bundle} - using patch blob {blobname}")
    return patch_cdn_base + '/' + blobname


def rewrite_text_asset(path: str, data: memoryview) -> Tuple[str, bytearray]:
    # RSA signature can fuck itself
    data = bytearray(data[128:])

    # Almost all files end with .bytes
    # If it doesn't, we'll keep it as it is,
    # otherwise we drop the '.bytes' extension
    path_without_bytes, ext = os.path.splitext(path)
    if ext != ".bytes":
        return path, data

    path = path_without_bytes
    ext = os.path.splitext(path)[1]

    if ext == ".lua":
        logger.warning('Extracting lua files is unsupported atm')

    return path, data


def extract_bundle(env: UnityPy.Environment, output_dir: str):
    for path, obj in env.container.items():
        dest = os.path.join(output_dir, *path.split("/"))
        # create dest based on original path
        # make sure that the dir of that path exists
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        try:
            if obj.type.name in ["Texture2D", "Sprite"]:
                data = obj.read()
                # correct extension
                dest, ext = os.path.splitext(dest)
                dest = dest + ".png"
                data.image.save(dest)
                logger.debug(f"Extracted {path}")
            elif obj.type.name == "TextAsset":
                data = obj.read()
                dest, data = rewrite_text_asset(dest, data.script)
                with open(dest, "wb") as f:
                    f.write(data)
                logger.debug(f"Extracted {path}")
            else:
                logger.warning(f"Unsupported type {obj.type.name} for {path}")
        except Exception as e:
            logger.error(f"Failed to extract {path}: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extracts the assets required for kennel')
    # From the config tab PrimaryCdn, e.g. http://prod-encdn-akamai.kurogame.net/prod/client/config/com.kurogame.punishing.grayraven.en.pc/1.28.0/standalone/config.tab
    parser.add_argument('--version', type=str, help='The client version to use.', required=True)
    parser.add_argument('--output', type=str, help='Output directory to use', required=True)
    parser.add_argument('bundles', nargs='*', help='Bundles to extract')
    args = parser.parse_args()

    if len(args.bundles) == 0:
        parser.error('No bundles specified')

    UnityPy.set_assetbundle_decrypt_key(DECRYPTION_KEY)
    launcher_blobs = get_primary_blobs()
    patch_cdn_url = get_patch_cdn_url(args.version)
    main_index = get_index(patch_cdn_url + '/index')

    for bundle in args.bundles:
        if bundle not in main_index:
            parser.error(f"Bundle {bundle} not found in index")

    for bundle in args.bundles:
        bundle_path = resolve_blob(bundle, main_index, launcher_blobs, patch_cdn_url)
        logger.info(f"Extracting {bundle_path}")
        extract_bundle(get_bundle(bundle_path), output_dir=args.output)
