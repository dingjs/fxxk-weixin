# fuck-weixin

A Claude Code Skill that scrapes **all articles** from a WeChat Official Account. Outputs Markdown by default (file name = article title), with optional HTML; images can be embedded, kept as remote URLs, or stripped.

**English** | [中文](README.md)

> The repository is named `fxxk-weixin`; the skill name (the `name` field in `SKILL.md`) is `fuck-weixin`.

## How it works

WeChat blocks non-client access: curl or a browser without a session gets a CAPTCHA page, and opening the account profile in a browser gets "please open this link in WeChat". This project therefore works as follows:

1. **mitmproxy in local mode** intercepts only new connections from the WeChat article-page process (`WeChatAppEx` network service) to `mp.weixin.qq.com`. **It does not set a system proxy**, so other apps are unaffected.
2. Session signatures are extracted from those requests: `key`, `pass_ticket`, `uin`, `appmsg_token`, `__biz`.
3. The list endpoint `mp/profile_ext?action=getmsg` is called directly **on the same machine as WeChat**, paging through the article list, then each article body is fetched.
4. Bodies are parsed and rendered to Markdown / HTML.

WeChat's risk control looks at the public egress IP, so scraping must share the machine and egress with the WeChat client. `key` rotates every 2–4 minutes; the scripts reload fresh parameters before every page and every article.

## Requirements

- Python 3
- mitmproxy **10.2+** (local mode is available from 10.2)
- bash 3.2+, curl
  - On Windows, **Git Bash from Git for Windows is preferred**
  - If no sh is available (no Git Bash / WSL), ask the Claude Code agent to port `scripts/*.sh` in place to `.ps1` / `.bat` following the "Windows without sh" section of `SKILL.md`; no extra install is needed
- A machine with PC WeChat logged in that can view the target Official Account

## Install

```bash
git clone https://github.com/dingjs/fxxk-weixin.git ~/.claude/skills/fuck-weixin
```

Make sure `SKILL.md` sits at the skill root (the repository root is the skill directory): `~/.claude/skills/fuck-weixin/SKILL.md` and `~/.claude/skills/fuck-weixin/scripts/`.

## Quick start

> The first run requires a one-time install of the mitmproxy CA certificate. On macOS it must go into the **System keychain**; `login.keychain-db` does not work for the sandboxed WeChatAppEx (this needs `sudo`, so run it in your own terminal).

1. **Start interception** (no system proxy, no need to quit WeChat):

   ```bash
   export PYTHONUTF8=1 && export PYTHONIOENCODING=utf-8
   bash scripts/start_proxy.sh
   ```

2. **Install the certificate** (one time): add `~/.mitmproxy/mitmproxy-ca-cert.pem` to the system trust store.
   - macOS:
     ```bash
     sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem
     ```
   - Windows: double-click `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem` and install it into "Trusted Root Certification Authorities".
   - Linux: copy it to `/usr/local/share/ca-certificates/` and run `update-ca-certificates`.

