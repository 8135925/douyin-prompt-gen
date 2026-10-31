# -*- coding: utf-8 -*-
"""核心逻辑：抖音短链提取、目录归档、浏览器自动化下载音频、提示词生成。"""
import re
import shutil
from pathlib import Path

DOUYIN_LINK_RE = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_-]+/?")
WINDOWS_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')

SITE_URL = "https://vidgap.com/douyin/audio/cn"

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
    blacklist = ("下载器", "如何", "历史", "离线", "Offline", "PC", "App", "MP3", "音效", "幻灯片")
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


def download_audio(link: str, work_dir: Path, title: str, log, headless: bool = False) -> Path:
    """用 Playwright 打开 vidgap，粘贴短链、点击下载、捕获 mp3 并归档到 work_dir/{{title}}.mp3。"""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    dest = work_dir / f"{title}.mp3"
    log(f"打开下载站点：{SITE_URL}" + ("（无头模式）" if headless else ""))
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=headless)
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
                dl_btn.wait_for(state="visible", timeout=90_000)
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
                log("等待下载任务出现（最长 180 秒）……")
                with page.expect_download(timeout=180_000) as dl_info:
                    dl_btn.click()
                download = dl_info.value
            except PWTimeoutError:
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

            log(f"捕获到下载文件：{download.suggested_filename}")
            tmp_path = download.path()
            shutil.move(str(tmp_path), dest)
            log(f"重命名并归档完成：{dest}")
            return dest
        except StepError:
            raise
        except Exception as e:
            raise StepError(f"下载过程异常：{e}，请检查链接有效性或站点可用状态。")
        finally:
            browser.close()
