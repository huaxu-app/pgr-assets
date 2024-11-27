# PGR Assets
> Backbone for huaxu's asset database

## Common usages

```bash
# List assets on global:
pgr-assets --list

# Switch servers by changing preset: (global, korea, japan, taiwan, china)
pgr-assets --preset global --list

# Extract all text assets
pgr-assets --all-temp --output /path/to/output
```

## Usage

```
usage: pgr-assets.py [-h] [--preset {global,korea,japan,taiwan,china}] [--prerelease] [--primary {obb,EN_PC,KR_PC,JP_PC,TW_PC,CN_PC}] [--obb OBB] [--patch {EN,EN_PC,KR,KR_PC,JP,JP_PC,TW,TW_PC,CN,CN_PC}] [--version VERSION] [--output OUTPUT]
                     [--decrypt-key DECRYPT_KEY] [--list] [--all-temp] [--all-audio] [--all-video] [--all-images] [--recode-video] [--nvenc] [--all] [--cache CACHE] [--write-settings]
                     [bundles ...]

Extracts the assets required for kennel

positional arguments:
  bundles               Bundles to extract

options:
  -h, --help            show this help message and exit
  --preset {global,korea,japan,taiwan,china}
  --prerelease          Use the prerelease patch source, if available
  --primary {obb,EN_PC,KR_PC,JP_PC,TW_PC,CN_PC}
  --obb OBB             Path to obb file. Only valid when --primary is set to obb.
  --patch {EN,EN_PC,KR,KR_PC,JP,JP_PC,TW,TW_PC,CN,CN_PC}
  --version VERSION     The client version to use. Inferred by default.
  --output OUTPUT       Output directory to use. Required for extraction, not list.
  --decrypt-key DECRYPT_KEY
                        Decryption key to use
  --list                List all available bundles
  --all-temp            Extract all temp (text) bundles
  --all-audio           Extract all audio bundles
  --all-video           Extract all video bundles
  --all-images          Extract all image bundles
  --recode-video        Recode h264 in videos
  --nvenc               Use NVenc to recode
  --all                 Extract all i can find
  --cache CACHE         Path to sha1 cache file
  --write-settings      Write a small settings file to the output directory containing preset and version

```

## Requirements

You'll need to have [`ffmpeg`](https://ffmpeg.org/) installed. Just use your platform's recommended way of installing it, such as:

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

Just run `just build` to build a pyinstaller'd version of pgr-assets (`dist/pgr-assets`) that you can use like a normal executable
It's what I do.

