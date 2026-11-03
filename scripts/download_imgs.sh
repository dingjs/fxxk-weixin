#!/usr/bin/env bash
# download_imgs.sh: 按 img_manifest.json 逐张下载正文图片(经 mitmproxy 代理) -> img/{mid}_{seq}.{ext}
# Usage: bash download_imgs.sh
# 说明: 清单由 make_img_manifest.py 生成;ext 按 URL 判断 gif/png/webp/jpg,与 make_html.py 命名一致
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/common.sh"

mkdir -p "$WORKSPACE/img"
MANIFEST="$WORKSPACE/img_manifest.json"
[ -f "$MANIFEST" ] || { echo "missing $MANIFEST"; exit 1; }

prev=""; n=0; dl=0
while IFS=$'\t' read -r mid url; do
  [ -n "$mid" ] || continue
  # seq 按每篇文章的 data-src 出现顺序编号,换篇文章清零
  if [ "$mid" != "$prev" ]; then prev="$mid"; n=0; fi
  n=$((n + 1))

  ul=$(printf '%s' "$url" | tr 'A-Z' 'a-z')   # bash 3.2 无 ${var,,}
  ext="jpg"
  case "$ul" in
    *wx_fmt=gif* | *mmbiz_gif*) ext="gif" ;;
    *wx_fmt=png* | *mmbiz_png*) ext="png" ;;
    *wx_fmt=webp*) ext="webp" ;;
  esac

  out="$WORKSPACE/img/${mid}_${n}.${ext}"
  if [ -f "$out" ] && [ "$(filesize "$out")" -gt 1000 ]; then continue; fi
  curl_via_proxy -A "$UA_WIN" --max-time 30 "$url" -o "$out"
  sleep 0.12
  dl=$((dl + 1))
done < <("$PY" - "$MANIFEST" <<'PY'
import json, sys
for a in json.load(open(sys.argv[1], encoding='utf-8')):
    for u in a.get('imgs', []):
        print(a.get('mid', '') + '\t' + u)
PY
)
echo "IMG_DONE downloaded=$dl"