apkpure_kr_apk_url := "https://d.apkpure.net/b/XAPK/com.herogame.gplay.punishing.grayraven.kr?version=latest"

build:
  pyinstaller pgr-assets.spec

download-latest-kr-apk:
  #!/bin/bash
  set -euo pipefail

  version="$(curl -LsqI -w '%header{content-disposition}\n' -o/dev/null 2>&1 "{{apkpure_kr_apk_url}}" | grep -Eo '([0-9]+\.[0-9]+\.[0-9]+)')"
  echo $version

clean:
  rm -rf build dist

