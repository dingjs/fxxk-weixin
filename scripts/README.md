# fuck-weixin 脚本说明

抓取微信公众号全部文章 -> HTML（**文件名=文章标题**；图片是否内嵌/远程/去图由用户决定，`img_mode=embed|remote|strip`）或可选 Markdown（同按标题命名）。

同一套 `.sh`（bash）在所有平台运行：Linux/macOS 原生跑，Windows **首选** Git for Windows 的 Git Bash 跑。**若 Windows 没有 sh（无 Git Bash / WSL），由 agent 把 `.sh` 就地移植成同名的 `.ps1`（配 `.bat` 启动器）再运行，行为一致（见 SKILL.md「Windows 无 sh 环境」小节）。** Python 解析器由 common.sh 自动探测（`python3`/`python`/`py`，可用环境变量 `PY` 覆盖）；直接运行的 python 脚本（parse_articles / make_img_manifest / make_html / convert / refresh_loop）在 Windows 下用 `python`（或 `py`）代替 `python3` 即可。

## 前置（一次性）

1. 启动劫持（**不改系统代理，不必退出微信**）：跑 `start_proxy.sh`，`proxy.cfg` 写 `MODE=local`、`PROCS=...`、`MITM_PROXY=direct`：
   - 安装 mitmproxy 10.2+：macOS `brew install --cask mitmproxy`；Windows `winget install mitmproxy`；Linux `pip install mitmproxy`
   - 启动：`bash start_proxy.sh`（`--mode local`，只劫持 WeChatAppEx 网络服务；并重置文章页已有的外网 443）
   - 看到 key：文章页开着之后 `bash start_proxy.sh --wait-key 25`（只认 jsonl 新增行里的 `mp.weixin.qq.com` + `key=daf9bd`）
   - 停止：`bash start_proxy.sh --stop`
2. macOS 证书必须装**系统钥匙串**（`sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ...`，login keychain 对 WeChatAppEx 无效）。列表和正文在本机直连（`MITM_PROXY=direct`）
3. 用户在 PC 微信打开目标公众号 -> 主页 -> 点开任意一篇文章（产生 mp.weixin.qq.com 请求），**并保持文章页开着**（key 轮换依赖其 jsmonitor 流量）
4. 依赖：bash 3.2+（macOS/Linux 自带；Windows 用 Git Bash）或**移植后的 PowerShell**（Windows 无 sh 时，由 agent 就地生成 `.ps1`/`.bat`）、curl、Python 3（解析器自动探测 `python3`/`python`/`py`）

## 脚本

