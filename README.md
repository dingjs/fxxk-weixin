# fuck-weixin

抓取微信公众号**全部文章**的 Claude Code Skill。默认输出 Markdown（文件名 = 文章标题），可选 HTML；图片可按需内嵌、保留远程链接或直接去掉。

[English](README.en.md) | **中文**

> 仓库名是 `fxxk-weixin`，技能名（`SKILL.md` 的 `name`）是 `fuck-weixin`。

## 工作原理

微信对非客户端访问（curl / 浏览器无会话）会返回验证页，浏览器打开公众号资料页也会被「请在微信客户端打开链接」拦截。因此本项目采用：

1. **mitmproxy local 模式**只劫持微信文章页进程（`WeChatAppEx` 网络服务）发往 `mp.weixin.qq.com` 的新连接，**不设置系统代理**，其它应用不受影响。
2. 从请求中提取会话签名：`key`、`pass_ticket`、`uin`、`appmsg_token`、`__biz`。
3. 在**微信所在的同一台机器**上直连调用 `mp/profile_ext?action=getmsg` 翻页拉取文章列表，再逐篇抓取正文。
4. 解析正文并输出 Markdown / HTML。

风控看的是公网出口 IP，所以抓取必须与微信客户端同机、同出口。`key` 每 2~4 分钟轮换一次，脚本会在每页/每篇前实时刷新参数。

## 环境要求

- Python 3
- mitmproxy **10.2+**（local 模式自 10.2 起可用）
- bash 3.2+、curl
  - Windows **首选** Git for Windows 自带的 Git Bash
  - 没有 sh 环境（无 Git Bash / WSL）时，让 Claude Code agent 按 `SKILL.md` 的「Windows 无 sh 环境」小节把 `scripts/*.sh` 就地移植为 `.ps1` / `.bat`，无需另外安装
- 一台登录了 PC 微信、且能正常查看目标公众号的机器

## 安装

```bash
git clone https://github.com/dingjs/fxxk-weixin.git ~/.claude/skills/fuck-weixin
```

确保 `SKILL.md` 位于技能目录根部（本仓库根目录即技能目录）：`~/.claude/skills/fuck-weixin/SKILL.md`、`~/.claude/skills/fuck-weixin/scripts/`。

## 快速开始

> 首次使用需要一次性安装 mitmproxy CA 证书。macOS 必须装入**系统钥匙串**，`login.keychain-db` 对沙箱化的 WeChatAppEx 无效（需要 `sudo`，请在自己的终端执行）。

1. **启动劫持**（不改系统代理，不必退出微信）：

   ```bash
   export PYTHONUTF8=1 && export PYTHONIOENCODING=utf-8
   bash scripts/start_proxy.sh
   ```

2. **安装证书**（一次性）：把 `~/.mitmproxy/mitmproxy-ca-cert.pem` 装入系统信任库。
   - macOS：
     ```bash
     sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem
     ```
   - Windows：双击 `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem`，装入「受信任的根证书颁发机构」。
   - Linux：复制到 `/usr/local/share/ca-certificates/` 后执行 `update-ca-certificates`。

3. **在 PC 微信里操作**（唯一一次人工配合）：
   1. 搜索目标公众号并点进聊天窗口；
   2. 点右上角公众号名称进入主页，下滑几次；
   3. **点开任意一篇文章**；
   4. **保持文章页开着**（key 轮换依赖文章页持续的 jsmonitor 请求）。

4. **确认拿到 key**：

   ```bash
   bash scripts/start_proxy.sh --wait-key 25
   ```

   成功标志：`wechat_flows.jsonl` 新增行中同时出现 `mp.weixin.qq.com` 和 `key=daf9bd`。

5. **后台提取会话参数**：

   ```bash
   python3 refresh_loop.py &
   ```

   脚本每 3 秒刷新一次 `params.txt`，写入 `key` / `pass_ticket` / `uin` / `appmsg_token` / Cookie / `__biz`。

## 抓取流程

把 `scripts/` 复制到以公众号命名的工作区后再运行，交付物会写到工作区根：

```text
公众号名/
├── scripts/            # 脚本副本 + 中间产物
│                       #   wechat_flows.jsonl / params.txt / getmsg_pages/ / html/{mid}_{idx}.html / img/
├── articles_md/        # 交付物：Markdown（默认，按标题命名）
└── articles_html/      # 交付物：HTML（可选，按标题命名）
```

