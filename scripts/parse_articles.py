#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 fetch_list 拉回的 getmsg_pages/*.json -> articles_list.json。

微信数据模型：每个「群发」bundle 用一个 mid 表示，内含最多 8 个子文章，靠
content_url 里的 idx=1..8 区分（主文 idx=1 + 附加文 idx=2..8）。因此去重键必须是
(mid, idx) 而非 mid——只按 mid 去重会把同一群发的附加文全部吞掉，只剩最后一条
（实测多为尾条小视频），宝贵的 idx=1 主文丢失。本版每条都保留、独立成篇。

每条消息含主文（app_msg_ext_info）+ 附加文（multi_app_msg_item_list），全部收入；
按 (mid, idx) 去重，按发布时间升序。字段：date（本地时间）、ts、title、mid、idx、
id（=mid_idx，便于下游命名）、url（content_url 已 html.unescape）。

用法：python3 parse_articles.py [pages_dir=getmsg_pages] [out=articles_list.json]
"""
import json, glob, os, sys, re, html, time

PAGES_DIR = 'getmsg_pages'
OUT = 'articles_list.json'


def parse_page(path, arts):
    try:
        data = json.load(open(path, encoding='utf-8'))
    except Exception:
        return 0
    if not data or data.get('ret') != 0:
        return 0
    gl = data.get('general_msg_list')
    if not gl:
        return 0
    try:
        info = json.loads(gl)
    except Exception:
        return 0
    items = info.get('list') or []
    n = 0
    for it in items:
        comm = it.get('comm_msg_info') or {}
        ext = it.get('app_msg_ext_info') or {}
        if not ext or comm.get('type') != 49:  # 49 = 图文消息
            continue
        for e in [ext] + (ext.get('multi_app_msg_item_list') or []):
            url = (e.get('content_url') or '').strip()
            if url:
                url = html.unescape(url)
            m = re.search(r'mid=(\d+)', url)
            if not m:
                continue
            mid = m.group(1)
            mi = re.search(r'idx=(\d+)', url)
            idx = mi.group(1) if mi else '0'
            key = (mid, idx)  # 群发共享 mid，子篇文章靠 idx 区分 → 必须 (mid, idx)
            ts = comm.get('datetime') or 0
            arts[key] = {
                'date': time.strftime('%Y-%m-%d %H:%M', time.localtime(ts)),
                'ts': ts,
                'title': (e.get('title') or mid).strip(),
                'mid': mid,
                'idx': idx,
                'id': '%s_%s' % (mid, idx),
                'url': url,
            }
            n += 1
    return n


def main():
    global PAGES_DIR, OUT
    for a in sys.argv[1:]:
        if a.startswith('pages_dir='):
            PAGES_DIR = a.split('=', 1)[1]
        elif a.startswith('out='):
            OUT = a.split('=', 1)[1]
    arts = {}
    total = 0
    for p in sorted(glob.glob(os.path.join(PAGES_DIR, '*.json'))):
        total += parse_page(p, arts)
    result = sorted(arts.values(), key=lambda x: x['ts'])
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print('parsed items:', total, 'unique articles:', len(result), '->', OUT)


if __name__ == '__main__':
    main()