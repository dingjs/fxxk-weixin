#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把抓到的微信正文 HTML 转成可交付的单文件 HTML：
- 文件名 = 文章标题（非法字符替换为 _，超长截断，重名自动 _2/_3）
- UI：统一卡片样式 + 字体栈覆盖微信残留内联旧字体（-apple-system-font 等）
- 修复：微信正文容器内联 `visibility:hidden`（JsContent 靠 JS 揭晓）→ 提取时替换容器标签
  + CSS `.article-content *{visibility:visible !important}` 兜底，页面不再整篇不可见
- 正文只保留到 rich_media_tool 标记，剔除尾部 script/style 残留

图片模式 img_mode=（由用户决定，默认 embed）：
（标题/时间/昵称/正文提取统一走 wechat_extract.py：含 item_show_type=7/8/10
  图集文/短内容/音频分享与音频文章等特殊类型，跳过时带具体原因）
  embed  默认：读 img/{mid}_{seq}.{ext}，图片 base64 内嵌 → 单文件自包含、永久离线（需先跑
          make_img_manifest.py + download_imgs 下载图片）；缺图自动退化为远程 URL 不丢图
  remote 不下载图片：把 data-src 换成真实远程 mmbiz.qpic.cn URL 作为 src，文件小、需联网看图
  strip  不保留图片：直接删除 <img>，纯文字存档