```bash
# 1. 翻页拉取全部文章列表 -> getmsg_pages/p{offset}.json
bash scripts/fetch_list.sh

# 2. 解析列表 -> articles_list.json
python3 scripts/parse_articles.py

# 3. 逐篇抓取正文 -> scripts/html/{mid}_{idx}.html
bash scripts/fetch_bodies.sh

# 4a. 默认输出 Markdown -> articles_md/{文章标题}.md
python3 scripts/convert.py

# 4b. 可选输出 HTML -> articles_html/{文章标题}.html
python3 scripts/make_html.py
```

只想抓最新 N 篇时，用 `MAX_OFFSET=<offset>` 限制最大 offset（如 `MAX_OFFSET=100` 表示最新 10 页，每页 10 个群发 bundle）。offset 数的是 **bundle**，解析后会展开成更多子文章。

## 输出格式与图片策略

Markdown 是默认格式，纯文字模式：

```bash
env STRIP_IMAGES=1 python3 scripts/convert.py
```

HTML 的图片模式由 `img_mode` 控制：

| 模式 | 效果 | 是否需要先下载图片 |
| --- | --- | --- |
| `embed`（默认） | 图片 base64 内嵌，单文件自包含、可离线 | 是 |
| `remote` | 图片保留远程 URL，文件小、看图需联网 | 否 |
| `strip` | 删除全部图片，纯文字存档 | 否 |

`embed` 模式先执行：

```bash
python3 scripts/make_img_manifest.py
bash scripts/download_imgs.sh
python3 scripts/make_html.py img_mode=embed
```

## 脚本一览

| 文件 | 作用 |
| --- | --- |
| `scripts/start_proxy.sh` | 启动 / 停止 local 劫持；`--wait-key` 等待有效 key |
| `scripts/saver.py` | mitmproxy 插件，只记录带 key / `__biz` / `appmsg_token` 的 `mp.weixin.qq.com` 流量 |
| `scripts/refresh_loop.py` | 从 JSONL 尾部提取最新会话参数写入 `params.txt` |
| `scripts/fetch_list.sh` | 调用 `getmsg` 翻页拉取文章列表 |
| `scripts/parse_articles.py` | 解析列表，按 `(mid, idx)` 去重，输出 `articles_list.json` |
| `scripts/fetch_bodies.sh` | 逐篇抓取正文 HTML |
| `scripts/check_article.py` | 正文有效性判定 |
| `scripts/wechat_extract.py` | 标题 / 时间 / 正文提取共享模块 |
| `scripts/make_img_manifest.py` | 生成图片清单（仅 `embed` 模式需要） |
| `scripts/download_imgs.sh` | 下载正文图片（仅 `embed` 模式需要） |
| `scripts/convert.py` | 转换 Markdown 交付物 |
| `scripts/make_html.py` | 转换 HTML 交付物 |
| `scripts/common.sh` | 共享函数：参数加载、代理 curl、文件大小 |

## 注意事项

- **不要设置系统代理**。local 模式只接管文章页进程发往 `mp.weixin.qq.com` 的连接。如果文章页流量先进入了 Clash 之类的本机代理，抓包会拿不到 key。
- **不要退出微信**。local 模式劫持的是启动之后的新连接；关闭文章页会断掉 key 的来源。
- **必须与微信同出口 IP**。用 Python 沙箱或另一台机器代发 `getmsg` 会返回空列表。只有 curl 不在微信那台机器上时，才用 `WX_MITM_MODE=regular` 开一个给 curl 用的端口，并设置 `MITM_PROXY`，且不要设成系统代理。
- **`getmsg` 必须带 `appmsg_token` URL 参数**，只放在 Cookie 里会返回 `msg_count:0`。Mac 客户端本身就把它放在 URL 参数且不带 Cookie，脚本已双路兼容。
- **续页判据用 `next_offset` 前进**，不要只信 `can_msg_continue`（部分账号该字段恒为 0）。
- **文章去重键是 `(mid, idx)`**。一次群发是一个 `mid`，最多含 8 个子文章；只按 `mid` 去重会丢失附加文。
- **正文有效性按内容标记校验**，不能只看文件大小；平台已删除的文章任何会话都拿不到。
- **macOS 证书必须装系统钥匙串**，否则微信文章页会一直转圈，日志报 `Client TLS handshake failed`。
- 抓取结束后执行 `bash scripts/start_proxy.sh --stop`。

## 合规提醒

本项目仅用于抓取**你有权访问的内容**（你的微信账号能正常查看的公众号文章）。请遵守微信平台条款与相关法律法规，不要用于批量侵权、绕过访问控制或其它不当用途。

## 许可

本项目采用 [Apache License 2.0](LICENSE) 开源许可，Copyright 2026 dingjs。
