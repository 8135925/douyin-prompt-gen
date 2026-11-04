# -*- coding: utf-8 -*-
"""核心逻辑：抖音短链提取、目录归档、浏览器自动化下载音频、提示词生成。"""
import re
import shutil
from pathlib import Path

DOUYIN_LINK_RE = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_-]+/?")
WINDOWS_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')

SITE_URL = "https://vidgap.com/douyin/audio/cn"
SNAPTIK_URL = "https://snaptik.fi/zh"
DLPANDA_URL = "https://dlpanda.com/zh-CN"


def _ensure_playwright_browsers_path():
    """PyInstaller 打包后，playwright 会去解包临时目录找浏览器内核；
    显式指向系统默认内核目录，确保 `playwright install chromium` 装的内核可用。"""
    import os
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        local_app = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(local_app, "ms-playwright")

PROMPT_TEMPLATE = """我要参加抖音上的 Vibe知识大赏
请调用 vibe-knowledge-file 这个 skill 生成一条抖音发布视频，具体参数与要求如下：

**1. 音频配置**
- 背景音乐：C:\\Users\\ASUS\\Documents\\{{变量1}}\\{{变量1}}.mp3
- 音画同步：视频总时长必须等于音频时长，不要裁剪音频，不要延长或缩短音频，音频结束时画面自然收尾，不要突然黑屏，画面、字幕、音频三者时间轴严格对齐。（画面、字幕、音频三者时间轴严格对齐 ×3）
- 字幕文字：字幕文字必须与提供的文案文本完全一致，不得改写；每一句字幕的末尾绝对不带任何逗号、句号等标点符号，确保视觉上的干净利落与绝对对齐。

**2. 视觉规范**
- 封面输出：同时生成横屏 cover_h.png（1441×1080）与竖屏 cover_v.png（1080×1441）。
- 水印设置：水印「陆壹」在右下角，20px、20% 不透明度，全片常驻（片尾淡出）。

**3. 发布物料**
- 自动生成适配抖音平台的标题（固定为 Vibe知识大赏 | {{变量1}}）与简介文案。标题为 {{变量1}}，封面主题同样使用 {{变量1}}。

**4. 视频文案内容**：
{{变量2}}

**5. 输出归档**
最终生成的视频、封面、发布抖音的 markdown 文件，均复制一份到 C:\\Users\\ASUS\\Documents\\{{变量1}} 目录下。"""


class StepError(Exception):
    """业务步骤失败，message 直接展示给用户。"""


def extract_douyin_link(raw_text: str) -> str:
    """从整段分享文本中提取 https://v.douyin.com/... 短链。"""
    m = DOUYIN_LINK_RE.search(raw_text or "")
    if not m:
        raise StepError("未检测到有效抖音链接，请检查粘贴内容是否包含 v.douyin.com 短链。")
    return m.group(0)


def sanitize_title(title: str) -> tuple[str, list[str]]:
    """清洗 Windows 非法文件名字符，返回 (清洗后标题, 被移除的字符列表)。"""
    removed = sorted(set(WINDOWS_ILLEGAL_CHARS.findall(title or "")))
    cleaned = WINDOWS_ILLEGAL_CHARS.sub("", (title or "")).strip()
    if not cleaned:
        raise StepError("标题为空（或清洗后为空），请填写有效标题。")
    return cleaned, removed


def create_work_dir(docs_root: Path, title: str) -> Path:
    """在文档根目录下创建（或复用）以标题命名的工作目录。"""
    docs_root = Path(docs_root).expanduser()
    if not docs_root.exists():
        raise StepError(f"文档根目录不存在：{docs_root}，请在设置中修改。")
    try:
        work_dir = docs_root / title
        work_dir.mkdir(parents=True, exist_ok=True)
        # 探测写入权限
        probe = work_dir / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return work_dir
    except PermissionError:
        raise StepError(f"目录无写入权限：{work_dir}，请切换文档根目录后重试。")
    except OSError as e:
        raise StepError(f"创建工作目录失败：{e}")


