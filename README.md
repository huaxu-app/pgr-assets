# PGR Assets
> Backbone for Huaxu's asset database

## Installation

This package is not available on PyPI, so you will need to install it from source.

```bash
pip install pgr_assets@git+https://github.com/huaxu-app/pgr-assets
# or the dev version
pip install pgr_assets@git+https://github.com/huaxu-app/pgr-assets@dev
```

## Commands

- `list` — print every bundle name resolvable for a server. Pass search terms to filter (case-insensitive substrings, terms are AND-ed together).
- `bundles` — download raw bundle blobs to disk, without extracting or converting them.
- `extract` — download, decrypt, extract and convert images/audio/video/text.
- `spines` — reconstruct Spine2D rigs (atlas + skeleton + textures) from the game's spine bundles.

`extract` and `bundles` pick what to process with selection flags: `--all`, `--all-temp` (text), `--all-images`, `--all-audio`, `--all-video`, or explicit bundle names (discover them with `list`).

## Common usages

```bash
# List every asset (defaults to the global server)
pgr-assets list

# Switch servers with --preset: global, korea, japan, taiwan, china, china-beta
pgr-assets list --preset korea

# Search the manifest: prints only bundles matching ALL given terms case-insensitively
pgr-assets list spine lucia

# Extract every image bundle into ./out
pgr-assets extract --preset global --all-images --output ./out

# Extract specific bundles by name (discover them with `list` above)
pgr-assets extract --preset global assets/product/ui/spine/lucia/lucia.ab --output ./out

# Re-run after a game update, the sha1 cache skips unchanged bundles
pgr-assets extract --preset global --all --output ./out --cache ./out/.sha1cache.json

# More verbose logging
pgr-assets extract --preset global --all-audio --output ./out --log-level debug

# For full usage instructions see the help output of the various commands
```

## Output

`extract` mirrors each bundle's internal path under the output directory, converting as it goes:

- **Images** → `.png` **and** `.webp`; character art under `image/rolecharacter/` also gets a 256px `.256.webp` thumbnail.
- **Text** → decoded in place (the `.bytes` suffix is dropped). With `--convert-binary-tables`, `/temp/bytes/*.tab.bytes` tables are also written as `.csv`.
- **Audio** → `audio/<name>/*.mp3` (use `--raw-audio` to keep the decoded `.wav` instead).
- **Video** → `video/<name>.mp4` with each language as a tagged audio track; `--hls` additionally emits an HLS master playlist + segments.

`--write-settings` drops a `settings.json` (server + version) in the output directory.

## Requirements

You'll need **Python 3.13+** and [`ffmpeg`](https://ffmpeg.org/) installed. Just use your platform's recommended way of installing ffmpeg, such as:

```bash
# Arch Linux
$ pacman -Syu ffmpeg
# Fedora / RHEL (derivatives)
$ dnf install ffmpeg
# Debian / Ubuntu
$ apt install ffmpeg
# MacOS
$ brew install ffmpeg
# Windows
$ winget install --id=Gyan.FFmpeg  -e
```

Alternatively, follow the [official download instructions](https://ffmpeg.org/download.html) for your platform.

The `china-beta` server additionally requires a `PATCH_SIGN_KEY` environment variable.

## Considerations

### Why?

While there are similar tools (like [CNStudio](https://github.com/Razmoth/CNStudio)) that can fulfill the primary task, 
`pgr-assets` specializes itself towards Huaxu's goals, providing some major benefits:

- It does not require you to have any local copy of the entire game worth of game bundles 
  - It instead downloads the required files on-demand from the game's CDN servers
- It supports the internal encryption and signature scheme used for text assets
- It is aware of the file storage methods that PGR uses and properly extracts and decrypts
  the flavors of audio and video
- It converts assets into more web-friendly formats on the fly
- It can do partial updates (by relying on the sha1 cache)

All of these things made this worthwhile enough to invest in this custom tooling. 

### Python

Python was chosen for this project not specifically because I like it, but because it has the
proper intersection of libraries to fulfill my use-cases. While C# has some alternatives 
(You can grab the internal libraries of VGMtoolbox and AssetStudio),
these alternatives come with major downsides and hacking around their non-officially-a-library status.

In the end, I really didn't feel like building parsers for Unity Asset Bundles and Criware's formats,
and wanted to just focus on getting shit done.
