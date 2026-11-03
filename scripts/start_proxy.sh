#!/usr/bin/env bash
# 启动 mitmproxy，只劫持微信文章页进程，不改系统代理。
#
# 默认 --mode local（mitmproxy 10.2+）：操作系统把指定进程的新连接送进 mitmdump，
# 其它应用保持原样。文章参数来自 WeChatAppEx 的 Chromium 网络服务
# （命令行含 network.mojom.NetworkService）。进程已在跑就按 PID 劫持；
# 还没启动微信时退回进程名 WeChatAppEx / WeChatAppEx Helper / WeChatAppEx.exe。
# 不包含主进程 WeChat / Weixin，避免把聊天长连接卷进来。
#
# 已打开的文章页会复用旧的 HTTP/2，local 模式看不到那条连接。启动成功后重置
# 文章页进程上「非回环、对端端口 443」的 TCP 状态，让 jsmonitor 重连。
# macOS 用 `pfctl -k`（需要 sudo）。没有免密 sudo 时只打印命令，不退出微信。
#
# 抓列表/正文不走这个劫持。proxy.cfg 写 MITM_PROXY=direct，curl 在本机直连
# （和微信同一个公网出口）。只有 curl 跑在别的机器上才用 WX_MITM_MODE=regular
# 开一个仅供 curl -x 的端口，并且仍然不要把它设成系统代理。
#
# ponytail: allow_hosts 只解密 mp.weixin.qq.com；同一个网络服务进程的其它流量
# 仍会进 local 模式再透传。小程序/内置页因此异常时，把 WX_LOCAL_PROCS 设成
# 当时的 network service PID，抓完执行 --stop。
#
# Usage:
#   bash start_proxy.sh                 # 启动（或按进程重启）并重置旧 443
#   bash start_proxy.sh --wait-key [秒] # 同上，并等到新流量里出现 key=daf9bd
#   bash start_proxy.sh --stop          # 停掉 mitm.pid
#
# 环境变量：
#   WX_MITM_MODE=local|regular   默认 local
#   WX_LOCAL_PROCS=名或PID列表    覆盖自动发现（逗号分隔，可含空格）
#   WX_ALLOW_HOSTS=正则           默认只解密 mp.weixin.qq.com
#   WX_MITM_PORTS=...             仅 regular 模式的候选端口
#   MITMDUMP=mitmdump
#   WX_PROXY_CFG / WX_FLOWS
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

PROXY_CFG="${WX_PROXY_CFG:-$HERE/proxy.cfg}"
FLOWS="${WX_FLOWS:-$HERE/wechat_flows.jsonl}"
CANDIDATES="${WX_MITM_PORTS:-8868 10809 8088 8964 8080}"
MITM_CMD="${MITMDUMP:-mitmdump}"
PID_FILE="$HERE/mitm.pid"
LOG_FILE="$HERE/mitm.log"
MODE="${WX_MITM_MODE:-local}"
ALLOW_HOSTS="${WX_ALLOW_HOSTS:-^mp\.weixin\.qq\.com(:[0-9]+)?$}"

PY="${PY:-}"
if [ -z "$PY" ]; then
  for cand in python3 python py; do
    command -v "$cand" >/dev/null 2>&1 && { PY="$cand"; break; }
  done
fi
[ -n "$PY" ] || { echo "找不到 python3/python/py，请安装 Python 3" >&2; exit 1; }

DO_WAIT=0
WAIT_SECS=25
if [ "${1:-}" = "--stop" ]; then
  if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE")
    kill "$pid" 2>/dev/null && echo "已停止 mitmdump（pid $pid）" || echo "pid $pid 已不存在"
    rm -f "$PID_FILE"
  else
    echo "没有 mitm.pid，无需停止"
  fi
  exit 0
fi
if [ "${1:-}" = "--wait-key" ]; then
  DO_WAIT=1
  WAIT_SECS="${2:-25}"
fi

# 逗号分隔。微信已运行时优先用网络服务 PID；否则用进程名（主进程不在其中）。
discover_spec() {
  if [ -n "${WX_LOCAL_PROCS:-}" ]; then
    printf '%s\n' "$WX_LOCAL_PROCS"
    return
  fi
  local pids="" os
  os=$(uname -s)
  case "$os" in
    MINGW*|MSYS*|CYGWIN*)
      if command -v powershell.exe >/dev/null 2>&1; then
        pids=$(powershell.exe -NoProfile -Command 'Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "network.mojom.NetworkService" -and $_.Name -like "WeChatAppEx*" } | ForEach-Object { $_.ProcessId }' 2>/dev/null | tr -d '\r' | paste -sd, - || true)
      fi
      ;;
    *)
      pids=$(ps -ax -o pid=,command= 2>/dev/null | awk '/WeChatAppEx/ && /network\.mojom\.NetworkService/ && !/awk/ {print $1}' | paste -sd, - || true)
      ;;
  esac
  if [ -n "$pids" ]; then
    printf '%s\n' "$pids"
  else
    printf '%s\n' 'WeChatAppEx,WeChatAppEx Helper,WeChatAppEx.exe'
  fi
}

