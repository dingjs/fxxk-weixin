#!/usr/bin/env bash
# Shared helpers for the fuck-weixin shell scripts.
# 支持 Linux / macOS / Windows（Git for Windows 自带的 Git Bash）。
# Usage (from any of the .sh scripts in this dir):
#   . "$(cd "$(dirname "$0")" && pwd)/common.sh"
#
# Env overrides:
#   WORKSPACE_DIR=/path/to/work   run scripts with files in another dir
#   MITM_PROXY=direct                 本机直连（默认；和微信同一个公网出口）
#   MITM_PROXY=http://127.0.0.1:8868  仅当 curl 不在微信那台机器上时才 -x 过去
#   PARAMS_FILE=/path/to/params.txt
#   PY=python3                     python 解析器（默认自动探测 python3/python/py）
#
# Note: macOS ships bash 3.2 — no `mapfile`, no associative arrays, no ${var,,}.
# Keep the code below compatible with bash 3.2.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE_DIR:-$SCRIPT_DIR}"
# MITM_PROXY 解析：环境变量 > 工作区 proxy.cfg（start_proxy.sh 写入）> direct
# direct = 不走 -x。列表/正文必须和 PC 微信从同一个公网 IP 出去；人在本机时直连即可。
if [ -z "${MITM_PROXY:-}" ] && [ -f "$WORKSPACE/proxy.cfg" ]; then
  cfgm=$(sed -n 's/^MITM_PROXY=//p' "$WORKSPACE/proxy.cfg" 2>/dev/null | tr -d '\r')
  [ -n "$cfgm" ] && MITM_PROXY="$cfgm"
fi
MITM_PROXY="${MITM_PROXY:-direct}"
PARAMS_FILE="${PARAMS_FILE:-$WORKSPACE/params.txt}"

# ---- python 解析器：Windows(Git Bash) 上可能叫 python / py，mac/Linux 叫 python3 ----
# 统一用 $PY 调用（fetch_list/fetch_bodies 内的 python3 已改 $PY）。
if [ -z "${PY:-}" ]; then
  for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
fi
if [ -z "${PY:-}" ]; then
  echo "找不到 python3/python/py，请安装 Python 3 或用环境变量 PY 指定解析器" >&2
  exit 1
fi

# WeChat desktop UA
UA_WIN='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) WindowsWeixin(0x63090C0B-0x0)'

# ---- load_params: read params.txt into globals biz/key/pt/tok/cookie/uin ----
# Values may contain '=' (the cookie does), so split each line on the FIRST '='.
# Returns 0 only when key AND tok are both present (they're essential for getmsg).
load_params() {
  biz=; key=; pt=; tok=; cookie=; uin=
  [ -f "$PARAMS_FILE" ] || return 1
  local line k v
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '' | '#'*) continue ;;
    esac
    k="${line%%=*}"; v="${line#*=}"
    case "$k" in
      biz) biz="$v" ;;
      key) key="$v" ;;
      pt) pt="$v" ;;
      tok) tok="$v" ;;
      cookie) cookie="$v" ;;
      uin) uin="$v" ;;
    esac
  done <"$PARAMS_FILE"
  [ -n "$key" ] && [ -n "$tok" ]
}

# 本机直连与微信同出口。MITM_PROXY 为 http(s)://... 时才 -x（跨机器 curl）。
# -k 只在走 mitmproxy 时需要；直连校验微信自己的证书。
curl_via_proxy() {
  case "$MITM_PROXY" in
    direct|DIRECT) curl -s "$@" ;;
    *) curl -s -x "$MITM_PROXY" -k "$@" ;;
  esac
}

# File size in bytes (works on macOS `stat -f%z` and Linux `stat -c%s`).
filesize() {
  local f="$1"
  if [ -e "$f" ]; then
    stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0
  else
    echo 0
  fi
}