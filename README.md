# PGR Assets
> Backbone for huaxu's asset database

## Usage

```
usage: pgr-assets [-h] [--primary {obb,EN_PC,EN_PC_PRE,KR_PC,JP_PC,TW_PC,CN_PC}] [--obb OBB]
                  [--patch {EN,EN_PC,KR,KR_PC,JP,JP_PC,TW,TW_PC,CN,CN_PC}] --version VERSION --output OUTPUT
                  [--decrypt-key DECRYPT_KEY] [--list] [--all-temp] [--all-audio] [--all-video]
                  [--all-images] [--recode-video] [--nvenc] [--all] [--cache CACHE]
                  [bundles ...]

Extracts the assets required for kennel

positional arguments:
  bundles               Bundles to extract

options:
  -h, --help            show this help message and exit

  --version VERSION     The client version to use. (required)
  --output OUTPUT       Output directory to use (required)

  --primary {obb,EN_PC,EN_PC_PRE,KR_PC,JP_PC,TW_PC,CN_PC} (default: EN_PC)
  --patch {EN,EN_PC,KR,KR_PC,JP,JP_PC,TW,TW_PC,CN,CN_PC} (default: EN_PC)
  --obb OBB             Path to obb file. Only valid when --primary is set to obb.

  --list                List all available bundles
  --all-temp            Extract all temp (text) bundles
  --all-audio           Extract all audio bundles
  --all-video           Extract all video bundles
  --all-images          Extract all image bundles
  --all                 Extract all i can find

  --recode-video        Recode h264 in videos
  --nvenc               Use NVenc to recode
  --cache CACHE         Path to sha1 cache file
```
