#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信文章 HTML -> Markdown 转换器（可选交付格式）。

用法（在 scripts/ 目录下）：
  env STRIP_IMAGES=1 python3 convert.py           # 批量转换全部 html/*.html -> 工作区根/articles_md/（纯文字，删图）
  python3 convert.py html/2652168539.html          # 单篇测试（打印结果预览）
交付目录 = 脚本所在目录的上一级（工作区根）下的 articles_md/；可用 DELIVERY_ROOT 环境变量换根。
原文链接中的 __biz 优先从 params.txt 读取，缺省回退到原写死的示例值。

兼容（标题/时间/正文提取统一走 wechat_extract.py，包含 item_show_type=7/8/10
与音频等特殊类型的解析；跳过时会带具体原因）：
  - 老式模板：<div id="js_content">（正文 HTML 直取）
  - 新版「分享页」模板：js_content div 缺失时从 og:title 提取全文（段落为字面 "\\n"，已归一化）
  - 平台已删的文章（壳页无 og:title/正文）会被跳过，不产出空文件
"""
import re, os, glob, html as htmllib
from html.parser import HTMLParser

import wechat_extract as w

# strip 模式（纯文字，丢弃图片）：STRIP_IMAGES=1 时生效；默认保留图片方式不变
STRIP_IMAGES = os.environ.get('STRIP_IMAGES', '') == '1'

# 交付目录：脚本惯例放在 工作区根/scripts/ 下运行 → 交付物写到工作区根（scripts/ 的上一级）。
# 需要换根时用环境变量 DELIVERY_ROOT 显式指定（如 DELIVERY_ROOT=/srv/out python3 convert.py）。
_DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DELIVERY_ROOT = os.environ.get('DELIVERY_ROOT') or _DEFAULT_ROOT


def articles_md_dir():
    return os.path.join(DELIVERY_ROOT, 'articles_md')


def get_biz():
    try:
        with open('params.txt', encoding='utf-8') as f:
            for line in f:
                if line.startswith('biz='):
                    return line.strip()[4:]
    except Exception:
        pass
    return ''


class WxParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip_depth = 0
        self.in_pre = 0
        self.in_code = 0
        self.in_a = 0
        self.a_href = None
        self.in_li = 0
        self.in_list = None  # 'ul' or 'ol'
        self.list_count = 0
        self.in_h = 0
        self.h_level = 0
        self.block_seen = False  # 当前块是否有内容
        self.strong = 0
        self.em = 0
        self.in_script_style = 0
        self.pending_newline = 0

    # ---- 工具 ----
    def emit(self, s):
        self.out.append(s)

    def newline(self):
        # 避免连续空行
        if self.out and self.out[-1] == '\n':
            return
        self.out.append('\n')

    def text_to_out(self, t):
        t = t.replace('​', '')
        if not t:
            return
        if self.in_pre:
            self.emit(t)
            return
        # 清理空白（保留单词间空格）
        self.emit(re.sub(r'\s+', ' ', t))

    # ---- 标签 ----
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style'):
            self.in_script_style += 1
            return
        if self.in_script_style:
            return
        if tag == 'section' or tag == 'div':
            if self.block_seen and not self.in_li:
                self.newline()
            self.block_seen = False
            return
        if tag == 'p':
            if self.block_seen and not self.in_li:
                self.newline()
            self.block_seen = False
            return
        if tag == 'br':
            self.newline()
            self.block_seen = False
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            if self.block_seen:
                self.newline()
            self.in_h = 1
            self.h_level = int(tag[1])
            self.block_seen = True
            self.emit('#' * self.h_level + ' ')
            return
        if tag == 'strong' or tag == 'b':
            self.strong += 1
            return
        if tag == 'em' or tag == 'i':
            self.em += 1
            return
        if tag == 'code':
            if not self.in_pre:
                self.in_code += 1
                self.emit('`')
            return
        if tag == 'pre':
            self.in_pre += 1
            self.newline()
            self.emit('```\n')
            self.block_seen = True
            return
        if tag == 'a':
            self.in_a += 1
            self.a_href = a.get('href') or a.get('data-href') or ''
            return
        if tag == 'ul':
            self.in_list = 'ul'
            self.newline()
            return
        if tag == 'ol':
            self.in_list = 'ol'
            self.list_count = 0
            self.newline()
            return
        if tag == 'li':
            self.in_li += 1
            if self.block_seen:
                self.newline()
            if self.in_list == 'ol':
                self.list_count += 1
                self.emit(str(self.list_count) + '. ')
            else:
                self.emit('- ')
            self.block_seen = True
            return
        if tag == 'blockquote':
            self.newline()
            self.emit('> ')
            self.block_seen = True
            return
        if tag == 'img':
            if STRIP_IMAGES:
                # 纯文字模式：丢弃图片，不打断周围正文
                return
            src = a.get('data-src') or a.get('src') or ''
            src = htmllib.unescape(src)
            alt = a.get('alt') or ''
            if src:
                if self.block_seen:
                    self.newline()
                self.emit('![' + alt + '](' + src + ')')
                self.newline()
                self.block_seen = False
            return
        if tag == 'hr':
            self.newline()
            self.emit('---')
            self.newline()
            return

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            if self.in_script_style > 0:
                self.in_script_style -= 1
            return
        if self.in_script_style:
            return
        if tag == 'p' or tag == 'section' or tag == 'div':
            if self.block_seen and not self.in_li:
                self.newline()
            self.block_seen = False
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.in_h = 0
            self.newline()
            self.block_seen = False
            return
        if tag == 'strong' or tag == 'b':
            self.strong = max(0, self.strong - 1)
            return
        if tag == 'em' or tag == 'i':
            self.em = max(0, self.em - 1)
            return
        if tag == 'code':
            if self.in_code > 0:
                self.in_code -= 1
                self.emit('`')
            return
        if tag == 'pre':
            self.in_pre = max(0, self.in_pre - 1)
            self.emit('\n```\n')
            self.newline()
            self.block_seen = False
            return
        if tag == 'a':
            if self.in_a > 0:
                self.in_a -= 1
            self.a_href = None
            return
        if tag == 'ul' or tag == 'ol':
            self.in_list = None
            self.newline()
            return
        if tag == 'li':
            self.in_li = max(0, self.in_li - 1)
            self.newline()
            self.block_seen = False
            return
        if tag == 'blockquote':
            self.newline()
            self.block_seen = False
            return

    def handle_data(self, data):
        if self.in_script_style:
            return
        self.text_to_out(data)
        if data.strip():
            self.block_seen = True


def extract_article(body):
    """兼容旧接口：返回 (title, pubtime, content_html)；无正文时 content_html 为空串。"""
    info = w.extract_article(body)
    return info['title'], info['pubtime'], info['content']


def clean_md(text):
    text = re.sub(r'\n{3,}', '\n\n', text)  # 连续空行最多 2 个
    text = re.sub(r'[ \t]+\n', '\n', text)  # 行尾空格
    return text.strip() + '\n'


def html_to_md(content_html):
    p = WxParser()
    try:
        p.feed(content_html)
        p.close()
    except Exception:
        pass
    return clean_md(''.join(p.out))


def short_link_of(body):
    """从正文 HTML 提取规范的 /s/<hash> 短链（无需会话参数即可打开）；没有则返回空串。
    长链 /s?... 带会话参数，浏览器打开会报 parameter error，故优先用 short_link。
    优先 window.short_link，其次 short_link: 字段。"""
    for pat in (
        r'window\.short_link\s*=\s*[\'"]((?:https?:)?//mp\.weixin\.qq\.com/s/[A-Za-z0-9_\-]+)[\'"]',
        r'short_link:\s*[\'"]((?:https?:)?//mp\.weixin\.qq\.com/s/[A-Za-z0-9_\-]+)[\'"]',
    ):
        m = re.search(pat, body)
        if m:
            u = m.group(1)
            return 'https:' + u if u.startswith('//') else u
    return ''


def stem_mid(stem):
    """文件名 {mid}_{idx}.html 的前缀数字 -> mid；兼容旧式 {mid}.html。"""
    m = re.match(r'^(\d+)', stem)
    return m.group(1) if m else stem


def process_file(path, out_dir):
    """返回 (结果 dict 或 None, 跳过原因或 None)。"""
    body = open(path, encoding='utf-8', errors='replace').read()
    info = w.extract_article(body)
    content_html = info['content']
    # 无正文：验证页/壳页/平台已删/纯 JS 渲染 → 不产出文件，返回具体原因
    if not content_html:
        return None, info['reason'] or '无正文(平台已删或纯JS渲染)'
    md_body = html_to_md(content_html)
    stem = os.path.basename(path)[:-5]
    mid = stem_mid(stem)
    title = info['title']
    header = '# ' + (title or stem) + '\n\n'
    if info['pubtime']:
        header += '> 发布时间：' + info['pubtime'] + '\n\n'
    biz = get_biz()
    link = short_link_of(body) or 'https://mp.weixin.qq.com/s?__biz=' + (biz or 'MjM5ODI5Njc2MA==') + '&mid=' + mid
    header += '> 原文链接：' + link + '\n\n---\n\n'
    md = header + md_body
    os.makedirs(out_dir, exist_ok=True)
    # 文件名 = 文章标题（重名自动加 _2/_3），与 make_html 一致；标题为空回退 mid
    fname = w.sanitize(title or mid)
    out_path = os.path.join(out_dir, fname + '.md')
    n = 1
    while os.path.exists(out_path):
        out_path = os.path.join(out_dir, '%s_%d.md' % (fname, n))
        n += 1
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(md)
    return ({'mid': mid, 'title': title, 'pubtime': info['pubtime'],
             'file': os.path.basename(out_path), 'len': len(md)}, None)


if __name__ == '__main__':
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(glob.glob('html/*.html'))
    print('total html:', len(files))
    out_dir = articles_md_dir()
    if test:
        r, reason = process_file(test, out_dir)
        print('TEST result:', r)
        if r:
            p = os.path.join(out_dir, r['file'])
            print(open(p, encoding='utf-8').read()[:800])
        else:
            print('TEST SKIP:', test, reason)
    else:
        # 批量模式：无参数时对全部 html/*.html 转换（写到 工作区根/articles_md/）
        n_ok, n_skip = 0, 0
        for f in files:
            r, reason = process_file(f, out_dir)
            if r:
                n_ok += 1
            else:
                n_skip += 1
                print('SKIP', os.path.basename(f), reason or '')
        print('converted: %d / %d (skip %d)' % (n_ok, len(files), n_skip))