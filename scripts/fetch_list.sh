#!/usr/bin/env bash
# fetch_list.sh: getmsg 翻页拉全部文章列表 -> getmsg_pages/p{offset}.json
# Usage: bash fetch_list.sh   (JSON 页可能较大,用 python3 解析,无需 jq)
#
# - __biz/key/pass_ticket/appmsg_token/cookie/uin 实时读 params.txt (refresh_loop.py 维护)
# - msg_count=0 (key 轮换) 时同 offset 带退避重试,不再丢页
# - 续页判据用 next_offset 前进(can_msg_continue 部分会话恒 0,不可靠),缺失时回退;
#   MAX_OFFSET 限制最大 offset（默认 100000=拉全部）。只抓最新 N 篇：每页 10 个群发
#   bundle，MAX_OFFSET=100 即最新 10 页=100 个群发（解析后子文章数 >100）。注意偏移
#   到的是 bundle 而非子文章数。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/common.sh"

mkdir -p "$WORKSPACE/getmsg_pages"

MAX_OFFSET="${MAX_OFFSET:-100000}"
for ((off = 0; off < MAX_OFFSET; off += 10)); do
  page="$WORKSPACE/getmsg_pages/p${off}.json"
  [ -f "$page" ] && [ -s "$page" ] && continue

  load_params || { echo "NO_PARAM $off"; sleep 2; continue; }
  [ -n "$biz" ] || { echo "NO_BIZ $off"; sleep 2; continue; }

  url="https://mp.weixin.qq.com/mp/profile_ext?action=getmsg&__biz=${biz}&f=json&count=10&is_ok=1&scene=126&uin=${uin}&key=${key}&pass_ticket=${pt}&wxtoken=&appmsg_token=${tok}&x5=0&offset=${off}"

  ok=0
  for ((try = 1; try <= 5 && ok == 0; try++)); do
    curl_via_proxy -A "$UA_WIN" -H "Cookie: ${cookie}" --max-time 45 "$url" -o "$page"
    sleep 0.35
    # 提取 ret / msg_count / can_msg_continue / next_offset
    read -r jret mc cc noff < <("$PY" - "$page" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
    print(d.get('ret', -999), d.get('msg_count', ''), d.get('can_msg_continue', ''), d.get('next_offset', ''))
except Exception:
    print('-999', '', '', '')
PY
)
    if [ "$jret" != "0" ]; then
      echo "RET $off = $jret try=$try"; sleep 3; continue
    fi
    if [ "$mc" = "0" ]; then
      echo "EMPTY $off try=$try"; sleep 3; continue
    fi
    ok=1
    # 续页判据优先用 next_offset 是否前进 —— 部分会话 can_msg_continue 恒为 0
    # 但下一页仍有效（实测会只抓一页）；next_offset 缺失时回退 can_msg_continue。
    if [ -n "$noff" ] && [ "$noff" -le "$off" ]; then
      echo "STOP $off count=$mc next=$noff"; break 2
    elif [ -z "$noff" ] && [ "$cc" != "1" ]; then
      echo "STOP $off count=$mc"; break 2
    fi
  done
  # 该 offset 5 次重试后仍拿不到有效页(EMPTY/RET): 探针 offset=0 区分
  # 「历史尽头」与「key 轮换失效/断供」——避免对剩余百千个 offset 空转。
  # EMPTY 可能是:(a) getmsg 近期历史拉完 (b) key 失效(offset 0 也会空)。
  if [ "$ok" != "1" ]; then
    [ -n "$biz" ] && [ -n "$key" ] || load_params || true
    if [ -n "$biz" ] && [ -n "$key" ]; then
      probe="$WORKSPACE/getmsg_pages/.probe0.json"
      curl_via_proxy -A "$UA_WIN" -H "Cookie: ${cookie}" --max-time 45 \
        "https://mp.weixin.qq.com/mp/profile_ext?action=getmsg&__biz=${biz}&f=json&count=10&is_ok=1&scene=126&uin=${uin}&key=${key}&pass_ticket=${pt}&wxtoken=&appmsg_token=${tok}&x5=0&offset=0" -o "$probe"
      pmc=$("$PY" - "$probe" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding='utf-8')).get('msg_count', ''))
except Exception:
    print('')
PY
)
      [ "$pmc" = "0" ] && { echo "KEY_DEAD offset=$off (offset 0 也 EMPTY=文章页关闭/key 失效，请重新打开文章)"; break 2; }
      [ -z "$pmc" ] && { echo "FAIL offset=$off (probe 无结果，可能是网络/风控)"; break 2; }
      echo "END_OF_HISTORY offset=$off (offset 0 有数据、本页空=近期历史尽头，共 $((off / 10)) 页)"; break 2
    fi
    echo "NO_PARAM_ABORT offset=$off"; break 2
  fi
done
echo "LIST_DONE"