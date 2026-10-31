# -*- coding: utf-8 -*-
"""抖音口播视频一键生成小工具 —— 桌面 GUI。

输入：标题 / 抖音链接（自动提取短链）/ 口播文案
流程：2.1 建目录 → 2.2 提取归档音频 → 2.3 生成提示词 → 2.4 输出提示词
"""
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import core
from core import StepError

APP_TITLE = "抖音口播视频一键生成小工具"
COPY_MAX = 50000        # 硬限制：阻止提交
COPY_WARN = 20000       # 软限制：超出提示

# ---- 配色：暖调中性 + 墨色主按钮 + 苔绿成功色 ----
BG = "#f4f2ee"          # 窗口底色（暖灰纸面）
CARD = "#ffffff"        # 卡片底色
BORDER = "#e6e1d8"      # 卡片描边
FIELD_BORDER = "#d9d4c9"
TEXT = "#2a2823"        # 正文墨色
MUTED = "#8b847a"       # 次要文字
INK = "#1f1d1a"         # 顶部条 / 主按钮
INK_HOVER = "#3a3733"
OK = "#3e7a55"          # 苔绿
WARN = "#a97b2f"
ERR = "#b3483e"
LOG_BG = "#1c1a17"      # 日志深色
LOG_FG = "#d6d0c4"
ACCENT_DOT = "#b56545"  # 步骤指示点亮色（陶土）

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

# ===== 测试阶段默认值（正式使用时删除这三行即可恢复空白输入框）=====
DEFAULT_TITLE = "测试"
DEFAULT_LINK = ("8.28 复制打开抖音，看看【木读精进史的作品】真正的学习，从第四遍才开始，"
                "反复的梳理，是对知识的... https://v.douyin.com/nZz3COvjqoI/ u@s.eo SYz:/ :0pm 06/25")
