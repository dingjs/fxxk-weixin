#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信文章正文提取共享模块（零三方可依赖，只用了 re + html + time）。

为什么有它：convert.py / make_html.py 之前各自内联了一份标题/时间/正文提取，
且只认识两种模板（js_content 老式 + og:title 分享页）。本模块把这些收敛到一处，
并补齐三种特殊文章类型（思路来自 wechat-download-api 的 utils/helpers.py，改成纯正则版）：
  - item_show_type=7   音频/视频分享页（Vue 动态壳，只取标题/作者/封面 + 占位说明）
  - item_show_type=8   图集文（picture_page_info_list 画廊 + meta description 文字）
  - item_show_type=10  短内容/转发文（content_noencode，新旧 JsDecode/裸串两格式）
  - 音频文章             mpvoice / mp-common-mpaudio 的 voice_encode_fileid 提取
同时提供正文有效性判定 has_article_content / unavailable_reason，供 fetch_bodies
的 valid_page（经 check_article.py）与交付说明复用。

已知限制：图集文/短内容的图片在页面里不是 <img data-src>（在 JS 里），make_img_manifest
扫不到 → embed 模式对这类图会退化为远程 URL（见 make_html.py 的缺图兜底），不丢图。
"""
import re
import html as htmllib
import time


# ---- 通用小工具 ----

def _jsdecode_unescape(s):
    """解 JsDecode 的 \\xNN 序列 + HTML 实体（微信常双重编码，unescape 两次）。"""
    s = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), s)
    s = htmllib.unescape(s)
    s = htmllib.unescape(s)
    return s


def html_to_text(html):
    """HTML -> 纯文本（按块级标签分段）。"""
    text = re.sub(r'<br\s*/?\s*>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'</(?:p|div|section|h[1-6]|tr|li|blockquote)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<hr[^>]*>', '\n---\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = htmllib.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def get_item_show_type(html):
    m = re.search(r"window\.item_show_type\s*=\s*'(\d+)'", html)
    return m.group(1) if m else None


def sanitize(t):
    """文件名规则（原 convert.py/make_html.py 各自一份，收敛到这里）：
    非法字符替换为 _，去首尾空白/点，超长截断，空回退。"""
    t = re.sub(r'[\\/:*?"<>|\r\n]+', '_', t)
    t = re.sub(r'^[.\s]+|[.\s]+$', '', t)
    return (t[:80] or 'untitled')


# ---- 元信息提取 ----

def extract_title(html):
    """标题：老式 activity-name h1 -> rich_media_title h1/h2 -> msg_title 变量 -> og:title 首行。"""
    title = ''
    m = (re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', html, re.S) or
         re.search(r'<h1[^>]*class="[^"]*rich_media_title[^"]*"[^>]*>([\s\S]*?)</h1>', html, re.I) or
         re.search(r'<h2[^>]*class="[^"]*rich_media_title[^"]*"[^>]*>([\s\S]*?)</h2>', html, re.I))
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        title = htmllib.unescape(title)
    if not title:
        m = (re.search(r"var\s+msg_title\s*=\s*'([^']+)'\.html\(false\)", html) or
             re.search(r"window\.msg_title\s*=\s*window\.title\s*=\s*'([^']*)'", html) or
             re.search(r"msg_title:\s*JsDecode\('([^']+)'\)", html))
        if m:
            title = _jsdecode_unescape(m.group(1)).strip()
    if not title:
        m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        if m:
            # og:title 可能把全文塞进来（分享页），只取第一行，否则标题会串
            title = htmllib.unescape(m.group(1)).replace('\\n', '\n').strip().split('\n')[0].strip()
    return title


def extract_pubtime(html):
    """发布时间：createTime 字符串 -> publish_time em -> create_time JS 配置 -> 时间戳。"""
    pubtime = ''
    m = re.search(r"var createTime = '([^']+)'", html)
    if m:
        pubtime = m.group(1).strip()
    if not pubtime:
        m = re.search(r'<em id="publish_time"[^>]*>(.*?)</em>', html, re.S)
        if m:
            pubtime = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    if not pubtime:
        m = re.search(r"create_time:\s*'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})'", html)
        if m:
            pubtime = m.group(1)
    if not pubtime:
        # 时间戳形式：var ct = "…" / var publish_time = "…"（秒）
        m = re.search(r"var\s+(?:ct|publish_time)\s*=\s*[\"'](\d{9,})[\"']", html)
        if m:
            pubtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(m.group(1))))
    return pubtime


def extract_nickname(html):
    """公众号昵称：js_name -> var nickname -> og:article:author。"""
    m = (re.search(r'<a[^>]*id="js_name"[^>]*>([\s\S]*?)</a>', html, re.I) or
         re.search(r"var\s+nickname\s*=\s*[\"']([^\"']+)[\"']", html) or
         re.search(r'<meta property="og:article:author" content="([^"]+)"', html))
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return ''


# ---- 正文容器提取 ----

def extract_div_inner(html, open_pattern):
    """按开闭深度计数取 <div> 内层，正确处理嵌套 div；找不到返回 ''。"""
    m = re.search(open_pattern, html, re.DOTALL | re.IGNORECASE)
    if not m:
        return ''
    start = m.end()
    depth = 1
    pos = start
    open_re = re.compile(r'<div[\s/>]', re.IGNORECASE)
    close_re = re.compile(r'</div\s*>', re.IGNORECASE)
    while depth > 0 and pos < len(html):
        no = open_re.search(html, pos)
        nc = close_re.search(html, pos)
        if nc is None:
            break
        if no and no.start() < nc.start():
            depth += 1
            pos = no.end()
        else:
            depth -= 1
            if depth == 0:
                return html[start:nc.start()].strip()
            pos = nc.end()
    return html[start:].strip()


# 标准正文容器（按特异性排序；不同号/不同模板用的容器不同）
_CONTENT_PATTERNS = [
    r'<div[^>]*\bid=["\']js_content["\'][^>]*>',
    r'<div[^>]*\bclass=["\'][^"\']*rich_media_content[^"\']*["\'][^>]*>',
    r'<div[^>]*\bid=["\']page-content["\'][^>]*>',
    r'<div[^>]*\bid=["\']page_content["\'][^>]*>',
    r'<div[^>]*\bid=["\']js_article["\'][^>]*>',
    r'<div[^>]*\bclass=["\'][^"\']*rich_media_area_primary_inner[^"\']*["\'][^>]*>',
    r'<div[^>]*\bclass=["\'][^"\']*rich_media_area_primary(?:\s|"|\')',
]


def extract_div_content(html):
    """标准容器正文（js_content 等），含尾部（rich_media_tool）裁剪与 script/style 剔除。"""
    content = ''
    for pat in _CONTENT_PATTERNS:
        content = extract_div_inner(html, pat)
        if content:
            break
    if content:
        idx = content.find('<div class="rich_media_tool')
        if idx > 0:
            content = content[:idx]
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.S)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.S)
    return content


# ---- 特殊文章类型 ----

def extract_image_text_content(html):
    """item_show_type=8 图集文：picture_page_info_list 画廊图片 + description 文字。"""
    images = []
    # 简单格式：picture_page_info_list = [ {...cdn_url: '...'}, ... ]
    sp = html.find('picture_page_info_list = [')
    if sp >= 0:
        bs = html.find('[', sp)
        depth = 0
        end = bs
        while end < min(bs + 30000, len(html)):
            if html[end] == '[':
                depth += 1
            elif html[end] == ']':
                depth -= 1
                if depth == 0:
                    break
            end += 1
        block = html[bs:end + 1]
        for item in re.split(r'\n\s{2,20}\{', block):
            m = re.search(r"cdn_url:\s*'([^']+)'", item)
            if m and m.group(1) not in images and ('mmbiz.qpic.cn' in m.group(1)
                                                   or 'mmbiz.qlogo.cn' in m.group(1)):
                images.append(m.group(1))
    # 降级：JsDecode 格式 picture_page_info_list: [ {cdn_url: JsDecode('...')} ]
    if not images:
        jm = re.search(r'picture_page_info_list:\s*\[', html)
        if jm:
            bs = jm.end() - 1
            depth = 0
            end = bs
            while end < min(bs + 30000, len(html)):
                if html[end] == '[':
                    depth += 1
                elif html[end] == ']':
                    depth -= 1
                    if depth == 0:
                        break
                end += 1
            block = html[bs:end + 1]
            for item in re.split(r'\n\s{2,20}\{(?=\s*\n\s*cdn_url)', block):
                m = re.search(r"cdn_url:\s*JsDecode\('([^']+)'\)", item)
                if m:
                    u = m.group(1).replace('\\x26amp;', '&').replace('\\x26', '&')
                    if u not in images and ('mmbiz.qpic.cn' in u or 'mmbiz.qlogo.cn' in u):
                        images.append(u)

    desc = ''
    dm = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
    if dm:
        desc = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m2: chr(int(m2.group(1), 16)), dm.group(1))
        desc = htmllib.unescape(htmllib.unescape(desc))
        desc = re.sub(r'<[^>]+>', '', desc)
        desc = desc.replace('\\x0a', '\n').replace('\\n', '\n')
    if not desc:
        dm2 = re.search(r"content_desc:\s*JsDecode\('([^']*)'\)", html)
        if dm2:
            desc = htmllib.unescape(dm2.group(1))

    parts = []
    for u in images:
        parts.append('<p><img data-src="%s" src="%s" alt="img" /></p>' % (u, u))
    for line in desc.split('\n'):
        line = line.strip()
        if line:
            parts.append('<p>%s</p>' % htmllib.escape(line))
    return ''.join(parts)


def extract_short_content(html):
    """item_show_type=10 短内容/转发文：content_noencode（JsDecode 旧式 / 裸单引号新式），
    兜底 og:title / og:description（部分号把正文塞在 meta）。"""
    text = ''
    for key in ('content_noencode', 'content'):
        m = re.search(rf"\b{key}\s*:\s*JsDecode\('([^']*)'\)", html)
        if not m or len(m.group(1)) <= 10:
            cands = re.findall(rf"\b{key}\s*:\s*'([^']*)'", html)
            if cands:
                longest = max(cands, key=len)
                if len(longest) > 10:
                    text = _jsdecode_unescape(longest)
                    break
            continue
        if len(m.group(1)) > 10:
            text = _jsdecode_unescape(m.group(1))
            break
    if not text:
        m = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']{30,})["\']', html)
        if m:
            text = htmllib.unescape(m.group(1)).replace('\\n', '\n').replace('\\x0a', '\n')
    if not text:
        m = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']{30,})["\']', html)
        if m:
            text = htmllib.unescape(m.group(1)).replace('\\n', '\n').replace('\\x0a', '\n')

    images = []
    m = re.search(r"round_head_img:\s*JsDecode\('([^']+)'\)", html)
    if m:
        u = _jsdecode_unescape(m.group(1))
        if 'mmbiz.qpic.cn' in u or 'wx.qlogo.cn' in u:
            images.append(u)
    if not images:
        m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
        if m and ('mmbiz' in m.group(1) or 'wx.qlogo.cn' in m.group(1)):
            images.append(m.group(1))

    parts = []
    for u in images:
        parts.append('<p><img data-src="%s" src="%s" alt="img" /></p>' % (u, u))
    for line in text.replace('\\x0a', '\n').replace('\\n', '\n').split('\n'):
        line = line.strip()
        if line:
            parts.append('<p>%s</p>' % htmllib.escape(line))
    return ''.join(parts)


def extract_audio_share_content(html):
    """item_show_type=7 音频/视频分享页：Vue 动态壳，正文 JS 加载，只取元信息 + 占位说明。"""
    title = extract_title(html)
    author = extract_nickname(html)
    images = []
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if m and m.group(1) and ('mmbiz' in m.group(1) or m.group(1).startswith('http')):
        images.append(m.group(1))
    parts = []
    if title:
        parts.append('<p><strong>%s</strong></p>' % htmllib.escape(title))
    if author:
        parts.append('<p>作者：%s</p>' % htmllib.escape(author))
    for u in images:
        parts.append('<p><img data-src="%s" src="%s" alt="cover" /></p>' % (u, u))
    parts.append('<p>🎵 此文章为音频/视频分享内容，正文由微信端 JS 动态加载，无法直接提取，请到微信中查看完整内容。</p>')
    return ''.join(parts)


def extract_audio_content(html):
    """音频文章：mpvoice / mp-common-mpaudio 的 voice_encode_fileid（可拼播放鉴权链接）+ 周边文字。"""
    audio_items = []
    seen = set()
    # 老式 <mpvoice .../> 与新版 <mp-common-mpaudio .../> 一并收集，按 fileid 去重
    for pat in (r'<mpvoice[^>]*voice_encode_fileid=["\']([^"\']+)["\'][^>]*/?>',
                r'<mp-common-mpaudio[^>]*voice_encode_fileid=["\']([^"\']+)["\'][^>]*/?>'):
        for m in re.finditer(pat, html, re.I):
            fid = m.group(1)
            if fid in seen:
                continue
            seen.add(fid)
            nm = re.search(r'name=["\']([^"\']*)["\']', m.group(0))
            pl = re.search(r'play_length=["\'](\d+)["\']', m.group(0))
            audio_items.append({
                'name': htmllib.unescape(nm.group(1)) if nm else '',
                'url': 'https://res.wx.qq.com/voice/getvoice?mediaid=%s' % fid,
                'duration': int(pl.group(1)) if pl else 0,
            })
    if not audio_items:
        return ''

    # 周边文字：js_content 里去掉音频标签后取纯文本
    text = ''
    inner = extract_div_inner(html, r'<div[^>]*\bid=["\']js_content["\'][^>]*>')
    if inner:
        inner = re.sub(r'<mpvoice[^>]*/?>', '', inner)
        inner = re.sub(r'<mp-common-mpaudio[^>]*/>', '', inner)
        inner = re.sub(r'<mp-common-mpaudio[^>]*>.*?</mp-common-mpaudio>', '', inner, flags=re.S)
        text = html_to_text(inner)

    parts = []
    for line in text.split('\n'):
        line = line.strip()
        if line:
            parts.append('<p>%s</p>' % htmllib.escape(line))
    for i, a in enumerate(audio_items):
        dur_s = ''
        if a['duration']:
            dur_s = '（%d:%02d）' % (a['duration'] // 60, a['duration'] % 60)
        nm = a['name'] or ('音频 %d' % (i + 1))
        parts.append('<p>[音频] %s%s — 此音频需在微信内播放，无法离线保存</p>' % (htmllib.escape(nm), dur_s))
    return ''.join(parts)


# ---- 有效性判定 / 不可用原因 ----

_VERIFY_MARKERS = ('环境异常', '完成验证后即可继续访问', '去验证')


def is_verification_page(html):
    """微信验证页（IP 风控/代理断连时的重定向页）：三个特征齐全才算，避免误伤正常文章。"""
    return all(k in html for k in _VERIFY_MARKERS)


# 真实正文容器标记：匹配 HTML 元素而不是 JS 字符串里的字样（验证页 1.9MB 壳里有 js_content 字样）
_CONTENT_MARKERS = [
    'id="js_content"',
    'class="rich_media_content',
    'class="rich_media_area_primary',
    'id="page-content"',
    'id="page_content"',
    'id="js_article"',
]

_UNAVAILABLE_MARKERS = [
    ('该内容已被发布者删除', '已被发布者删除'),
    ('内容已删除', '已被发布者删除'),
    ('此内容因违规无法查看', '因违规无法查看'),
    ('涉嫌违反相关法律法规和政策', '涉嫌违规被限制'),
    ('此内容发送失败无法查看', '发送失败无法查看'),
    ('根据作者隐私设置，无法查看该内容', '作者隐私设置不可见'),
    ('接相关投诉，此内容违反', '因投诉违规被限制'),
    ('该文章已被第三方辟谣', '已被第三方辟谣'),
]


def unavailable_reason(html):
    """返回不可用原因；正文正常返回 None。验证页不算不可用（那是风控，应重试）。"""
    if is_verification_page(html):
        return None
    for kw, reason in _UNAVAILABLE_MARKERS:
        if kw in html:
            # 大 HTML 里关键字可能只是正文 JS 里的字符串，需确认出现在前 50KB 可见区
            if len(html) > 1000000 and ('id="js_content"' in html or 'class="rich_media_content' in html):
                body = re.search(r'<body[^>]*>(.*?)(?:<script|$)', html[:50000], re.DOTALL | re.I)
                if body and kw not in body.group(1):
                    continue
            return reason
    # 「该内容暂时无法查看」独立页（<2KB + <title> 含此文案）
    if '该内容暂时无法查看' in html and len(html) < 2000:
        mt = re.search(r'<title>(.*?)</title>', html, re.I)
        if mt and '该内容暂时无法查看' in mt.group(1):
            return '该内容暂时无法查看'
    # 空 Vue 应用（作者隐私设置的动态错误页）
    if '<div id="app">' in html and len(html) < 200000:
        has_c = any(m in html for m in _CONTENT_MARKERS)
        mt = re.search(r'<title>(.*?)</title>', html, re.I)
        if not has_c and mt and not mt.group(1).strip():
            return '根据作者隐私设置不可查看'
    return None


def has_article_content(html):
    """能否从该 HTML 中拿到正文（供 fetch_bodies 的 valid_page 复用）。
    - 验证页/壳页        → False（应重试）
    - 平台已删/违规等终态 → True（拿去重试没意义）
    - 真实容器 / 特殊类型 / 分享页 og:title → True
    """
    if is_verification_page(html):
        return False
    if unavailable_reason(html):
        return True
    if any(m in html for m in _CONTENT_MARKERS):
        return True
    t = get_item_show_type(html)
    if t in ('7', '8', '10'):
        return True
    if '<mpvoice' in html or '<mp-common-mpaudio' in html:
        return True
    if re.search(r'<meta\s+property="og:title"\s+content="[^"]+"', html):
        return True
    return False


# ---- 主入口 ----

def extract_article(html):
    """解析一篇正文 HTML。

    返回 dict：title / pubtime / nickname / item_type / content / reason
    content 为空串 = 无正文（验证页/壳页/平台已删/纯 JS 渲染），reason 说明原因。
    """
    if is_verification_page(html):
        return {'title': '', 'pubtime': '', 'nickname': '', 'item_type': None,
                'content': '', 'reason': '微信验证页(风控/代理断连)，非文章'}
    item_type = get_item_show_type(html)
    title = extract_title(html)
    pubtime = extract_pubtime(html)
    nickname = extract_nickname(html)

    content = ''
    if item_type == '7':
        content = extract_audio_share_content(html)
    elif item_type == '8':
        content = extract_image_text_content(html)
    elif item_type == '10':
        content = extract_short_content(html)
    elif '<mpvoice' in html or '<mp-common-mpaudio' in html:
        content = extract_audio_content(html)
    if not content:
        content = extract_div_content(html)
    if not content:
        # 新版「分享页」模板：无 js_content，全文在 og:title（段落分隔常是字面 "\n"）
        m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        if m:
            txt = htmllib.unescape(m.group(1)).replace('\\n', '\n')
            lines = [ln.strip() for ln in txt.split('\n')]
            while lines and not lines[0]:
                lines.pop(0)
            paras = [p for p in lines[1:] if p]
            if paras or lines:
                content = ''.join('<p>%s</p>' % htmllib.escape(p) for p in paras)
                if not title and lines:
                    title = lines[0]

    reason = None
    if not content:
        reason = unavailable_reason(html) or '无正文(平台已删或纯JS渲染)'
    return {'title': title, 'pubtime': pubtime, 'nickname': nickname,
            'item_type': item_type, 'content': content, 'reason': reason}


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        html = open(sys.argv[1], encoding='utf-8', errors='replace').read()
        import json as _json
        info = extract_article(html)
        print(_json.dumps({k: (v[:80] + '…' if isinstance(v, str) and len(v) > 80 else v)
                           for k, v in info.items()}, ensure_ascii=False, indent=1))