def render_prompt(title: str, copy_text: str, audio_dir_literal: str | None = None) -> str:
    """替换模板变量生成成品提示词。audio_dir_literal 用于覆盖模板中的绝对路径前缀。"""
    base = audio_dir_literal if audio_dir_literal else "C:\\Users\\ASUS\\Documents"
    prompt = PROMPT_TEMPLATE.replace("C:\\Users\\ASUS\\Documents\\{{变量1}}", f"{base}\\{{{{变量1}}}}")
    prompt = prompt.replace("{{变量1}}", title)
    prompt = prompt.replace("{{变量2}}", copy_text)
    return prompt


def _find_visible_download_button(page, log, box):
    """在与输入框同一行（右侧）的可见元素中找下载按钮。

    策略：收集所有可见的 button/[role=button]/a，排除导航类文本
    （下载器/如何下载/历史等），按（文本精确度, 与输入框的垂直距离, 文本长度）排序，
    命中输入框旁边那个真正的『下载』按钮。
    """
    input_box = box.bounding_box()
    blacklist = ("下载器", "如何", "历史", "离线", "Offline", "PC", "App", "MP3", "音效", "幻灯片",
                 "tiktok", "主页", "常见问题", "联系我们")
    candidates = page.locator(
        "button, [role='button'], a:has-text('下载'), a:has-text('下載'), "
        "div:has-text('下载'), div:has-text('下載'), span:has-text('下載'), "
        "[class*='btnDl'], [class*='DownloadBtn'], [class*='download-btn']"
    )
    total = candidates.count()
    log(f"扫描到 {total} 个候选元素，按位置筛选……")
    best, best_key = None, None
    for i in range(min(total, 300)):
        el = candidates.nth(i)
        try:
            if not el.is_visible():
                continue
            text = (el.inner_text() or "").strip()
            eb = el.bounding_box()
        except Exception:
            continue
        if not text or len(text) > 8:
            continue
        if not any(k in text for k in ("下载", "下載", "解析", "提取", "获取", "轉換", "转换")):
            continue
        if any(b.lower() in text.lower() for b in blacklist):
            continue
        if not eb:
            continue
        # 与输入框同行优先（垂直距离小），且在输入框右侧或同一容器内
        dy = abs(eb["y"] - input_box["y"]) if input_box else 0
        key = (0 if text in ("下载", "下載") else 1, dy, len(text))
        if best_key is None or key < best_key:
            best_key, best = key, el
    if best:
        log(f"定位到下载按钮，文本：{best.inner_text().strip()!r}")
    else:
        log("未找到任何匹配的下载按钮", "warn")
    return best


