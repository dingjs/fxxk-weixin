#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正文有效性 + 不可用原因判定（供 fetch_bodies.sh 的 valid_page 复用）。

用法：python3 check_article.py <html文件>
输出：
  OK            有正文（含平台已删等终态页，重试没意义）
  BAD:原因       无正文，原因见冒号后（如「微信验证页(风控/代理断连)，非文章」）
  BAD           无正文且无已知原因
"""
import sys
import wechat_extract as w


def main():
    if len(sys.argv) < 2:
        sys.exit(2)
    html = open(sys.argv[1], encoding='utf-8', errors='replace').read()
    if w.has_article_content(html):
        print('OK')
        return
    if w.is_verification_page(html):
        print('BAD:微信验证页(风控/代理断连)，非文章')
        return
    r = w.unavailable_reason(html)
    print('BAD' + ((':' + r) if r else ''))


if __name__ == '__main__':
    main()