pid_is_ours() {
  [ -f "$PID_FILE" ] || return 1
  local pid cmd
  pid=$(cat "$PID_FILE" 2>/dev/null || true)
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
  if [ -n "$cmd" ]; then
    echo "$cmd" | grep -q 'saver.py' || return 1
  fi
  return 0
}

stop_recorded() {
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
    sleep 0.5
  fi
}

cfg_get() {
  sed -n "s/^$1=//p" "$PROXY_CFG" 2>/dev/null | tr -d '\r' | head -n 1
}

write_local_cfg() {
  printf 'MODE=local\nPROCS=%s\nMITM_PROXY=direct\n' "$1" > "$PROXY_CFG"
}

# 重置文章页进程上已建立的外网 443，让下一次 jsmonitor 走新连接。
# 不碰 127.0.0.0/8，避免掐断微信自己的本机 IPC。
reset_article_conns() {
  local os pids
  os=$(uname -s)
  case "$os" in
    MINGW*|MSYS*|CYGWIN*)
      echo "Windows 没有 pfctl。不必退出微信：关掉文章页再点开一篇，然后 bash start_proxy.sh --wait-key"
      return 0
      ;;
  esac
  pids=$(ps -ax -o pid=,command= 2>/dev/null | awk '/WeChatAppEx/ && /network\.mojom\.NetworkService/ && !/awk/ {print $1}' | paste -sd, - || true)
  if [ -z "$pids" ]; then
    pids=$(ps -ax -o pid=,command= 2>/dev/null | awk '/WeChatAppEx/ && !/awk/ {print $1}' | paste -sd, - || true)
  fi
  if [ -z "$pids" ]; then
    echo "微信文章页进程还没起来。先打开一篇文章（不必退出微信），再跑 bash start_proxy.sh --wait-key"
    return 0
  fi
  pairs=$("$PY" - "$pids" <<'PY'
import subprocess, sys, re
pids = [p for p in sys.argv[1].split(',') if p]
pairs = set()
for pid in pids:
    try:
        out = subprocess.check_output(
            ['lsof', '-nP', '-a', '-p', pid, '-iTCP', '-sTCP:ESTABLISHED'],
            text=True, stderr=subprocess.DEVNULL)
    except Exception:
        continue
    for line in out.splitlines():
        m = re.search(r'(\d+\.\d+\.\d+\.\d+):\d+->(\d+\.\d+\.\d+\.\d+):(\d+)', line)
        if not m:
            continue
        src, dst, port = m.group(1), m.group(2), m.group(3)
        if port != '443' or dst.startswith('127.') or src.startswith('127.'):
            continue
        pairs.add((src, dst))
for src, dst in sorted(pairs):
    print(src, dst)
PY
)
  if [ -z "$pairs" ]; then
    echo "没有需要重置的文章页外网 443（新请求会被劫持）。已开着文章仍抓不到时，在文章页点一下或下拉，不必退出微信"
    return 0
  fi
  if ! sudo -n true 2>/dev/null; then
    echo "旧连接还在。不必退出微信，在自己的终端执行下面的命令（需要 sudo）后再 --wait-key：" >&2
    printf '%s\n' "$pairs" | while read -r src dst; do
      [ -n "$src" ] && echo "sudo pfctl -k $src -k $dst" >&2
    done
    return 0
  fi
  printf '%s\n' "$pairs" | while read -r src dst; do
    [ -n "$src" ] || continue
    sudo -n pfctl -k "$src" -k "$dst" >/dev/null && echo "已重置 $src -> $dst"
  done
}

wait_for_key() {
  local secs="$1" off="$2" i=0
  while [ "$i" -lt "$secs" ]; do
    if [ -f "$FLOWS" ] && "$PY" - "$FLOWS" "$off" <<'PY'
import os, sys
path, off = sys.argv[1], int(sys.argv[2] or 0)
try:
    size = os.path.getsize(path)
except OSError:
    sys.exit(1)
if off > size:
    off = 0
with open(path, 'rb') as f:
    f.seek(off)
    data = f.read().decode('utf-8', 'replace')
sys.exit(0 if ('mp.weixin.qq.com' in data and 'daf9bd' in data) else 1)
PY
    then
      echo "OK：新增流量里已有 mp.weixin.qq.com 且带 key=daf9bd"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "还没有新的带 key 的文章请求。保持文章页开着（不必退出微信），点一下或下拉后再跑：bash start_proxy.sh --wait-key" >&2
  echo "证书：macOS 须装系统钥匙串（SKILL.md 坑 13）。日志：$LOG_FILE" >&2
  return 1
}

flows_offset() {
  if [ -f "$FLOWS" ]; then
    wc -c < "$FLOWS" | tr -d '[:space:]'
  else
    echo 0
  fi
}

