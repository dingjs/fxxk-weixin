#!/usr/bin/env bash
# fetch_bodies.sh: 读 articles_list.json + params.txt,逐篇 curl 正文 -> html/{mid}_{idx}.html
# Usage: bash fetch_bodies.sh
#   ARTS_FILE=/path/other_list.json   # 抓指定子集（如只重抓最新 N 篇），默认 $WORKSPACE/articles_list.json
# - 文件名带 idx：微信一个 mid（群发）内含多个子文章(idx=1..8)，正文互不相同，
#   只按 mid 命名会互相覆盖 → {mid}_{idx}.html
# - __biz 实时从 params.txt 读 (refresh_loop.py 自动提取,不再写死)
# - 正文有效性=内容标记(老式 js_content / 新版 og:title),不只按文件大小;
#   验证页(小)与壳页(大但无正文)都视为无效自动重试一次
# - key 轮换期 NO_PARAM 时对同一 mid 重试,不永久跳过
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/common.sh"

# 正文有效性判定（复用 wechat_extract.has_article_content，见 check_article.py）：
# 覆盖老式 js_content / rich_media_content、新版分享页 og:title，以及 item_show_type
# 7/8/10 图集文/短内容/音频等特殊类型；微信验证页(风控/断连)判定 BAD:… 会重试；
# 平台已删等终态判 OK（重试没意义）。输出 OK 或 BAD[:原因]。
valid_page() {
  "$PY" "$HERE/check_article.py" "$1" 2>/dev/null || echo BAD
}

mkdir -p "$WORKSPACE/html"
ARTS_FILE="${ARTS_FILE:-$WORKSPACE/articles_list.json}"
[ -f "$ARTS_FILE" ] || { echo "missing $ARTS_FILE"; exit 1; }

total=$("$PY" - "$ARTS_FILE" <<'PY'
import json, sys
print(len(json.load(open(sys.argv[1], encoding='utf-8'))))
PY
)
count=0
while IFS=$'\t' read -r mid url; do
  [ -n "$mid" ] || continue
  # 从 content_url 抠出 idx/sn/chksm（idx 决定输出文件名 {mid}_{idx}.html，必须在 out= 前解析）
  idx=1; sn=""; chksm=""
  case "$url" in
    *idx=*) idx="${url##*idx=}"; idx="${idx%%&*}" ;;
  esac
  case "$url" in
    *sn=*) sn="${url##*sn=}"; sn="${sn%%&*}" ;;
  esac
  case "$url" in
    *chksm=*) chksm="${url##*chksm=}"; chksm="${chksm%%&*}" ;;
  esac

  out="$WORKSPACE/html/${mid}_${idx}.html"
  # 断点续跑：已有文件且内容有效才跳过（壳页/大但无正文会重新抓）
  if [ -f "$out" ] && [ "$(filesize "$out")" -gt 100000 ] && [ "$(valid_page "$out")" = "OK" ]; then continue; fi
  # key 轮换期可能短暂拿不到参数：对同一 mid 重试最多 5 次，避免永久跳过
  pr=0
  while ! { load_params && [ -n "$biz" ] && [ -n "$key" ]; }; do
    pr=$((pr + 1))
    if [ $pr -ge 5 ]; then echo "GIVEUP_PARAM $mid"; continue 2; fi
    echo "NO_PARAM $mid try=$pr"; sleep 3
  done

  u="https://mp.weixin.qq.com/s?__biz=${biz}&mid=${mid}&idx=${idx}&sn=${sn}"
  [ -n "$chksm" ] && u="${u}&chksm=${chksm}"
  u="${u}&uin=${uin}&key=${key}&pass_ticket=${pt}"
  hd="Cookie: ${cookie}"

  curl_via_proxy -L -A "$UA_WIN" -H "$hd" --max-time 45 "$u" -o "$out"
  sleep 0.25
  sz=$(filesize "$out")
  # 有效性=内容标记（老/新两模板），不只是文件大小：壳页可能很大但无正文
  if [ "$sz" -lt 100000 ] || [ "$(valid_page "$out")" != "OK" ]; then
    echo "RETRY $mid size=$sz"
    sleep 1
    curl_via_proxy -L -A "$UA_WIN" -H "$hd" --max-time 45 "$u" -o "$out"
    sz=$(filesize "$out")
    v=$(valid_page "$out")
    [ "$v" != "OK" ] && echo "DEGRADED $mid size=$sz $v"
  fi
  count=$((count + 1))
  [ $((count % 10)) -eq 0 ] && echo "progress $count/$total"
done < <("$PY" - "$ARTS_FILE" <<'PY'
import json, sys
for a in json.load(open(sys.argv[1], encoding='utf-8')):
    print(a.get('mid', '') + '\t' + a.get('url', ''))
PY
)
echo "BODIES_DONE"