def download_audio(link: str, work_dir: Path, title: str, log, headless: bool = False,
                   proxy: str | None = None) -> Path:
    """用 Playwright 打开 vidgap，粘贴短链、点击下载、捕获 mp3 并归档到 work_dir/{{title}}.mp3。"""
    import os
    _ensure_playwright_browsers_path()

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    dest = work_dir / f"{title}.mp3"
    log(f"打开下载站点（方式1）：{SITE_URL}" + ("（无头模式）" if headless else "")
        + (f"，代理：{proxy}" if proxy else ""))
    with sync_playwright() as p:
        try:
            launch_kwargs = {"headless": headless}
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as e:
            raise StepError(
                f"浏览器启动失败（{e}）。请先执行 `playwright install chromium` 安装内核。"
            )
        try:
            page = browser.new_page(accept_downloads=True)
            page.goto(SITE_URL, timeout=60_000)
            log("页面加载完成，正在定位输入框")
            box = page.locator("input[type='text'], input[type='url'], input:not([type]), textarea").first
            box.wait_for(state="visible", timeout=30_000)
            box.fill(link)
            log("已粘贴抖音短链，定位下载按钮")
            btn = _find_visible_download_button(page, log, box)
            if btn is None:
                raise StepError("未找到可见的下载按钮，站点可能已改版，请稍后重试或手动下载。")
            btn.scroll_into_view_if_needed()
            btn.click()

            # 第二步：解析完成后点击『下载声音 | MP3』按钮触发真正的下载
            log("解析已触发，等待『下载声音 | MP3』按钮出现……")
            try:
                dl_btn = page.locator(
                    "button[data-testid='download-main'][data-feature='music-only']"
                ).first
                dl_btn.wait_for(state="visible", timeout=30_000)
            except PWTimeoutError:
                dl_btn = page.get_by_role("button", name=re.compile("下载声音|下載聲音|MP3"))
                if dl_btn.count() == 0:
                    raise StepError("解析完成但未找到『下载声音 | MP3』按钮，站点可能已改版，请稍后重试。")
                dl_btn = dl_btn.first
                log("未命中 data-testid，回退为文本匹配按钮")
            log("已定位『下载声音 | MP3』按钮，点击并等待下载任务……")
            dl_btn.scroll_into_view_if_needed()

            download = None
            try:
                log("等待下载任务出现（最长 30 秒）……")
                with page.expect_download(timeout=30_000) as dl_info:
                    dl_btn.click()
                download = dl_info.value
            except PWTimeoutError:
                download = None
            return _save_download(page, download, dest, log)
        except StepError:
            raise
        except Exception as e:
            raise StepError(f"下载过程异常：{e}，请检查链接有效性或站点可用状态。")
        finally:
            browser.close()


def _find_visible_audio_button(page, log, box):
    """在解析结果区域（输入框下方）定位『仅下载音频』按钮。

    过滤规则：
    - 排除导航栏元素（位于输入框上方的全部排除）
    - 黑名单排除 下载器/TikTok/如何/主页/常见/联系 等导航类文本
    - 精确含『仅下载音频』优先，其次含 下载音频/音频/Audio/MP3
    """
    candidates = page.locator(
        "button, [role='button'], a:has-text('音频'), a:has-text('Audio'), "
        "a:has-text('MP3'), div:has-text('仅下载'), span:has-text('音频')"
    )
    box_pos = box.bounding_box() if box else None
    blacklist = ("下载器", "如何", "主页", "常见问题", "联系我们", "tiktok", "douyin")
    best, best_key = None, None
    for i in range(min(candidates.count(), 300)):
        el = candidates.nth(i)
        try:
            if not el.is_visible():
                continue
            text = (el.inner_text() or "").strip()
            eb = el.bounding_box()
        except Exception:
            continue
        if not text or len(text) > 30:
            continue
        low = text.lower()
        if not any(k in text or k in low for k in ("仅下载音频", "下载音频", "音频", "audio", "mp3")):
            continue
        if any(b.lower() in low for b in blacklist):
            continue
        if "下载视频" in text and "音频" not in text:
            continue
        if not eb:
            continue
        # 结果区在输入框下方：排除位于输入框上方（导航栏）的元素
        if box_pos and eb["y"] < box_pos["y"] - 20:
            continue
        priority = 0 if "仅下载音频" in text else 1
        dy = abs(eb["y"] - box_pos["y"]) if box_pos else 0
        key = (priority, dy, len(text))
        if best_key is None or key < best_key:
            best_key, best = key, el
    if best:
        log(f"定位到音频下载按钮，文本：{best.inner_text().strip()!r}")
    else:
        log("本轮未找到『仅下载音频』按钮，继续等待……")
    return best


