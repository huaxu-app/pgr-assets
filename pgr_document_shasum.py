import argparse
import sys

import UnityPy
import msgpack
import requests

# This contains the sha1 table.
WANTED_FILE = 'assets/temp/table.ab'

parser = argparse.ArgumentParser(description='Extracts the sha256 checksum of the requested PGR bundle')
parser.add_argument('--decryption-key', type=str, help='The decryption key to use. Defaults to live.',
                    default='y5XPvqLOrCokWRIa')
# From the config tab PrimaryCdn, e.g. http://prod-encdn-akamai.kurogame.net/prod/client/config/com.kurogame.punishing.grayraven.en.pc/1.28.0/standalone/config.tab
parser.add_argument('--cdn-base', type=str, help='The base URL of the CDN to use. Defaults to the current default CDN.',
                    default='http://prod-encdn-aliyun.kurogame.net/prod')
parser.add_argument('--game-id', type=str, help='The game ID to use. Defaults to PC.',
                    default='com.kurogame.punishing.grayraven.en.pc',
                    choices=['com.kurogame.punishing.grayraven.en', 'com.kurogame.punishing.grayraven.en.pc'])
parser.add_argument('--client-version', type=str, help='The client version to use. See config.tab', required=True)
parser.add_argument('--document-version', type=str, help='The document version to use. See config.tab', required=True)
parser.add_argument('--platform', type=str, help='The platform to use.', choices=['android', 'ios', 'standalone'],
                    default='standalone')

args = parser.parse_args()

UnityPy.set_assetbundle_decrypt_key(args.decryption_key)


def cdn_path(path):
    return '/'.join([
        args.cdn_base, 'client/patch', args.game_id, args.client_version, args.platform, args.document_version,
        'matrix', path
    ])


def get(path):
    resp = requests.get(cdn_path(path))
    if resp.status_code != 200:
        print(f'Failed to download {path}: {resp.status_code} - {resp.reason}', file=sys.stderr)
        exit(1)
    return resp.content


def download_bundle(bundle_name):
    print('Downloading bundle ' + cdn_path(bundle_name), file=sys.stderr)
    return UnityPy.load(get(bundle_name))


def parse_sum_line(line):
    splits = line.split('\t')
    if len(splits) != 2:
        print('Invalid line: ' + line, file=sys.stderr)
        exit(1)
    return splits[0], splits[1]


def parse_sum_table(table):
    print('Parsing table...', file=sys.stderr)
    return dict(parse_sum_line(line) for line in table.splitlines())


index = download_bundle('index')
if len(index.objects) != 2:
    print('Invalid index file', file=sys.stderr)
    exit(1)
index_manifest = msgpack.loads(index.objects[1].read().script)[0]

if WANTED_FILE not in index_manifest:
    print('File not found in index manifest', file=sys.stderr)
    exit(1)

# [0] = the bundle that contains it, [1] = is a hash of the file, [2] = is the size
wanted_bundle = index_manifest[WANTED_FILE][0]
bundle_env = download_bundle(wanted_bundle)

# The first 128 bytes of the file are an RSA signature, the rest is the sha1 table.
table = parse_sum_table(bytearray(bundle_env.objects[1].read().script[128:]).decode())

print(table['All'])