3. **Do this once in PC WeChat**:
   1. Search for the target Official Account and open its chat window.
   2. Click the account name at the top right to open its profile, then scroll a few times.
   3. **Open any article.**
   4. **Keep the article page open** (key rotation depends on the article page's ongoing jsmonitor requests).

4. **Confirm a key has arrived**:

   ```bash
   bash scripts/start_proxy.sh --wait-key 25
   ```

   Success means a newly appended line in `wechat_flows.jsonl` contains both `mp.weixin.qq.com` and `key=daf9bd`.

5. **Extract session parameters in the background**:

   ```bash
   python3 refresh_loop.py &
   ```

   It refreshes `params.txt` every 3 seconds with `key` / `pass_ticket` / `uin` / `appmsg_token` / Cookie / `__biz`.

## Scraping flow

Copy `scripts/` into a workspace named after the Official Account, then run the scripts there. Deliverables go to the workspace root:

```text
account-name/
├── scripts/            # script copy + intermediate artifacts
│                       #   wechat_flows.jsonl / params.txt / getmsg_pages/ / html/{mid}_{idx}.html / img/
├── articles_md/        # deliverable: Markdown (default, named by title)
└── articles_html/      # deliverable: HTML (optional, named by title)
```

```bash
# 1. Page through the full article list -> getmsg_pages/p{offset}.json
bash scripts/fetch_list.sh

# 2. Parse the list -> articles_list.json
python3 scripts/parse_articles.py

# 3. Fetch every article body -> scripts/html/{mid}_{idx}.html
bash scripts/fetch_bodies.sh

# 4a. Default Markdown output -> articles_md/{article-title}.md
python3 scripts/convert.py

# 4b. Optional HTML output -> articles_html/{article-title}.html
python3 scripts/make_html.py
```

To grab only the newest N articles, set `MAX_OFFSET=<offset>` (for example `MAX_OFFSET=100` means the newest 10 pages, 10 bundles per page). The offset counts **bundles**, which expand into more sub-articles after parsing.

## Output formats and image strategies

Markdown is the default. For plain text:

```bash
env STRIP_IMAGES=1 python3 scripts/convert.py
```

HTML image modes are controlled by `img_mode`:

| Mode | Effect | Download images first? |
| --- | --- | --- |
| `embed` (default) | Images embedded as base64; single self-contained offline file | Yes |
| `remote` | Images keep their remote URLs; smaller files, needs network to view | No |
| `strip` | All images removed; plain-text archive | No |

For `embed`, run:

```bash
python3 scripts/make_img_manifest.py
bash scripts/download_imgs.sh
python3 scripts/make_html.py img_mode=embed
```

## Scripts

| File | Purpose |
| --- | --- |
| `scripts/start_proxy.sh` | Start / stop local interception; `--wait-key` waits for a valid key |
| `scripts/saver.py` | mitmproxy addon that records only `mp.weixin.qq.com` traffic carrying key / `__biz` / `appmsg_token` |
| `scripts/refresh_loop.py` | Extracts the latest session parameters from the JSONL tail into `params.txt` |
| `scripts/fetch_list.sh` | Pages through the article list via `getmsg` |
| `scripts/parse_articles.py` | Parses the list, deduplicates by `(mid, idx)`, writes `articles_list.json` |
| `scripts/fetch_bodies.sh` | Fetches article body HTML one by one |
| `scripts/check_article.py` | Validates whether a body page is usable |
| `scripts/wechat_extract.py` | Shared title / date / body extraction module |
| `scripts/make_img_manifest.py` | Builds the image manifest (only needed for `embed`) |
| `scripts/download_imgs.sh` | Downloads body images (only needed for `embed`) |
| `scripts/convert.py` | Renders Markdown deliverables |
| `scripts/make_html.py` | Renders HTML deliverables |
| `scripts/common.sh` | Shared helpers: parameter loading, proxied curl, file size |

## Caveats

- **Do not set a system proxy.** Local mode only takes over connections from the article-page process to `mp.weixin.qq.com`. If article-page traffic enters a local proxy such as Clash first, no key will be captured.
- **Do not quit WeChat.** Local mode intercepts new connections made after startup; closing the article page cuts off the key source.
- **Use the same egress IP as WeChat.** Sending `getmsg` from a Python sandbox or another machine returns an empty list. Only when curl is not on the WeChat machine should you run with `WX_MITM_MODE=regular` to expose a port for curl, set `MITM_PROXY`, and avoid making it a system proxy.
- **`getmsg` must include `appmsg_token` as a URL parameter.** Cookie-only requests return `msg_count:0`. The Mac client already puts it in the URL and sends no Cookie; the scripts support both paths.
- **Use `next_offset` advancing as the paging stop condition**, not `can_msg_continue` alone (that field is always 0 for some accounts).
- **The article dedup key is `(mid, idx)`.** One mass-send is one `mid` with up to 8 sub-articles; deduplicating by `mid` alone loses the attached articles.
- **Validate body pages by content markers**, not file size. Articles deleted by the platform are unreachable with any session.
- **On macOS the certificate must be in the System keychain.** Otherwise WeChat article pages spin forever and the log reports `Client TLS handshake failed`.
- Stop interception when done: `bash scripts/start_proxy.sh --stop`.

## Compliance

This project is only for scraping **content you are entitled to access** (articles your own WeChat account can view normally). Follow WeChat's terms and applicable laws; do not use it for mass infringement, bypassing access controls, or other improper purposes.

## License

Released under the [Apache License 2.0](LICENSE). Copyright 2026 dingjs.
