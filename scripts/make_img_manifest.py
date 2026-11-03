#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从抓到的正文 html/{mid}.html 生成图片下载清单 img_manifest.json。

每篇：[{mid, imgs:[url,...]}]，imgs 按正文 data-src 出现顺序（与 make_html.py 序号一致），
URL 已 html.unescape（&amp; -> &，curl 才能直接下）。
用法：python3 make_img_manifest.py [html_dir=html] [out=img_manifest.json]
"""
import json, re, os, sys, html

HTML_DIR = 'html'
OUT = 'img_manifest.json'


def main():
    global HTML_DIR, OUT
    for a in sys.argv[1:]:
        if a.startswith('html_dir='):
            HTML_DIR = a.split('=', 1)[1]
        elif a.startswith('out='):
            OUT = a.split('=', 1)[1]
    manifest = []
    for f in sorted(os.listdir(HTML_DIR)):
        if not f.endswith('.html'):
            continue
        mid = f[:-5]
        body = open(os.path.join(HTML_DIR, f), encoding='utf-8', errors='replace').read()
        imgs = []
        for mm in re.finditer(r'data-src="([^"]+)"', body):
            u = html.unescape(mm.group(1)).strip()
            if u:  # 不去重：同一 URL 出现多次也保留，序号与 make_html 一一对应
                imgs.append(u)
        if imgs:
            manifest.append({'mid': mid, 'imgs': imgs})
    with open(OUT, 'w', encoding='utf-8') as fo:
        json.dump(manifest, fo, ensure_ascii=False, indent=1)
    print('articles with images:', len(manifest), '->', OUT)


if __name__ == '__main__':
    main()