def _launch_stealth_browser(p, headless: bool, log, proxy: str | None = None):
    """启动带反检测配置的浏览器：优先系统 Edge，失败回退 Chromium；
    去除 Headless UA 与 webdriver 特征，避免被站点反爬掐断连接。
    proxy 形如 http://127.0.0.1:7890，可空。"""
    from playwright.sync_api import sync_playwright  # noqa: F401

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    args = ["--disable-blink-features=AutomationControlled"]
    launch_kwargs = {"headless": headless, "args": args}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    browser = None
    last_err = None
    for channel in ("msedge", None):  # 先用系统 Edge（更不易被拦），失败回退 Chromium
        try:
            browser = p.chromium.launch(channel=channel, **launch_kwargs)
            if channel:
                log("使用系统 Edge 内核")
            else:
                log("使用 Chromium 内核")
            break
        except Exception as e:
            last_err = e
            continue
    if browser is None:
        raise StepError(
            f"浏览器启动失败（{last_err}）。请先执行 `playwright install chromium` 安装内核。"
        )
    return browser, UA


def _tcp_tls_connect(host: str, port: int, timeout: int = 8) -> tuple[bool, str]:
    """直连目标主机并做 TLS 握手，返回 (是否成功, 说明)。"""
    import socket
    import ssl
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            with ssl.create_default_context().wrap_socket(s, server_hostname=host):
                return True, "TCP+TLS 握手成功"
    except Exception as e:
        return False, repr(e)


def _proxy_tunnel_test(proxy: str, host: str, port: int, timeout: int = 8) -> tuple[bool, str]:
    """通过代理建立 CONNECT 隧道并做 TLS 握手，返回 (是否成功, 说明)。"""
    import socket
    import ssl
    try:
        hp = proxy.split("://")[-1]
        ph, _, pport = hp.partition(":")
        pport = int(pport or 7890)
        with socket.create_connection((ph, pport), timeout=timeout) as s:
            s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
            reply = b""
            while b"\r\n\r\n" not in reply:
                chunk = s.recv(4096)
                if not chunk:
                    break
                reply += chunk
            status_line = reply.split(b"\r\n")[0].decode(errors="replace").strip()
            if " 200 " not in status_line:
                return False, f"代理应答：{status_line or '(连接被关闭，无应答)'}"
            with ssl.create_default_context().wrap_socket(s, server_hostname=host) as ss:
                return True, f"隧道建立，TLS 握手成功（{ss.version()}）"
    except Exception as e:
        return False, repr(e)


def _diagnose_network(log, proxy: str | None) -> str:
    """浏览器访问失败后自动诊断网络，日志打印每一步，返回结论提示文本。"""
    import urllib.request
    log("—— 开始自动网络诊断 ——")
    proxy_ok_site = proxy_fail_site = direct_ok = False

    if proxy:
        # 1. 代理端口是否在监听
        hp = proxy.split("://")[-1]
        ph, _, pport = hp.partition(":")
        import socket
        try:
            with socket.create_connection((ph, int(pport or 7890)), timeout=3):
                log(f"[诊断1] 代理端口 {ph}:{pport} 正在监听", "ok")
        except Exception as e:
            log(f"[诊断1] 代理端口 {ph}:{pport} 不可达：{e}", "err")
            return "代理软件未运行或端口不对，请检查代理设置。"

        # 2. 经代理隧道访问 snaptik（与浏览器走代理的路径一致）
        ok, detail = _proxy_tunnel_test(proxy, "snaptik.fi", 443)
        proxy_ok_site = ok
        log(f"[诊断2] 经代理访问 snaptik.fi:443 → {'成功' if ok else '失败'}（{detail}）",
            "ok" if ok else "warn")

        # 3. 经代理访问对照站点（检验代理节点本身是否可用）
        ok2, detail2 = _proxy_tunnel_test(proxy, "www.google.com", 443)
        log(f"[诊断3] 经代理访问 www.google.com:443 → {'成功' if ok2 else '失败'}（{detail2}）",
            "ok" if ok2 else "warn")
        if not ok2:
            return "代理节点不可用（Google 也不通），请检查代理软件的节点/订阅。"
        if ok2 and not ok:
            return ("代理节点正常，但 snaptik.fi 经代理仍不通——多为代理软件的分流规则把该域名"
                    "走了直连。请在代理软件中为 snaptik.fi 添加走代理的规则，或切换全局模式后重试。")

    # 4. 直连 snaptik
    ok3, detail3 = _tcp_tls_connect("snaptik.fi", 443)
    direct_ok = ok3
    log(f"[诊断4] 直连 snaptik.fi:443 → {'成功' if ok3 else '失败'}（{detail3}）",
        "ok" if ok3 else "warn")
    if ok3 and not proxy_ok_site:
        return "直连可用但走代理不通，请把「代理（可选）」留空后重试。"

    # 5. 完整 HTTPS 请求（走系统代理设置）
    try:
        req = urllib.request.urlopen("https://snaptik.fi/zh", timeout=15)
        log(f"[诊断5] 完整 HTTPS 请求 → HTTP {req.status}", "ok")
        return "网络层面可通（HTTP 请求成功），问题可能出在浏览器特征被站点识别，请把日志反馈给开发者。"
    except Exception as e:
        log(f"[诊断5] 完整 HTTPS 请求 → 失败：{e}", "warn")

    if direct_ok:
        return "直连与 HTTP 请求均异常，请稍后重试。"
    return "snaptik.fi 直连与代理均不通，可能是站点当前不可用，建议换用方式1（Vidgap）。"