port_free() {
  "$PY" - "$1" <<'PY'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('127.0.0.1', int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

proxy_up() {
  local p="$1" code
  code=$(curl -s -m 6 -x "http://127.0.0.1:$p" -k -o /dev/null -w '%{http_code}' \
      'https://mp.weixin.qq.com/' 2>/dev/null || echo 000)
  [ "$code" != "000" ]
}

pick_port() {
  local p_cfg="" p
  if [ -f "$PROXY_CFG" ]; then
    p_cfg=$(cfg_get PORT)
    if [ -n "$p_cfg" ]; then
      if port_free "$p_cfg"; then echo "$p_cfg"; return
      elif proxy_up "$p_cfg"; then echo "$p_cfg"; return
      else echo "proxy.cfg 里的端口 $p_cfg 已被别的进程占用，改挑新端口" >&2; fi
    fi
  fi
  for p in $CANDIDATES; do
    if port_free "$p"; then echo "$p"; return; fi
    echo "端口 $p 被占用，试下一个…" >&2
  done
  echo "候选端口全部被占用：${CANDIDATES}；用 WX_MITM_PORTS 指定" >&2
  exit 1
}

after_local_up() {
  local spec="$1" off
  write_local_cfg "$spec"
  off=$(flows_offset)
  reset_article_conns
  if [ "$DO_WAIT" = "1" ]; then
    wait_for_key "$WAIT_SECS" "$off"
    return $?
  fi
  echo "劫持已启动。不改系统代理，不必退出微信。打开或保持文章页后执行：bash start_proxy.sh --wait-key"
  return 0
}

SPEC=""
if [ "$MODE" = "local" ]; then
  SPEC=$(discover_spec)
fi

if pid_is_ours; then
  old_mode=$(cfg_get MODE)
  old_spec=$(cfg_get PROCS)
  if [ "$MODE" = "local" ] && [ "$old_mode" = "local" ] && [ "$old_spec" = "$SPEC" ]; then
    echo "mitmproxy local 已在运行（pid $(cat "$PID_FILE")，进程 $SPEC），复用"
    after_local_up "$SPEC"
    exit $?
  fi
  echo "已有 mitmdump 与本次模式/进程不一致，先停掉再启动"
  stop_recorded
fi

command -v "$MITM_CMD" >/dev/null 2>&1 || {
  echo "找不到 ${MITM_CMD}：先安装 mitmproxy 10.2+（macOS: brew install --cask mitmproxy）" >&2
  exit 1
}

if [ "$MODE" = "regular" ]; then
  echo "警告：regular 只给「curl 不在这台机器上」提供 -x 端口。不要把它设成系统代理。" >&2
  PORT="$(pick_port)"
  if proxy_up "$PORT" && pid_is_ours; then
    printf 'MODE=regular\nPORT=%s\nMITM_PROXY=http://127.0.0.1:%s\n' "$PORT" "$PORT" > "$PROXY_CFG"
    echo "mitmproxy 已在端口 $PORT 运行（pid $(cat "$PID_FILE")），复用"
    exit 0
  fi
  printf 'MODE=regular\nPORT=%s\nMITM_PROXY=http://127.0.0.1:%s\n' "$PORT" "$PORT" > "$PROXY_CFG"
  nohup "$MITM_CMD" -p "$PORT" --ssl-insecure -q -s "$HERE/saver.py" --set keep_host_header=true \
      >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 1
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "mitmdump 退出了。日志：" >&2
    tail -n 40 "$LOG_FILE" >&2
    exit 1
  fi
  echo "regular 已监听 127.0.0.1:${PORT}（仅供 MITM_PROXY，不是系统代理）"
  exit 0
fi

if [ "$MODE" != "local" ]; then
  echo "WX_MITM_MODE 只能是 local 或 regular，当前是 $MODE" >&2
  exit 1
fi

ver=$("$MITM_CMD" --version 2>&1 | head -n 1 || true)
major=$(printf '%s\n' "$ver" | sed -n 's/.*Mitmproxy: \([0-9][0-9]*\).*/\1/p')
if [ -n "$major" ] && [ "$major" -lt 10 ]; then
  echo "local 模式需要 mitmproxy 10.2+，当前是：$ver" >&2
  exit 1
fi

nohup "$MITM_CMD" --mode "local:${SPEC}" --ssl-insecure -q \
    --allow-hosts "$ALLOW_HOSTS" \
    -s "$HERE/saver.py" --set keep_host_header=true \
    >"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 2
if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "mitmdump 退出了。日志：" >&2
  tail -n 40 "$LOG_FILE" >&2
  exit 1
fi
echo "已启动 local 劫持（pid $(cat "$PID_FILE")，--mode local:${SPEC}）"
echo "只解密 mp.weixin.qq.com。首次若系统弹出网络扩展授权，允许 mitmproxy 后再 --wait-key。日志：$LOG_FILE"
after_local_up "$SPEC"
exit $?