用法：python3 make_html.py [html_dir=html] [img_dir=img] [out_dir=<工作区根>/articles_html] [img_mode=embed|remote|strip]
交付目录默认为脚本上一级（工作区根）下的 articles_html/；可用 DELIVERY_ROOT 环境变量或 out_dir= 覆盖。
"""
import re, os, sys, base64, html as htmllib

import wechat_extract as w

# 交付目录：脚本惯例放在 工作区根/scripts/ 下运行 → 交付物写到工作区根（scripts/ 的上一级）。
_DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DELIVERY_ROOT = os.environ.get('DELIVERY_ROOT') or _DEFAULT_ROOT
HTML_DIR = 'html'   # 中间产物正文，跑的时候位于工作区/scripts/ 下
IMG_DIR = 'img'
OUT_DIR = os.path.join(DELIVERY_ROOT, 'articles_html')
IMG_MODE = 'embed'  # embed | remote | strip
_SKIP_REASONS = []  # [(mid, reason), ...]


def img_ext(url):
    ul = url.lower()
    if 'wx_fmt=gif' in ul or 'mmbiz_gif' in ul: return 'gif'
    if 'wx_fmt=png' in ul or 'mmbiz_png' in ul: return 'png'
    if 'wx_fmt=webp' in ul: return 'webp'
    return 'jpg'


PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE%</title>
<style>
:root{
  --ink:#26282c; --ink-strong:#1a1a1a; --muted:#8a919c;
  --line:#e7e9ee; --bg:#f4f5f7; --card:#fff; --accent:#2f6fde;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;padding:28px 14px 64px;background:var(--bg);color:var(--ink);
     font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
     line-height:1.8;font-size:16px;-webkit-font-smoothing:antialiased}
.page{max-width:760px;margin:0 auto}
.article-head{padding:6px 4px 16px}
.article-title{font-size:22px;line-height:1.45;font-weight:700;color:var(--ink-strong);margin:0 0 10px;letter-spacing:.2px}
.article-meta{font-size:13px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:12px}
.article-content{background:var(--card);padding:26px 22px;border-radius:10px;box-shadow:0 1px 2px rgba(0,0,0,.04),0 4px 16px rgba(0,0,0,.04)}
/* 微信正文残留内联样式（旧字体 / visibility:hidden / 异常行高）统一强制覆盖 */
.article-content, .article-content p, .article-content div,
.article-content section, .article-content span, .article-content li,
.article-content blockquote, .article-content td, .article-content th{
  font-family:inherit !important; line-height:1.8 !important;
}
.article-content *{visibility:visible !important}
.article-content{font-size:16px;color:var(--ink);word-break:break-word;overflow-wrap:break-word}
.article-content p{margin:0 0 1em}
.article-content section{margin:.6em 0}
.article-content img{max-width:100%;height:auto;display:block;margin:14px auto;border-radius:4px}
.article-content a{color:var(--accent);text-decoration:none}
.article-content h1,.article-content h2,.article-content h3,
.article-content h4,.article-content h5,.article-content h6{
  font-weight:700;color:var(--ink-strong);margin:1.2em 0 .6em;font-size:1.15em}
.article-content blockquote{border-left:4px solid #c9d1d9;padding:2px 1em;margin:1em 0;
  color:#57606a;background:#f6f8fa;border-radius:0 6px 6px 0}
.article-content pre{background:#f6f8fa;padding:12px 14px;overflow-x:auto;border-radius:6px;font-size:13px;line-height:1.6}
.article-content code{background:#f0f1f3;padding:2px 5px;border-radius:4px;font-size:.92em;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.article-content pre code{background:none;padding:0}
.article-content table{border-collapse:collapse;margin:1em 0;width:100%}
.article-content th,.article-content td{border:1px solid #e2e4e8;padding:6px 10px;text-align:left}
.article-content hr{border:none;border-top:2px solid var(--line);margin:1.6em 0}
</style>
</head>
<body>
<div class="page">
  <div class="article-head">
    <h1 class="article-title">%TITLE%</h1>
    <div class="article-meta"><span>%NICKNAME%</span><span>发布于 %PUBTIME%</span></div>
  </div>
%BODY%
</div>
</body>
</html>'''


def rebuild_img(tag, src):
    """去掉占位 src，把 data-src 换成真实 src。返回新标签。"""
    new = re.sub(r'\ssrc="[^"]*"', '', tag)
    dm = re.search(r'data-src="([^"]+)"', tag)
    if dm:
        new = new.replace('data-src="%s"' % dm.group(1), 'src="%s"' % src, 1)
    return new


def process_one(path):
    global _SKIP_REASONS
    mid = os.path.basename(path)[:-5]
    body = open(path, encoding='utf-8', errors='replace').read()
    info = w.extract_article(body)
    title = info['title'] or mid
    pubtime = info['pubtime']
    nickname = info['nickname']
    content_html = info['content']
    if not content_html:
        _SKIP_REASONS.append((mid, info['reason'] or '无正文(平台已删或纯JS渲染)'))
        return None
    # 提取层（wechat_extract.py）已剥离开标签并剔除 script/style，
    # 这里换掉微信正文容器的残留属性（内联 visibility:hidden 等），用自家干净容器
    content = '<div class="article-content">' + content_html

    seq = 0
    replaced = 0
    for mm in re.finditer(r'<img[^>]*>', content):
        tag = mm.group(0)
        dm = re.search(r'data-src="([^"]+)"', tag)
        if not dm:
            continue
        seq += 1
        url = htmllib.unescape(dm.group(1))
        if IMG_MODE == 'strip':
            content = content.replace(tag, '', 1)
            continue
        if IMG_MODE == 'remote':
            content = content.replace(tag, rebuild_img(tag, url), 1)
            continue
        # embed：读本地图片，缺图退化为远程 URL（不丢图）
        ext = img_ext(url)
        imgf = os.path.join(IMG_DIR, '%s_%d.%s' % (mid, seq, ext))
        if not os.path.exists(imgf):
            content = content.replace(tag, rebuild_img(tag, url), 1)
            continue
        b64 = base64.b64encode(open(imgf, 'rb').read()).decode()
        data_uri = 'data:image/%s;base64,%s' % (ext, b64)
        content = content.replace(tag, rebuild_img(tag, data_uri), 1)
        replaced += 1

    page = (PAGE.replace('%TITLE%', title)
                .replace('%NICKNAME%', nickname or '微信公众号')
                .replace('%PUBTIME%', pubtime or '未知')
                .replace('%BODY%', content))
    fname = w.sanitize(title or mid)
    out_path = os.path.join(OUT_DIR, fname + '.html')
    n = 1
    while os.path.exists(out_path):
        out_path = os.path.join(OUT_DIR, '%s_%d.html' % (fname, n))
        n += 1
    with open(out_path, 'w', encoding='utf-8') as fo:
        fo.write(page)
    return {'mid': mid, 'title': title, 'file': os.path.basename(out_path),
            'imgs': seq, 'replaced': replaced,
            'size_kb': round(os.path.getsize(out_path) / 1024, 1)}


if __name__ == '__main__':
    for a in sys.argv[1:]:
        if a.startswith('html_dir='): HTML_DIR = a.split('=', 1)[1]
        elif a.startswith('img_dir='): IMG_DIR = a.split('=', 1)[1]
        elif a.startswith('out_dir='): OUT_DIR = a.split('=', 1)[1]
        elif a.startswith('img_mode='):
            v = a.split('=', 1)[1].strip().lower()
            if v in ('embed', 'remote', 'strip'):
                IMG_MODE = v
            else:
                print('img_mode 无效，使用 embed')
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(HTML_DIR) if f.endswith('.html'))
    print('img_mode =', IMG_MODE)
    ok = 0
    for f in files:
        try:
            r = process_one(os.path.join(HTML_DIR, f))
            if not r:
                print('SKIP', f)
                continue
            print('OK', r['file'], 'imgs', r['imgs'], '/', r['replaced'], r['size_kb'], 'KB')
            ok += 1
        except Exception as e:
            print('FAIL', f, e)
    print('done', ok, '/', len(files))
    if _SKIP_REASONS:
        print('跳过原因：', ', '.join('%s(%s)' % (m, r) for m, r in _SKIP_REASONS))