def _open_stealth_page(p, url: str, headless: bool, log, proxy: str | None = None):
    """打开站点页面（带反检测配置）。尝试顺序：无头(代理) → 可见(代理) → 可见(直连)。
    全部失败时自动网络诊断。返回 (browser, page)。"""
    attempts = [(headless, proxy)]
    if headless:
        attempts.append((False, proxy))
    if proxy:
        attempts.append((False, None))
    last_err = None
    for hl, px in attempts:
        browser, UA = _launch_stealth_browser(p, hl, log, proxy=px)
        page = browser.new_page(accept_downloads=True, user_agent=UA,
                                viewport={"width": 1280, "height": 800},
                                locale="zh-CN")
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        try:
            page.goto(url, timeout=60_000)
            return browser, page
        except Exception as e:
            last_err = e
            mode = "无头" if hl else "可见窗口"
            via = f"，代理：{px}" if px else "，直连"
            log(f"访问站点失败（{mode}{via}）：{e}", "warn")
            page.close()
            browser.close()
    conclusion = _diagnose_network(log, proxy)
    raise StepError(
        f"无法访问 {url}：{last_err}。{conclusion}"
    )


def _auto_detect_proxy() -> str | None:
    """读取 Windows 系统代理设置（注册表），返回如 http://127.0.0.1:7890；未配置返回 None。"""
    import urllib.request
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return None
    for scheme in ("https", "http"):
        u = proxies.get(scheme)
        if u:
            if "://" not in u:
                u = "http://" + u
            return u
    return None


def _find_link_input(page, log):
    """智能选择链接输入框：优先占位符/aria-label 含 链接/http/tiktok/douyin 字样的可见输入框，
    避免填到搜索框或语言切换框。"""
    inputs = page.locator(
        "input[type='text'], input[type='url'], input[type='search'], input:not([type]), textarea"
    )
    first_visible = None
    for i in range(min(inputs.count(), 60)):
        el = inputs.nth(i)
        try:
            if not el.is_visible():
                continue
            hint = ((el.get_attribute("placeholder") or "")
                    + (el.get_attribute("aria-label") or "")).lower()
            if any(k in hint for k in ("http", "链接", "tiktok", "douyin", "抖音", "粘贴", "url", "视频")):
                log(f"命中链接输入框（提示文本：{hint[:40]!r}）")
                return el
            if first_visible is None:
                first_visible = el
        except Exception:
            continue
    if first_visible is not None:
        log("未找到带链接提示的输入框，使用第一个可见输入框")
    return first_visible