DEFAULT_COPY = "测试文案"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x800")
        self.minsize(800, 680)
        self.configure(bg=BG)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False
        self._chips = []

        # 自定义窗口图标（打包 exe 后同样生效）
        icon_path = Path(__file__).with_name("icon.ico")
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        self._build_ui()
        self._on_copy_modified(None)  # 同步默认文案的字数显示
        self.after(100, self._poll_log_queue)

    # ---------- UI ----------
    def _card(self, master, title, hint=None):
        """卡片容器：白底 + 细描边 + 小方块标题，替代默认 LabelFrame。"""
        frame = tk.Frame(master, bg=CARD, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=BORDER)
        frame.pack(fill="x", padx=18, pady=(14, 0))
        head = tk.Frame(frame, bg=CARD)
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Frame(head, bg=ACCENT_DOT, width=4, height=14).pack(side="left", padx=(0, 8), pady=1)
        tk.Label(head, text=title, bg=CARD, fg=TEXT,
                 font=(FONT, 10, "bold")).pack(side="left")
        if hint:
            tk.Label(head, text=hint, bg=CARD, fg=MUTED,
                     font=(FONT, 8)).pack(side="right")
        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        return inner

    def _field(self, parent, row, label, default=""):
        tk.Label(parent, text=label, bg=CARD, fg=TEXT,
                 font=(FONT, 9)).grid(row=row, column=0, sticky="w", pady=5)
        entry = tk.Entry(parent, font=(FONT, 10), relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=FIELD_BORDER,
                         highlightcolor=OK, fg=TEXT, bg=CARD, insertbackground=TEXT)
        if default:
            entry.insert(0, default)
        entry.grid(row=row, column=1, sticky="ew", pady=5, padx=(8, 0), ipady=5)
        return entry

    def _hover(self, widget, normal, hover):
        widget.bind("<Enter>", lambda e: widget.config(bg=hover))
        widget.bind("<Leave>", lambda e: widget.config(bg=normal))

    def _build_ui(self):
        # 顶部：墨色横条
        top = tk.Frame(self, bg=INK)
        top.pack(fill="x")
        tk.Label(top, text="抖音口播 · 一键生成", bg=INK, fg="#f4f2ee",
                 font=(FONT, 13, "bold")).pack(anchor="w", padx=20, pady=(12, 0))
        tk.Label(top, text="提取音频 · 归档目录 · 生成发布提示词", bg=INK, fg="#9d968b",
                 font=(FONT, 9)).pack(anchor="w", padx=20, pady=(0, 10))

        # Step1 信息采集
        s1 = self._card(self, "信息采集", hint="三项均为必填")
        s1.columnconfigure(1, weight=1)

        self.entry_title = self._field(s1, 0, "标题名字", DEFAULT_TITLE)
        self.entry_link = self._field(s1, 1, "抖音链接", DEFAULT_LINK)

        tk.Label(s1, text="口播文案", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).grid(row=2, column=0, sticky="nw", pady=5)
        copy_frame = tk.Frame(s1, bg=CARD)
        copy_frame.grid(row=2, column=1, sticky="ew", pady=5, padx=(8, 0))
        self.txt_copy = tk.Text(copy_frame, height=5, font=(FONT, 10), relief="flat", bd=0,
                                wrap="word", undo=True, fg=TEXT, bg=CARD,
                                insertbackground=TEXT, highlightthickness=1,
                                highlightbackground=FIELD_BORDER, highlightcolor=OK)
        self.txt_copy.insert("1.0", DEFAULT_COPY)
        self.txt_copy.pack(fill="both", expand=True)
        self.txt_copy.bind("<<Modified>>", self._on_copy_modified)
        self.lbl_copy_count = tk.Label(copy_frame, text="0 / 50000", bg=CARD, fg=MUTED,
                                       font=(FONT, 8), anchor="e")
        self.lbl_copy_count.pack(fill="x")

        tk.Label(s1, text="文档根目录", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).grid(row=3, column=0, sticky="w", pady=5)
        dir_frame = tk.Frame(s1, bg=CARD)
        dir_frame.grid(row=3, column=1, sticky="ew", pady=5, padx=(8, 0))
        default_root = os.path.join(os.path.expanduser("~"), "Documents")
        self.var_docs_root = tk.StringVar(value=default_root)
        dir_entry = tk.Entry(dir_frame, textvariable=self.var_docs_root, font=(FONT, 9),
                             relief="flat", bd=0, fg=TEXT, bg=CARD, insertbackground=TEXT,
                             highlightthickness=1, highlightbackground=FIELD_BORDER,
                             highlightcolor=OK)
        dir_entry.pack(side="left", fill="x", expand=True, ipady=4)
        btn_browse = tk.Button(dir_frame, text="浏览", command=self._browse_root,
                               font=(FONT, 9), relief="flat", bd=0, bg="#ebe7df", fg=TEXT,
                               activebackground="#e0dbd2", activeforeground=TEXT,
                               padx=12, cursor="hand2")
        btn_browse.pack(side="left", padx=(8, 0))
        self._hover(btn_browse, "#ebe7df", "#e0dbd2")

        # 开始按钮区
        btn_row = tk.Frame(s1, bg=CARD)
        btn_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.var_headless = tk.BooleanVar(value=False)
        tk.Checkbutton(btn_row, text="隐藏浏览器窗口（无头模式，失败时可取消勾选重试）",
                       variable=self.var_headless, bg=CARD, fg=MUTED,
                       activebackground=CARD, activeforeground=TEXT,
                       selectcolor=CARD, font=(FONT, 9), anchor="w",
                       relief="flat", bd=0).pack(fill="x")
        self.btn_start = tk.Button(btn_row, text="开 始 生 成", command=self._on_start,
                                   bg=INK, fg="#f4f2ee", activebackground=INK_HOVER,
                                   activeforeground="#f4f2ee", font=(FONT, 11, "bold"),
                                   relief="flat", bd=0, padx=26, pady=8, cursor="hand2")
        self.btn_start.pack(pady=(10, 0))
        self._hover(self.btn_start, INK, INK_HOVER)

        # Step2 进度与日志
        s2 = self._card(self, "执行进度", hint="实时日志")
        self.lbl_step = tk.Label(s2, text="待开始", bg=CARD, fg=MUTED,
                                 font=(FONT, 9), anchor="w")
        self.lbl_step.pack(fill="x")

        # 四步骤指示条
        chips_row = tk.Frame(s2, bg=CARD)
        chips_row.pack(fill="x", pady=(8, 4))
        for i, txt in enumerate(("2.1 创建目录", "2.2 归档音频", "2.3 生成提示词", "2.4 输出提示词")):
            chip = tk.Label(chips_row, text=f"  {txt}  ", bg=CARD, fg=MUTED,
                            font=(FONT, 9), relief="flat",
                            highlightthickness=1, highlightbackground=BORDER)
            chip.pack(side="left", padx=(0, 8), ipady=3)
            self._chips.append(chip)
        self._update_chips(0)

        style = ttk.Style(self)
        style.configure("App.Horizontal.TProgressbar", troughcolor="#ebe7df",
                        background=OK, bordercolor="#ebe7df",
                        lightcolor=OK, darkcolor=OK)
        self.progress = ttk.Progressbar(s2, mode="determinate", maximum=100,
                                        style="App.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(2, 8))

        self.txt_log = tk.Text(s2, height=10, bg=LOG_BG, fg=LOG_FG, font=(MONO, 9),
                               relief="flat", bd=0, wrap="word", state="disabled",
                               insertbackground=LOG_FG, highlightthickness=0,
                               padx=10, pady=8)
        self.txt_log.pack(fill="both", expand=True)
        self.txt_log.tag_config("warn", foreground="#d8b96b")
        self.txt_log.tag_config("err", foreground="#d97b72")
        self.txt_log.tag_config("ok", foreground="#8fbe9a")

        # Step3 成品提示词
        s3 = self._card(self, "成品提示词")
        head = tk.Frame(s3, bg=CARD)
        head.pack(fill="x")
        self.lbl_result = tk.Label(head, text="等待生成…", bg=CARD, fg=MUTED,
                                   font=(FONT, 9), anchor="w")
        self.lbl_result.pack(side="left")
        self.btn_copy = tk.Button(head, text="复制全部", command=self._on_copy, state="disabled",
                                  bg=OK, fg="#f4f2ee", activebackground="#356a48",
                                  activeforeground="#f4f2ee", font=(FONT, 9, "bold"),
                                  relief="flat", bd=0, padx=14, pady=2, cursor="hand2")
        self.btn_copy.pack(side="right")
        self._hover(self.btn_copy, OK, "#356a48")
        self.txt_prompt = tk.Text(s3, height=8, font=(FONT, 10), relief="flat", bd=0,
                                  wrap="word", state="disabled", fg=TEXT, bg=CARD,
                                  highlightthickness=1, highlightbackground=FIELD_BORDER,
                                  padx=10, pady=8)
        self.txt_prompt.pack(fill="both", expand=True, pady=(8, 0))

        # 底部留白
        tk.Frame(self, bg=BG, height=14).pack()

    def _update_chips(self, stage):
        """stage: 0 待开始；1~4 进行中；5 全部完成。"""
        for i, chip in enumerate(self._chips):
            idx = i + 1
            if stage == 5 or idx < stage:
                chip.config(fg=OK, highlightbackground="#cfe0d6")
            elif idx == stage:
                chip.config(fg=ACCENT_DOT, highlightbackground=ACCENT_DOT)
            else:
                chip.config(fg=MUTED, highlightbackground=BORDER)

    # ---------- 交互 ----------
    def _browse_root(self):
        d = filedialog.askdirectory(title="选择文档根目录")
        if d:
            self.var_docs_root.set(d)

    def _on_copy_modified(self, event):
        self.txt_copy.edit_modified(False)
        n = len(self.txt_copy.get("1.0", "end-1c"))
        color = ERR if n > COPY_MAX else (WARN if n > COPY_WARN else MUTED)
        self.lbl_copy_count.config(text=f"{n} / 50000", fg=color)

    def _log(self, msg, tag=None):
        self.log_queue.put((msg, tag))

    def _poll_log_queue(self):
        try:
            while True:
                msg, tag = self.log_queue.get_nowait()
                ts = datetime.now().strftime("%H:%M:%S")
                self.txt_log.config(state="normal")
                self.txt_log.insert("end", f"[{ts}] {msg}\n", tag or ())
                self.txt_log.see("end")
                self.txt_log.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _set_progress(self, pct, step_text):
        self.progress["value"] = pct
        self.lbl_step.config(text=step_text)
        if pct >= 100:
            stage = 5
        elif pct >= 85:
            stage = 4
        elif pct >= 30:
            stage = 2
        elif pct >= 10:
            stage = 1
        else:
            stage = 0
        self._update_chips(stage)

    def _show_prompt(self, text):
        self.txt_prompt.config(state="normal")
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.insert("1.0", text)
        self.txt_prompt.config(state="disabled")
        self.btn_copy.config(state="normal")
        self.lbl_result.config(text=f"已生成（{len(text)} 字符）", fg=OK)

    def _on_copy(self):
        text = self.txt_prompt.get("1.0", "end-1c").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_result.config(text="已复制到剪贴板", fg=OK)
        self._log("成品提示词已复制到剪贴板。", "ok")

    # ---------- 主流程 ----------
    def _on_start(self):
        if self.running:
            return
        title_raw = self.entry_title.get().strip()
        link_raw = self.entry_link.get().strip()
        copy_text = self.txt_copy.get("1.0", "end-1c").strip()

        if not title_raw:
            messagebox.showwarning("输入校验", "请填写标题名字。")
            return
        if not copy_text:
            messagebox.showwarning("输入校验", "请填写口播文案。")
            return
        if len(copy_text) > COPY_MAX:
            messagebox.showerror("输入校验", f"口播文案超过 {COPY_MAX} 字（当前 {len(copy_text)} 字），已阻止提交，请精简后重试。")
            return
        if len(copy_text) > COPY_WARN:
            if not messagebox.askyesno("输入校验", f"口播文案超过 {COPY_WARN} 字（当前 {len(copy_text)} 字），是否继续？"):
                return

        self.running = True
        self.btn_start.config(state="disabled")
        self.btn_copy.config(state="disabled")
        self.lbl_result.config(text="生成中…", fg=MUTED)
        self._set_progress(2, "开始执行…")

        threading.Thread(target=self._worker, args=(title_raw, link_raw, copy_text), daemon=True).start()

    def _worker(self, title_raw, link_raw, copy_text):
        try:
            # 输入预处理
            try:
                link = core.extract_douyin_link(link_raw)
            except StepError as e:
                self._log(str(e), "err")
                messagebox.showerror("输入校验", str(e))
                return
            self._log(f"已提取抖音短链：{link}", "ok")

            title, removed = core.sanitize_title(title_raw)
            if removed:
                self._log(f"标题含非法文件名字符 {' '.join(removed)}，已自动清洗为：{title}", "warn")
            copy_text = copy_text[:COPY_MAX]

            # 2.1 创建工作目录
            self._set_progress(10, "步骤 2.1 · 创建工作目录")
            docs_root = self.var_docs_root.get().strip()
            try:
                work_dir = core.create_work_dir(docs_root, title)
            except StepError as e:
                self._log(str(e), "err")
                messagebox.showerror("执行失败", str(e))
                return
            self._log(f"工作目录就绪：{work_dir}（已存在则复用）", "ok")

            # 2.2 提取并归档音频
            self._set_progress(30, "步骤 2.2 · 提取并归档音频")
            try:
                audio = core.download_audio(link, work_dir, title, self._log,
                                            headless=self.var_headless.get())
            except StepError as e:
                self._log(str(e), "err")
                messagebox.showerror("执行失败", str(e))
                return
            self._set_progress(75, "步骤 2.2 完成 · 音频已归档")
            self._log(f"音频归档完成：{audio}", "ok")

            # 2.3 生成提示词
            self._set_progress(85, "步骤 2.3 · 生成发布提示词")
            try:
                base_literal = str(docs_root).rstrip("\\/") or "C:\\Users\\ASUS\\Documents"
                prompt = core.render_prompt(title, copy_text, audio_dir_literal=base_literal)
            except Exception as e:
                self._log(f"生成提示词失败：{e}", "err")
                messagebox.showerror("执行失败", f"生成提示词失败：{e}")
                return
            self._log("模板变量替换完成（{{变量1}}→标题，{{变量2}}→口播文案）。", "ok")

            # 2.4 输出提示词
            self._set_progress(100, "全部完成")
            self._show_prompt(prompt)
            self._log("成品提示词已输出，可一键复制。", "ok")
        finally:
            self.running = False
            self.btn_start.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
