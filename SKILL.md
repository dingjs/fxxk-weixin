---
name: fuck-weixin
description: 抓取微信公众号全部文章。原理：mitmproxy local 模式只劫持微信文章页进程（WeChatAppEx 网络服务）的新连接，不设置系统代理，其它应用不受影响；start_proxy.sh 重置文章页已有的外网 443，不必退出微信。从文章请求提取 key/pass_ticket/appmsg_token/__biz，再在本机直连调 mp/profile_ext?action=getmsg 翻页并抓正文（与微信同一公网出口；curl 不在这台机器时才设 MITM_PROXY）。默认输出 Markdown（文件名=文章标题，纯文字或带图由用户定），可选 HTML；图片策略 embed/remote/strip 由用户决定。交付物（articles_md/、articles_html/）放工作区根，脚本与中间产物在 scripts/。需要用户在 PC 微信里点开一篇文章并保持开着供 key 刷新。全部平台同一套 scripts/*.sh + start_proxy.sh（Windows **首选** Git Bash；无 sh 时按 SKILL.md 移植为 .ps1/.bat；macOS 证书须装系统钥匙串，见坑 13。不要设系统代理，不要为抓包退出微信）。
---

# fuck-weixin —— 拉取微信公众号全部文章

抓取目标公众号的**全部文章**，默认输出 **Markdown**（文件名 = 文章标题；无法用标题时回退 mid），可选输出 **HTML**；均按标题命名。图片策略由用户决定（保留 → embed 内嵌 / remote 远程链接；不保留 → strip 纯文字）。交付物 `articles_md/`、`articles_html/` 放在**工作区根**（`<公众号名>/articles_md`），脚本与全部中间产物留在 `scripts/` 下。

**本技能目录**：`fuck-weixin-skill`（随个人 skills 安装后整体复制到工作区）
**完整脚本**：`scripts/` 子目录（saver.py / refresh_loop.py / parse_articles.py / fetch_list.sh / fetch_bodies.sh / download_imgs.sh / make_img_manifest.py / make_html.py / convert.py / wechat_extract.py / check_article.py / common.sh / README.md）。全部平台同一套 `.sh`（Windows **首选** Git for Windows 的 Git Bash 运行；**无 sh 时由 agent 按「Windows 无 sh 环境」就地移植为 `.ps1`/`.bat`**；Python 解析器由 common.sh 自动探测）。执行前把 `scripts/` 整个复制到工作区（或按 README 用绝对路径调用）；所有脚本默认以工作区为当前目录。

## 原理（为什么必须这么干）

- 微信对**非客户端访问**（curl/浏览器无会话）返回反爬验证页 `wappoc_appmsgcaptcha`，拿不到正文；浏览器打开公众号资料页（mp/profile_ext）会被「请在微信客户端打开链接」拦截。
- 正确路径：mitmproxy **local 模式**只解密微信文章页进程发往 `mp.weixin.qq.com` 的新连接 → 从请求中拿到**会话签名**（URL 参数 key/pass_ticket/uin + appmsg_token）→ 用这些签名在**微信所在机器上直连**调列表接口拿全部文章 → 逐篇抓正文 HTML。不设置系统代理。风控看的是公网出口 IP：curl 和微信必须在同一台机器；python 沙箱/另一台机器出口不同会返回空列表。
- 会话参数位置注意：**Windows 客户端**把 `appmsg_token` 放 Cookie，**Mac 客户端**放 URL 参数且请求不带 Cookie（`refresh_loop.py` 已两路兼容）。
- 列表接口 `mp/profile_ext?action=getmsg` 一次 10 篇，offset 翻页直到 `can_msg_continue=0`。
- **数据模型（必须记住）**：一个「群发」= 一个 `mid`，内含最多 8 个子文章，靠 `content_url` 里的 `idx=1..8` 区分（主文 idx=1 + 附加文 idx=2..8）。**去重键必须是 `(mid, idx)`**——只按 `mid` 去重会把同一群发的附加文全部吞掉、只剩最后一条（实测多为尾条小视频，正文唯一的主文丢失）。正文文件名一律 `html/{mid}_{idx}.html`（详见坑 21）。
- `__biz`（公众号唯一标识）由 `refresh_loop.py` 从用户打开的正文请求 URL 自动提取写入 `params.txt`，脚本不再写死。

## 前置环境（一次性，agent 自动完成）

Windows（**首选** Git for Windows 自带的 Git Bash，跑与 mac/Linux 相同的 `.sh`）：

0. 装 Git for Windows 与 Python 3；Git Bash 里如果命令不是 `python3`，common.sh 会自动探测 `python3`/`python`/`py`，也可 `export PY=python` 指定。
   **没有 sh 环境时（不要停在"先装 Git Bash"）**：若 `bash` 不在 PATH（PowerShell `Get-Command bash` 或 cmd `where bash` 都失败，且未装 WSL），**不要要求用户先装 Git for Windows**——按下节「## Windows 无 sh 环境：agent 就地移植为 .ps1/.bat」，由 agent 把 `scripts/*.sh` 逐个移植成 `.ps1`（配 `.bat` 启动器）再跑，行为一致。**本段后续所有 `bash scripts/x.sh` 在无 sh 时一律替换为移植出的 `x.ps1`（或双击同名 `x.bat`）。**
1. mitmproxy 10.2 及以上：`winget install mitmproxy`（或装到 PATH）。local 模式从 10.2 起可用。
2. 启动劫持（**不改系统代理，不必退出微信**）：
   `export PYTHONUTF8=1 && export PYTHONIOENCODING=utf-8` 后
   `bash scripts/start_proxy.sh`。默认 `--mode local`，只劫持 WeChatAppEx 的网络服务（命令行含 `network.mojom.NetworkService` 的 PID；微信还没开时用进程名 `WeChatAppEx` / `WeChatAppEx Helper` / `WeChatAppEx.exe`，不含主进程 WeChat/Weixin）。`proxy.cfg` 写 `MODE=local`、`PROCS=...`、`MITM_PROXY=direct`。
3. mitmproxy CA 装入「受信任的根证书颁发机构」（一次性）：双击 `C:\Users\<你>\.mitmproxy\mitmproxy-ca-cert.pem`（Windows 微信不沙箱，用户级根证书即可）。
4. 用户保持或点开一篇文章后：`bash scripts/start_proxy.sh --wait-key 25`。成功只认 `wechat_flows.jsonl` **新增**行里同时有 `mp.weixin.qq.com` 和 `key=daf9bd`。脚本自己的 curl 不算。Windows 没有 `pfctl`：关掉文章页再点开一篇即可，不必退出客户端。

Linux / macOS：

1. mitmproxy 10.2 及以上：macOS `brew install --cask mitmproxy`；Linux 官方脚本或 `pip install mitmproxy` / 发行版包。
2. `bash scripts/start_proxy.sh`。local 模式，**不调用 networksetup，不改系统代理**。首次若系统弹出网络扩展授权，允许 mitmproxy。抓完 `bash scripts/start_proxy.sh --stop`。
3. 把 `~/.mitmproxy/mitmproxy-ca-cert.pem` 装入系统信任库（一次性。Linux：`/usr/local/share/ca-certificates/` + `update-ca-certificates`）。
   macOS：`security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db` **不够**——沙箱化的 WeChatAppEx（Chromium）只认**系统钥匙串**，必须：
   `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem`
   且 `sudo` 需要用户在**自己的终端 App** 里执行（agent 的 `!` 前缀无 TTY，读不了密码）。
4. 脚本会重置文章页进程上已建立的外网 443（macOS `pfctl -k`，需要 sudo）。没有免密 sudo 时，按它打印的命令让用户在自己的终端执行。然后 `bash scripts/start_proxy.sh --wait-key 25`。成功只认 jsonl **新增**行里同时有 `mp.weixin.qq.com` 和 `key=daf9bd`。

.sh 脚本运行方式：`bash fetch_list.sh`（依赖 bash 3.2+；macOS 自带 bash 3.2 兼容，Linux 自带，Windows 用 Git for Windows 的 Git Bash）。**无 sh 环境时见下节，由 agent 就地移植为 .ps1/.bat。**

## Windows 无 sh 环境：agent 就地移植为 .ps1/.bat

**触发条件**：Windows 且**没有 sh**——`Get-Command bash`（PowerShell）/ `where bash`（cmd）失败，也未装 WSL/MSYS2。此时**不要**让用户去装 Git for Windows，而是由 agent 把 `scripts/*.sh` **就地移植**成同目录下的 `.ps1`（每个脚本再配一个同名 `.bat` 启动器）后运行。`.sh` **保留不删**，作为行为基准。

### 移植原则（必须遵守）

- **`.sh` 是唯一行为基准**：1:1 移植，不新增/删减逻辑。环境变量（`WORKSPACE_DIR`/`MITM_PROXY`/`PARAMS_FILE`/`PY`/`MAX_OFFSET`/`ARTS_FILE`/`WX_*`）语义一致；`proxy.cfg`/`params.txt` 读写格式一致（`KEY=VALUE` 逐行、值内含 `=` 只切第一个 `=`）。local 模式的 `proxy.cfg` 是 `MODE=local`、`PROCS=...`、`MITM_PROXY=direct`（没有 `PORT`）。`MITM_PROXY=direct` 表示 curl 不带 `-x`。
- **输出关键字必须一致**（续跑/下游判据靠它）：`LIST_DONE`/`BODIES_DONE`/`IMG_DONE`/`NO_PARAM`/`NO_BIZ`/`STOP`/`RET`/`EMPTY`/`KEY_DEAD`/`END_OF_HISTORY`/`FAIL`/`GIVEUP_PARAM`/`DEGRADED`/`progress N/M`。
- **硬规则不得改动**：正文去重键 `(mid, idx)` 与文件名 `html/{mid}_{idx}.html`；续页判据用 `next_offset` 前进（缺失才回退 `can_msg_continue`）；每 offset 最多 5 次重试；每页/每篇前**实时**读 `params.txt` 刷 key；`embed` 模式必须先下载图片。
- **Python 脚本（`*.py`）不移植**：Windows 上直接用 `py`（优先）或 `python` 调，行为与 mac/Linux 一致。

### 需移植的文件

`common.sh → common.ps1`（被 dot-source）、`start_proxy.sh`、`fetch_list.sh`、`fetch_bodies.sh`、`download_imgs.sh`。移植后目录里 `.sh` 与 `.ps1` 并存。

### sh → PowerShell 关键映射（都是踩过的坑）

| sh 写法 | PowerShell 写法 | 说明 |
|---|---|---|
| `curl ...` | **`curl.exe ...`** | PS 5.1 里 `curl` 是 `Invoke-WebRequest` 的别名，参数完全不同；必须写 `curl.exe` |
| `-H "Cookie: $h"` | 参数**数组** `& curl.exe @a` | 原生参数含空格/分号（Cookie 一大串）时 PS 5.1 会重新拆引号。数组传参最稳；PS 7.3+ 另设 `$PSNativeCommandArgumentPassing='Standard'`。PS 5.1 退化方案：`Start-Process -Wait -NoNewWindow -RedirectStandardOutput`。**切勿直接拼 `-H "Cookie: $var"`** |
| `<<'PY' … PY` heredoc | 写成临时 `.py` 文件再 `& $PY file.py` | PS 5.1 的 stdin 重定向有编码坑，别把多行 Python 塞进管道 |
| `command -v x` | `Get-Command x -ErrorAction SilentlyContinue` | 探测 `python3`/`python`/`py` 同理；Windows 上优先 `py` |
| `nohup … &` | `Start-Process -NoNewWindow -PassThru` | 后台常驻（`refresh_loop.py`、`mitmdump`）；把 `$p.Id` 写进 pid 文件 |
| `kill $(cat pid)` | `Stop-Process -Id (Get-Content pid)` | `start_proxy --stop` 用 |
| `stat -f%z/-c%s "$f"` | `(Get-Item "$f").Length` | 文件大小 |
| `$(dirname "$0")` | `$PSScriptRoot` | 脚本所在目录 |
| `. "$HERE/common.sh"` | `. "$PSScriptRoot/common.ps1"` | dot-source |
| `[ -f f ] && [ -s f ]` | `Test-Path f` + 长度判断 | 判存在/非空 |
| `sed -n 's/^MITM_PROXY=//p'` | `Select-String` / `-split` | 读 `proxy.cfg`；`direct` 表示不走代理 |
| UTF-8 输出 | `[Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Text.Encoding]::UTF8; $env:PYTHONUTF8='1'` | `params.txt`/JSON 一律按 UTF-8 读写，否则中文乱码 |

`.bat` 启动器模板（每个 `.ps1` 配一个同名 `.bat`，绕执行策略且可双击）：

```bat
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fetch_list.ps1" %*
```

### 移植后必须验证（等价性自检）

1. **先自检再真抓**：用同一份 `params.txt`，`.ps1` 与 `.sh` 跑出**相同的输出关键字与产物文件**（如 `fetch_list` 的 `getmsg_pages/p*.json` 数量、`STOP`/`KEY_DEAD` 判定一致）。
2. 再做一次真实 getmsg（offset=0，预期 `ret:0` 且 `msg_count:10`）。
3. 任一步不一致 → 回 `.sh` 对照修正；**不能"跑起来就算数"**。

## 引导用户操作（一次性，话术要点）

目标：让微信文章页产生 **mp.weixin.qq.com** 且带 `key=` 的请求（这是拿会话参数的唯一途径）。列表接口不必从客户端抓。agent 先跑 `start_proxy.sh`（已含重置旧连接），再让用户点开文章。

给用户的指引（说明是唯一一次配合）：
0. **（agent 先确认交付选项再动工）** 输出格式默认 **Markdown**，可选 HTML；图片策略：保留（embed 内嵌 / remote 远程链接）或纯文字（strip 删图）。默认 md + 按用户对体积/离线的偏好定图片策略。
1. 在 PC 微信搜索目标公众号并点进公众号聊天窗口；
2. 点右上角公众号名称进入主页（历史文章列表），下滑几次；
3. **点开任意一篇文章**（关键！产生 `mp.weixin.qq.com/s?...` 请求）；
4. **保持文章页开着**（后续 key 轮换靠文章页持续产生的 jsmonitor 请求喂新 key）——回复「好了」。

用户确认后：`bash scripts/start_proxy.sh --wait-key 25`（看的是 jsonl **新增**字节，旧 key 不算）。要有 `key=`（`daf9bd` 开头）、`pass_ticket=`、`uin=`、`appmsg_token=`（Mac 在 URL；Windows 在 Cookie）与 `__biz=`。没有就让用户在**已开着的文章页**里点一下或下拉，不必退出微信。

> **不要退出微信，也不要设系统代理**。local 模式只接启动之后的新连接。文章页若已经连着 `mp.weixin.qq.com`，`start_proxy.sh` 会重置那条外网 443（macOS 需 sudo；没有免密 sudo 时按脚本打印的 `pfctl -k` 执行）。重置后 jsmonitor 会带 key 重连。

## 执行流程

**工作区目录结构**（把 `scripts/` 复制到 `<公众号名>/scripts/` 下运行，交付物自动写到上级目录）：

```
公众号名/
├── scripts/            # 脚本副本 + 全部中间产物
│                       #   (wechat_flows.jsonl / params.txt / getmsg_pages/ / html/{mid}.html / img/)
├── articles_md/        # 交付物：Markdown（标题命名，默认格式）
└── articles_html/      # 交付物：HTML（标题命名，用户选 HTML 时生成）
```

转换器（convert.py / make_html.py）默认把交付物写到脚本所在目录的上一级（工作区根）；换根用 `DELIVERY_ROOT=/path` 环境变量。

### 1. 提取会话参数（后台常驻）

先启动 `refresh_loop.py`（后台常驻，每 3 秒刷一次，写 `params.txt`）：抽取 `key`（URL 参数，`daf9bd` 开头）、`pass_ticket`、`uin`、`appmsg_token`（URL 参数和 Cookie 双路兼容）、`req_headers.Cookie` 完整值，以及 **`__biz`**。**关键**：`key` 每 2~4 分钟轮换一次 → 所有循环抓取前都必须读最新 `params.txt`（.sh 内部会实时加载，无需手工刷）。**这个进程必须与后续 .sh 的 `WORKSPACE_DIR` 一致**（即让它写在同一个 `params.txt`，别两处各写一份）。尾部窗口 8MB，只在提取到有效 key 时才写 `params.txt`；找不到时**保留上次有效参数（last-good）**，不会清空文件。

### 2. 验证 getmsg（一个请求确认可拉列表）

```
GET https://mp.weixin.qq.com/mp/profile_ext?action=getmsg&__biz=<BIZ>&f=json&count=10&is_ok=1&scene=126&uin=<UIN>&key=<KEY>&pass_ticket=<PT>&wxtoken=&appmsg_token=<TOK>&x5=0&offset=0
```
头：`Cookie: <完整 Cookie>`（见 `params.txt`）、微信 UA（见附录）。**在微信那台机器上直连**（`curl_via_proxy` 看到 `MITM_PROXY=direct` 时不带 `-x`）。不要用 python 沙箱或另一台机器代发——出口 IP 不同会被风控返回空列表。只有 curl 不在这台机器上时，才 `WX_MITM_MODE=regular bash scripts/start_proxy.sh` 开一个给 curl 用的端口，并 `export MITM_PROXY=http://<微信这台机器>:<端口>`。这个端口不要写成系统代理。

成功标志：`{"ret":0,"errmsg":"ok","msg_count":10,"can_msg_continue":1,"general_msg_list":"{...}"}`。
- 若 `msg_count:0` 但 ret:0 → 缺 `appmsg_token` URL 参数 / key 过期 / 走错代理。**appmsg_token 必须同时放 URL 参数**（只在 Cookie 里会返回空）。
- 若 ret 非 0 → key/pass_ticket 过期，重新提取或让用户再开一篇文章。

### 3. 翻页拉全部列表

跑 `fetch_list.sh`（每页实时读 params.txt 刷新参数，offset=0,10,20... 直到 `next_offset` 不再前进），页存 `getmsg_pages/p{offset}.json`。
页返回 `msg_count:0` → key 恰好轮换，脚本会自动 sleep 后**重试同 offset**（最多 5 次），不再丢页。已有非空页会自动跳过（可中断续跑）。
> 续页判据用 `next_offset` 前进（**不要只信 `can_msg_continue`**）：部分会话/账号该字段恒为 0 但分页仍有效，实测用它做停止条件会只抓一页就停。`next_offset` 缺失时脚本自动回退 `can_msg_continue`。
> **只抓最新 N 篇**：`MAX_OFFSET=<offset>` 限制最大 offset（如 `MAX_OFFSET=100` = 最新 10 页 = 100 个群发 bundle）。注意 offset 数的是 **bundle** 而非子文章数——解析（步骤 4）展开成 (mid, idx) 后文件数会多于 bundle 数。「最新 N 篇子文章」可在步骤 4 后自行按 ts 降序取前 N 条。

### 4. 解析列表 → 文章清单

跑 `python3 parse_articles.py`（读 `getmsg_pages/*.json`）→ `articles_list.json`。自动处理：ret!=0 的页跳过、主文 + `multi_app_msg_item_list` 附加文全收、content_url `html.unescape`、按 mid 去重、按时间升序。字段：date/title/mid/url。

### 5. 逐篇抓正文

跑 `fetch_bodies.sh`（读 articles_list.json + params.txt，逐篇 curl → `html/{mid}.html`）。
- **正文有效性按内容标记校验**（老式 `js_content` / 新版 `og:title`），不只按文件大小：`<100KB` 验证页与大但无正文的壳页都自动重试一次；重试后仍无效打 `DEGRADED` 日志（多为平台已删）。
- key 轮换期拿不到参数时对**同一 mid 重试最多 5 次**（不永久跳过；5 次仍失败才 `GIVEUP_PARAM` 放弃）。
- 目录已有**有效**文件跳过 → 可断点续跑。成功正文 HTML 通常 1.5~3.5MB。

### 6. 图片处理（是否保存图片由用户决定）

`python3 make_html.py` 支持三档图片模式（加参数 `img_mode=...`，默认 `embed`）：

| 模式 | 效果 | 要不要先下载图片 |
|---|---|---|
| `embed`（默认） | 图片 base64 内嵌 → **单文件自包含、永久离线**（文件大，几百篇约几个 GB） | 必须先跑下面两步 |
| `remote` | `data-src` 换成真实远程 URL 作 `src` → 文件小，**看图需联网** | 不需要 |
| `strip` | 删除全部 `<img>` → 纯文字存档 | 不需要 |

embed 模式的两步下载（产出在 `scripts/` 下，供 make_html.py 读取）：
```bash
python3 make_img_manifest.py   # 按 data-src 出现顺序生成 img_manifest.json（URL 已 unescape）
bash download_imgs.sh          # 逐张 curl → scripts/img/{mid}_{seq}.{ext}
```
> 图片 URL（mmbiz.qpic.cn）是公开 CDN，无需会话参数；实际可直连下载，不必全经代理。

### 7. 转换输出（默认格式 md；图片策略按步骤 6 用户选择）

- **Markdown（默认）**：`python3 convert.py` 批量 → `工作区根/articles_md/{文章标题}.md`（同样按标题命名）。加 `env STRIP_IMAGES=1` 输出**纯文字**（删图，正文图片较多时选它最省）；单篇预览 `python3 convert.py html/xxx.html`。已兼容新版「分享页」模板（从 og:title 提取全文，字面 `\n` 已归一化）与平台已删文章（自动跳过、不产出空文件）。`原文链接` 已自动用正文页 `window.short_link` 的 **`/s/<hash>` 短链**（浏览器可开）；长链 `/s?__biz=...` 带会话参数、浏览器打开报 parameter error，仅作缺失时的回退。
- **HTML（可选）**：`python3 make_html.py` → `工作区根/articles_html/{文章标题}.html`（标题命名，重名自动 `_2` 后缀；CSS 已覆盖微信残留旧字体与 `visibility:hidden`，正文不再整篇不可见）。图片模式见步骤 6，`img_mode=embed` 需先下载图片；`remote`/`strip` 无需。已兼容新版分享模板。

> 中间产物 `scripts/html/{mid}.html` 保留 mid 命名（防重名打架、断点续跑按它跳过）；**最终交付物** `articles_md/`、`articles_html/` 统一按标题命名，放在工作区根。

## 关键坑（全部踩过，务必遵守）

1. **getmsg 必须带 `appmsg_token` URL 参数**，否则 `ret:0` 但 `msg_count:0`。
2. **key 每 2~4 分钟轮换** → 翻页/正文循环每页前刷新（脚本已内置）；拿不到新 key 就让用户再打开一篇。
3. **getmsg/正文必须和微信同一个公网出口**。本机 `MITM_PROXY=direct`（`curl_via_proxy` 不带 `-x`）。python 沙箱或另一台机器 → 空列表。跨机器才把 `MITM_PROXY` 指到微信那台机器上的 regular 端口，并且不要设成系统代理。
4. **浏览器/无会话访问全部被拦**（验证页 / 「请在微信客户端打开」），别走浏览器方案。
5. **local 劫持进程挂了就没有新 key**。看 `scripts/mitm.pid` 是否还活着，以及 `scripts/mitm.log`。先 `bash scripts/start_proxy.sh --stop` 再启动。local 模式没有监听端口。文章页转圈多半是证书（坑 13），不是端口没开。
6. **Windows 首选 Git Bash 跑 `.sh`**（cmd / PowerShell **直接**去执行 `.sh` 会破坏双引号、`$` 与参数拼接——所以不能拿 cmd/PowerShell 硬跑 `.sh`）。**若系统没有 sh（无 Git Bash / WSL），改为按「Windows 无 sh 环境」小节把 `.sh` 就地移植成 `.ps1`/`.bat` 运行，而不是要求用户去装 Git Bash**（移植要点与验证见该节）。Git Bash 里路径含空格加引号即可，不需要 8.3 短路径；启动时先 `export PYTHONUTF8=1`（PowerShell 下改设 `$env:PYTHONUTF8='1'`）。
7. **别用 PowerShell `Get-Content` 读大 JSONL**（正文行 1.5MB，文件上百 MB 会卡死）→ 统一用 Python 读（refresh_loop.py 用 seek 尾部读取；.sh 内部也只用 `$PY` 调 Python）。
8. **curl `-H` 别直接拼变量**：`-H "Cookie: " + $var` 会被拆成多个参数（变量值可能被 curl 当成 URL）→ 先拼好 `$hd=...` 再整体 `-H "$hd"`（common.sh / fetch_*.sh 已用此模式）。
9. **插件保存响应体必须先按 content-encoding 解压**（gzip/br/zstd），否则正文是乱码；超大响应体只留 2KB 小样（`resp_body_truncated` 记录原长度）——避免把 fetch_bodies 抓回的正文（1.5MB+ 单行）写进 wechat_flows.jsonl 撑爆读取窗口。
10. **每次抓取前确认 params.txt 里有 `biz=` 行**（换公众号重抓时 delete 旧的 params.txt 再重导一次流量，避免残留旧号参数混用）。
11. 正文 HTML 中图片是懒加载：取 `data-src`（非 `src`）；URL 中 `&amp;` 需 unescape（make_img_manifest.py / make_html.py 已处理）。
12. getmsg 列表最多覆盖公众号**近期历史**（数百篇），更早的可能拿不到——交付时说明实际篇数与时间范围。
13. **macOS 证书信任必须走系统钥匙串**：`login.keychain-db` 对沙箱化 WeChatAppEx（Chromium）无效，抓包时微信文章会一直「转圈」且日志报 `Client TLS handshake failed ... does not trust the proxy's certificate`。装系统钥匙串要 `sudo`（用户在自己终端执行，agent 的 `!` 前缀无 TTY 读不了密码）。
14. **不必退出微信**。local 模式劫持的是启动之后的新连接；已经池化的 HTTP/2 仍直连。`start_proxy.sh` 重置文章页进程上非回环的 443（macOS `sudo pfctl -k <本机IP> -k <对端IP>`）。没有 sudo 时按脚本打印的命令执行，或在文章页里点一下/下拉。不要 Cmd+Q。
15. **key 轮换靠文章页续命**：`key` 每 2~4 分钟轮换，且**只有微信客户端在活跃请求时才产生新 key**（jsmonitor 每几秒一发的文章页）。抓取期间要反复叮嘱用户**保持文章页开着**；用户一旦关闭，key 断供。拿不到新 key 就让用户再开一篇。
16. **Mac 客户端 `appmsg_token` 在 URL 参数、请求不带 Cookie**：若用 Cookie-only 脚本提取会拿到空 token，getmsg 返回空列表。`refresh_loop.py` 已双路兼容；但验证 getmsg 时若 `msg_count:0` → 先检查 params.txt 里 `tok=` 是否为空。
17. **不要设置系统代理**。local 模式只劫持文章页进程里发往 `mp.weixin.qq.com` 的连接（`--allow-hosts`），其它应用保持原网络。机器上已有 Clash 等代理也别改。抓完 `--stop` 停 mitmdump，没有系统代理要还原。若 `lsof` 看到文章页进程连的是 `127.0.0.1:7897` 这类本机 HTTP 代理而不是外网 443，微信流量在进 local 模式之前就已经进了那层代理，jsonl 里不会出现 `mp.weixin.qq.com`。让文章页直连（或只用 TUN），不要再叠一层系统代理。
18. **`can_msg_continue` 不可靠**：部分会话恒为 0 但下一页仍有效。所有停页/续页判定用 `next_offset` 前进；只信 `can_msg_continue` 会只抓一两页。
19. **新版「分享页」模板（`mmbizwap:pages/common_share.html`）**：抓部分文章时 `/s?` 返回的不是 `<div id="js_content">` 而是壳页，全文在 `og:title` meta 里（段落分隔常是**字面 `\n`**，转换前必须归一化）。另有 appmsg_type=9 图集/互动帖 `og:title` 仅标题、无文字正文——纯文字模式下此类输出占位/跳过即可。
20. **正文有效性必须按内容校验，文件大小不可靠**：2MB 的壳页/降级页没有正文却会被误判成功；平台已删文章（页面显示「此内容因违规无法查看」）任何会话都拿不到，交付时如实说明。
21. **必须按 `(mid, idx)` 区分文章，正文存 `{mid}_{idx}.html`**：微信一个群发 = 一个 mid、多个子文章（idx=1..8）。早期脚本按 mid 去重/命名导致：同群发附加文全丢、只剩最后一条（多为尾条小视频）、正文互相覆盖。已在 parse_articles.py / fetch_bodies.sh / convert.py 修复（去重键改了，`fetch_bodies` 支持 `ARTS_FILE` 子集，`convert` 兼容 `{mid}_{idx}` 文件名）。旧数据若只有 `{mid}.html` 可继续用。
22. **原文链接用短链**：convert.py 自动从正文提取 `window.short_link`（`/s/<hash>`，公开可开）。长链 `/s?__biz&mid&idx&sn` 无会话参数时浏览器报 parameter error——交付的原文链接必须是短链。

## 附录：微信 UA

```
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) WindowsWeixin(0x63090C0B-0x0)
```

## 交付

- 完成后 artifact_mark 标记产物：`<公众号名>/articles_md/`（Markdown，默认）或 `<公众号名>/articles_html/`（HTML），均为标题命名；如需可再打合并 zip。
- 向用户说明：总篇数、时间范围、保存路径（工作区根下的 `articles_md/` 或 `articles_html/`）、文件名规则（**标题命名**）、格式（md/html）与图片策略（embed 内嵌 / remote 远程 / strip 无图——本次用了哪种）。
- 抓完执行 `bash scripts/start_proxy.sh --stop`。不要改、也不要「还原」系统代理。
- 合规提醒：仅用于你有权访问的内容（你的账号能正常查看的公众号文章）。