def _find_submit_button(page, log, box):
    """优先点击输入框所在表单内的 button[type=submit]（与站点实际结构一致），
    失败再回退到通用的位置评分定位。"""
    try:
        form = box.locator("xpath=ancestor::form[1]")
        if form.count() > 0:
            submit = form.first.locator("button[type='submit'], button:not([type])")
            for i in range(submit.count()):
                el = submit.nth(i)
                if el.is_visible():
                    log(f"定位到表单提交按钮，文本：{(el.inner_text() or '').strip()!r}")
                    return el
    except Exception:
        pass
    log("表单内未找到提交按钮，回退到通用定位", "warn")
    return _find_visible_download_button(page, log, box)


def download_audio_snaptik(link: str, work_dir: Path, title: str, log, headless: bool = False,
                           proxy: str | None = None) -> Path:
    """方式2：snaptik.fi —— 粘贴抖音链接 → 点击下载 → 点击『仅下载音频』并捕获 mp3。"""
    _ensure_playwright_browsers_path()
    import time
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    if not proxy:
        proxy = _auto_detect_proxy()
        if proxy:
            log(f"检测到系统代理，自动使用：{proxy}")

    dest = work_dir / f"{title}.mp3"
    log(f"打开下载站点（方式2）：{SNAPTIK_URL}" + ("（无头模式）" if headless else "")
        + (f"，代理：{proxy}" if proxy else ""))
    with sync_playwright() as p:
        browser, page = _open_stealth_page(p, SNAPTIK_URL, headless, log, proxy=proxy)
        try:
            log("页面加载完成，正在定位输入框")
            box = _find_link_input(page, log)
            if box is None:
                raise StepError("未找到链接输入框，站点可能已改版，请稍后重试。")
            box.wait_for(state="visible", timeout=30_000)
            box.fill(link)
            log("已粘贴抖音短链，定位下载按钮")
            btn = _find_submit_button(page, log, box)
            if btn is None:
                raise StepError("未找到可见的下载按钮，站点可能已改版，请稍后重试或手动下载。")
            btn.scroll_into_view_if_needed()
            btn.click()

            # 第二步：解析完成后点击『仅下载音频』
            log("解析已触发，等待『仅下载音频』按钮出现（最长 30 秒）……")
            deadline = time.time() + 30
            audio_btn = None
            while time.time() < deadline:
                audio_btn = _find_visible_audio_button(page, log, box)
                if audio_btn is not None:
                    break
                page.wait_for_timeout(1000)
            if audio_btn is None:
                raise StepError("解析完成但未找到『仅下载音频』按钮，站点可能已改版，请稍后重试。")
            audio_btn.scroll_into_view_if_needed()

            download = None
            try:
                log("已点击『仅下载音频』，等待下载任务出现（最长 30 秒）……")
                with page.expect_download(timeout=30_000) as dl_info:
                    audio_btn.click()
                download = dl_info.value
            except PWTimeoutError:
                download = None
            return _save_download(page, download, dest, log)
        except StepError:
            raise
        except Exception as e:
            raise StepError(f"下载过程异常：{e}，请检查链接有效性或站点可用状态。")
        finally:
            browser.close()