| 文件 | 作用 | 运行方式 |
| --- | --- | --- |
| saver.py | mitmproxy 插件：只把 `mp.weixin.qq.com` 上带 key/__biz/appmsg_token 的流量追加写 wechat_flows.jsonl | mitmdump -s 加载（start_proxy.sh 传入） |
| start_proxy.sh | 启动/复用/停止 local 劫持：不改系统代理，按网络服务 PID 或进程名劫持，重置文章页旧 443，`--wait-key` 才算抓到 key | bash start_proxy.sh [--wait-key 秒] [--stop] |
| refresh_loop.py | 每 3 秒从 JSONL 尾部提取最新 key/pass_ticket/appmsg_token/Cookie/__biz -> params.txt（key 2~4 分钟轮换；appmsg_token 兼容 URL 参数与 Cookie 两路） | 后台常驻 |
| parse_articles.py | getmsg_pages/*.json -> articles_list.json（含主文+附加文、去重、unescape） | python3 parse_articles.py |
| fetch_list.sh | 读 params.txt，getmsg 翻页拉全部文章列表 -> getmsg_pages/p{offset}.json（同 offset 自动重试；下一页判据用 next_offset 前进，缺失回退 can_msg_continue） | bash fetch_list.sh |
| fetch_bodies.sh | 读文章清单 + params.txt，逐篇 curl 正文 -> html/{mid}.html | bash fetch_bodies.sh |
| wechat_extract.py | 正文/标题/时间提取共享模块：item_show_type 7/8/10 特殊类型、音频文章、div 深度取正文、有效性判定与不可用原因分类 | 被 convert.py / make_html.py / check_article.py 引用 |
| check_article.py | 正文有效性判定封装（OK / BAD[:原因]），供 fetch_bodies.sh 的 valid_page 调用 | python3 check_article.py <html> |
| make_img_manifest.py | html/{mid}.html -> img_manifest.json（图片 URL 清单，已 unescape；**仅 embed 模式需要**） | python3 make_img_manifest.py |
| download_imgs.sh | 按 img_manifest.json 逐张下载正文图片（mmbiz.qpic.cn 是公开 CDN 可直连）-> img/{mid}_{seq}.{ext}；**仅 embed 模式需要** | bash download_imgs.sh |
| make_html.py | 正文 HTML -> 工作区根/articles_html/{文章标题}.html（可选格式）。图片模式 `img_mode=`：`embed`(默认,base64 内嵌,需先下图片) / `remote`(用远程 URL,需联网看图) / `strip`(去图纯文字)。已修复 `visibility:hidden` 导致正文不可见的问题，样式为统一卡片+字体栈覆盖微信内联旧字体，兼容新版分享模板 | python3 make_html.py（可加 `img_mode=remote`） |
| convert.py | 正文 HTML -> 工作区根/articles_md/{文章标题}.md（**默认格式**；标题命名、重名去重。`env STRIP_IMAGES=1` 输出纯文字，兼容新版分享模板，平台已删文章自动跳过） | python3 convert.py |
| common.sh | .sh 脚本共享：加载 params.txt、代理 curl、文件大小（bash 3.2 兼容） | 被 .sh 引用 |

> **Windows 无 sh 时**：上表所有 `*.sh` 替换为同名 `*.ps1`（或双击同名 `*.bat`），`.py` 不变（用 `py`/`python` 调），行为与 `.sh` 一致。移植要点与环境变量映射见 SKILL.md「Windows 无 sh 环境」小节。

## 关键参数/约定

- 所有会话参数（含 __biz）由 refresh_loop.py 写入 params.txt，各脚本实时读取，**不再写死 __biz**
- getmsg URL 必须带 appmsg_token 参数（仅 Cookie 不够），且必须和微信从同一个公网 IP 出去（本机直连；跨机器才 `-x`）
- Mac 客户端把 appmsg_token 放 URL 参数（请求不带 Cookie），refresh_loop.py 已双路兼容
- 图片命名：img/{mid}_{seq}.{ext}（seq 按正文 data-src 出现顺序，ext 按 URL 判断 gif/png/webp/jpg）
- 最终交付文件名 = 文章标题（非法字符 \/:*?"<>| 替换为 _，首尾空白/点去除，超 80 字符截断，重名自动 _2）；中间产物 html/{mid}.html 保留 mid

## 流程（agent 或手工执行）

1. 环境就绪 -> `start_proxy.sh`（不退出微信）-> 用户打开公众号并点开一篇文章（保持文章页开着）-> `--wait-key` -> 启动 refresh_loop.py 后台刷参数
2. 验证 getmsg（offset=0）成功
3. fetch_list.sh 翻页全部 -> python3 parse_articles.py 解析清单
4. fetch_bodies.sh 逐篇抓正文 -> html/{mid}.html（正文有效性按内容标记校验，不只按大小；key 空窗期对同一 mid 重试不跳过）
5. **交付格式默认 md，图片策略由用户决定**：
   - 保留图片（HTML 交付 embed/remote 才需要图）：embed 先 `python3 make_img_manifest.py` -> `bash download_imgs.sh` 下载图片 -> img/；remote/strip 跳过
   - Markdown 纯文字：`env STRIP_IMAGES=1 python3 convert.py`
6. `python3 make_html.py [img_mode=...]` 生成 工作区根/articles_html/{标题}.html；`python3 convert.py` 生成 工作区根/articles_md/{标题}.md（默认）
7. artifact_mark 交付；`start_proxy.sh --stop`（不要改系统代理）

## 环境变量（.sh 可覆盖）

- `WORKSPACE_DIR=/path` ：脚本读写文件改到该目录（默认=脚本所在目录）；**必须与 refresh_loop.py 写 params.txt 的目录一致**
- `MITM_PROXY=direct` ：本机直连（默认）。解析顺序：环境变量 > `proxy.cfg` > `direct`。只有 curl 不在微信那台机器上才设 `http://host:port`
- `WX_MITM_MODE=local|regular` ：默认 `local`。`regular` 只给跨机器 curl 开端口，不要设成系统代理
- `WX_LOCAL_PROCS=WeChatAppEx Helper` ：覆盖自动发现的进程名或 PID（逗号分隔）
- `WX_ALLOW_HOSTS=正则` ：local 模式只解密这些主机，默认 `mp.weixin.qq.com`
- `WX_MITM_PORTS=8080 8868 ...` ：仅 `regular` 模式的候选端口（默认 `8868 10809 8088 8964 8080`）
- `MITMDUMP=mitmdump` ：start_proxy.sh 用的 mitmdump 命令（PATH 内或绝对路径）
- `WX_PROXY_CFG` / `WX_FLOWS` ：start_proxy.sh 的 proxy.cfg / 验证流量文件路径（默认都在脚本目录）
- `PY=python3` ：python 解析器（默认自动探测 `python3`/`python`/`py`；Windows Git Bash 探测不到时用 `export PY=python` 指定）