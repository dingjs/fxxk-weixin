#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mitmproxy 插件：把匹配的流量（req/resp headers、解压后响应体）追加写 wechat_flows.jsonl。

加载：mitmdump --mode local:WeChatAppEx --allow-hosts mp.weixin.qq.com -s saver.py
日志写到本脚本所在目录（建议把 scripts/ 整体放在工作区运行）。
只记录 mp.weixin.qq.com 上带 key / __biz / appmsg_token 的请求，避免把整机流量写进 jsonl。
"""
import json, os, time, zlib
from mitmproxy import http

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wechat_flows.jsonl')
MAX_TEXT = 1500000  # 文本类响应体上限（解压后）
MAX_REQ = 20000


def _decompress(raw, encoding):
    """按 Content-Encoding 解压响应体（gzip/br/zstd）。"""
    if raw is None:
        return None
    enc = (encoding or '').lower()
    try:
        if 'gzip' in enc:
            return zlib.decompress(raw, 16 + zlib.MAX_WBITS)
        if 'deflate' in enc:
            try:
                return zlib.decompress(raw)
            except Exception:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
        if 'br' in enc:
            import brotli
            return brotli.decompress(raw)
        if 'zstd' in enc:
            import zstandard
            return zstandard.ZstdDecompressor().decompress(raw)
    except Exception:
        pass
    return raw


def _to_text(data, maxlen):
    if data is None:
        return None
    try:
        t = data.decode('utf-8', 'replace')
        if len(t) > maxlen:
            t = t[:maxlen] + '...[TRUNCATED]'
        return t
    except Exception:
        return None


class FlowSaver:
    def response(self, flow: http.HTTPFlow):
        try:
            req = flow.request
            resp = flow.response
            if resp is None:
                return
            host = (getattr(req, 'host', '') or '').split(':')[0].lower()
            url = req.pretty_url or ''
            cookie = req.headers.get('cookie', '') or ''
            blob = url + '\n' + (req.path or '') + '\n' + cookie
            # local 模式常把 Host 记成出口 IP，参数仍在 path 里。
            if ('key=' not in blob and '__biz=' not in blob
                    and 'appmsg_token' not in blob):
                return
            if host != 'mp.weixin.qq.com':
                host = 'mp.weixin.qq.com'
            raw = resp.raw_content or b''
            enc = resp.headers.get('content-encoding', '')
            body = _decompress(raw, enc)
            entry = {
                'ts': time.time(),
                'req_headers': dict(req.headers),
                'resp_headers': dict(resp.headers),
                'time_str': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
                'method': req.method,
                'url': req.pretty_url,
                'host': host,
                'path': req.path,
                'status': resp.status_code,
                'ctype': resp.headers.get('content-type', ''),
                'resp_size': len(raw),
                'resp_decoded_size': len(body) if body else 0,
                'content_encoding': enc,
                'req_ctype': req.headers.get('content-type', ''),
            }
            ctype = (resp.headers.get('content-type', '') or '').lower()
            if ('json' in ctype or 'text' in ctype or 'xml' in ctype or
                    'javascript' in ctype or 'html' in ctype) and body:
                # 大响应体单行可达 1.5MB+：fetch_bodies 的正文会把自己的流量文件撑爆，
                # 让尾部窗口提取（refresh_loop）失效。超大正文只留 2KB 小样 + 长度标记。
                dlen = len(body)
                if dlen > MAX_TEXT:
                    entry['resp_body'] = _to_text(body, 2000)
                    entry['resp_body_truncated'] = dlen
                else:
                    entry['resp_body'] = _to_text(body, MAX_TEXT)
            if req.content and len(req.content) <= MAX_REQ:
                rb = _to_text(req.content, MAX_REQ)
                if rb:
                    entry['req_body'] = rb
            with open(OUT, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception:
            pass


addons = [FlowSaver()]