#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""背景常驻：每 3 秒从 wechat_flows.jsonl 尾部提取最新会话参数 -> params.txt。

提取项：
  key / pass_ticket / uin       URL 参数（key 以 daf9bd 开头，2~4 分钟轮换一次）
  appmsg_token                  Windows 客户端放 Cookie，Mac 客户端放 URL 参数 → 两者都取
  cookie                        req_headers.Cookie 完整值（若有）
  __biz                         从 /s?__biz= 或 /mp/profile_ext?__biz= URL 提取（不再写死）

JSONL 位置：优先当前目录（工作区），找不到再回退到本脚本所在目录。
saver.py 把日志写在它自己旁边，建议把 scripts/ 全部放进同一个工作区再运行。
用法：python3 refresh_loop.py   （后台常驻）

容量：尾部读取窗口 8MB（非旧版 300KB）——既有 fetch_bodies 会把自己的正文大响应
（单行可达 1.5MB+）写进同一份 jsonl，窗口太小会整段落在一条大正文行中间导致解析失败。
注意：每次仅当提取到有效的 key 时才写 params.txt；找不到时保留上次有效参数（last-good），
避免把 params.txt 清空反过来饿死 fetch_bodies（曾因此把抓取流程搞挂）。
"""
import json, re, time, os, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))


def find_flows():
    # 先看工作区（cwd），再看脚本目录
    if os.path.exists('wechat_flows.jsonl'):
        return 'wechat_flows.jsonl'
    fallback = os.path.join(HERE, 'wechat_flows.jsonl')
    return fallback if os.path.exists(fallback) else 'wechat_flows.jsonl'


def tail_lines(path, max_bytes=8 * 1024 * 1024):
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            if size <= max_bytes:
                data = f.read()
            else:
                f.seek(size - max_bytes)
                data = f.read()
        text = data.decode('utf-8', 'replace')
        lines = text.splitlines()
        if size > max_bytes:
            lines = lines[1:]  # 丢弃可能被截断的半行
        return lines
    except Exception:
        return []


def qarg(u, name):
    """从 URL 提取查询参数（保留原始编码），取到返回字符串，否则 None。"""
    m = re.search(r'[?&]' + name + r'=([^&\s"\']+)', u)
    return m.group(1) if m else None


def latest_params(lines):
    keys, pts = [], []
    uin = cookie = tok = biz = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        h = r.get('req_headers', {}) or {}
        u = r.get('url', '')
        if 'mp.weixin.qq.com' not in (r.get('host', '') or ''):
            continue
        # __biz：URL 与 /s /profile_ext 请求均可能携带
        b = qarg(u, '__biz')
        if b:
            biz = b
        k = qarg(u, 'key')
        if k and k.startswith('daf9bd'):
            keys.append((k, r.get('ts', 0)))
        p = qarg(u, 'pass_ticket')
        if p:
            pts.append((urllib.parse.unquote(p), r.get('ts', 0)))
        un = qarg(u, 'uin')
        if un:
            uin = urllib.parse.unquote(un)
        # appmsg_token：Mac 客户端放在 URL 参数；Windows 放在 Cookie。两路都收
        t = qarg(u, 'appmsg_token')
        if t:
            tok = t
        ck = h.get('Cookie') or h.get('cookie') or ''
        if 'appmsg_token' in ck and not t:   # Cookie 只在 URL 无 token 时兜底
            cookie = ck
            m = re.search(r'appmsg_token=([^;\s]+)', ck)
            if m:
                tok = m.group(1)
        elif ck:
            cookie = ck
    keys.sort(key=lambda x: -x[1])
    pts.sort(key=lambda x: -x[1])
    return (keys[0][0] if keys else None, pts[0][0] if pts else None,
            uin, cookie, tok, biz)


def main():
    flows = find_flows()
    while True:
        try:
            key, pt, uin, cookie, tok, biz = latest_params(tail_lines(flows))
            if not key:
                # 尾窗没读到有效 flow（可能被正文大行占据元素）：保留上次有效参数，
                # 千万不要把 params.txt 清空——fetch_bodies 逐条读它，清空即全链路 NO_PARAM。
                time.sleep(3)
                continue
            with open('params.txt', 'w', encoding='ascii', errors='ignore') as f:
                f.write('biz=' + (biz or '') + '\n')
                f.write('key=' + (key or '') + '\n')
                f.write('pt=' + (pt or '') + '\n')
                f.write('tok=' + (tok or '') + '\n')
                f.write('cookie=' + (cookie or '') + '\n')
                f.write('uin=' + (uin or '') + '\n')
        except Exception:
            pass
        time.sleep(3)


if __name__ == '__main__':
    main()