def download_audio_dlpanda(link: str, work_dir: Path, title: str, log, headless: bool = False,
                           proxy: str | None = None) -> Path:
    """方式3：dlpanda.com —— 粘贴链接 → 点击『解析』→ 获取『下载音频』直链下载 mp3。"""
    _ensure_playwright_browsers_path()
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    if not proxy:
        proxy = _auto_detect_proxy()
        if proxy:
            log(f"检测到系统代理，自动使用：{proxy}")

    dest = work_dir / f"{title}.mp3"
    log(f"打开下载站点（方式3）：{DLPANDA_URL}" + ("（无头模式）" if headless else "")
        + (f"，代理：{proxy}" if proxy else ""))
    with sync_playwright() as p:
        browser, page = _open_stealth_page(p, DLPANDA_URL, headless, log, proxy=proxy)
        try:
            log("页面加载完成，正在定位输入框")
            box = _find_link_input(page, log)
            if box is None:
                raise StepError("未找到链接输入框，站点可能已改版，请稍后重试。")
            box.wait_for(state="visible", timeout=30_000)
            box.fill(link)
            log("已粘贴抖音短链，定位解析按钮")

            # 解析按钮：button[type=submit][data-download-submit]
            parse_btn = None
            try:
                cand = page.locator("button[data-download-submit], button[type='submit']")
                for i in range(min(cand.count(), 30)):
                    el = cand.nth(i)
                    if el.is_visible():
                        parse_btn = el
                        break
            except Exception:
                pass
            if parse_btn is None:
                parse_btn = _find_submit_button(page, log, box)
            if parse_btn is None:
                raise StepError("未找到解析按钮，站点可能已改版，请稍后重试。")
            log(f"定位到解析按钮，文本：{(parse_btn.inner_text() or '').strip()!r}")
            parse_btn.scroll_into_view_if_needed()
            parse_btn.click()

            # 等待『下载音频』链接出现（a[data-observed-media='audio']，带 mp3 直链）
            log("解析已触发，等待『下载音频』链接出现（最长 30 秒）……")
            audio_link = page.locator("a[data-observed-media='audio'][data-download-url]").first
            try:
                audio_link.wait_for(state="visible", timeout=30_000)
            except PWTimeoutError:
                fallback = page.get_by_role("link", name=re.compile("下载音频|下載音頻|Download Audio|MP3"))
                if fallback.count() == 0:
                    raise StepError("解析完成但未找到『下载音频』链接，站点可能已改版，请稍后重试。")
                audio_link = fallback.first
                log("未命中 data-observed-media，回退为文本匹配链接")

            # 优先取直链直接下载（比点击更稳）
            url = audio_link.get_attribute("data-download-url") or audio_link.get_attribute("href")
            if url and ".mp3" in url.lower():
                log(f"获取音频直链，直接下载：{url}")
                try:
                    resp = page.request.get(url)
                    if resp.ok:
                        dest.write_bytes(resp.body())
                        log(f"音频已保存：{dest}")
                        log(f"归档完成：{dest}")
                        return dest
                    log(f"直链下载失败（HTTP {resp.status}），改为点击下载……", "warn")
                except Exception as e:
                    log(f"直链下载异常（{e}），改为点击下载……", "warn")

            # 回退：点击链接触发浏览器下载
            download = None
            try:
                log("点击『下载音频』，等待下载任务出现（最长 30 秒）……")
                with page.expect_download(timeout=30_000) as dl_info:
                    audio_link.click()
                download = dl_info.value
            except PWTimeoutError:
                download = None
            return _save_download(page, download, dest, log)
        except StepError:
            raise
        except Exception as e:
            raise StepError(f"下载过程异常：{e}，请检查链接有效性或站点可用状态。")
        finally:
            browser.close()


def _save_download(page, download, dest: Path, log) -> Path:
    """保存捕获的下载文件；未捕获到时回退为扫描页面 mp3 直链下载。"""
    if download is not None:
        log(f"捕获到下载文件：{download.suggested_filename}")
        shutil.move(str(download.path()), str(dest))
        log(f"重命名并归档完成：{dest}")
        return dest
    log("未捕获到浏览器下载事件，尝试查找页面上的 mp3 直链……")
    href = None
    for a in page.locator("a[href]").all():
        u = (a.get_attribute("href") or "")
        if ".mp3" in u.lower():
            href = a.get_attribute("href")
            break
    if not href:
        raise StepError("下载超时：站点无响应或已改版，请检查链接有效性或稍后重试。")
    resp = page.request.get(href)
    log(f"通过直链下载：{href}")
    dest.write_bytes(resp.body())
    log(f"音频已保存：{dest}")
    return dest
