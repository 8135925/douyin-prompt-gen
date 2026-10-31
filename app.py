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
from tkinter import filedialog, messagebox, ttk

import core
from core import StepError

APP_TITLE = "抖音口播视频一键生成小工具"
COPY_MAX = 50000        # 硬限制：阻止提交
COPY_WARN = 20000       # 软限制：超出提示
BG = "#f5f7fa"
CARD_BG = "#ffffff"
ACCENT = "#4f6ef2"

# ===== 测试阶段默认值（正式使用时删除这三行即可恢复空白输入框）=====
DEFAULT_TITLE = "测试"
DEFAULT_LINK = ("8.28 复制打开抖音，看看【木读精进史的作品】真正的学习，从第四遍才开始，"
                "反复的梳理，是对知识的... https://v.douyin.com/nZz3COvjqoI/ u@s.eo SYz:/ :0pm 06/25")
DEFAULT_COPY = "测试文案"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("880x760")
        self.minsize(780, 640)
        self.configure(bg=BG)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False

        self._build_ui()
        self._on_copy_modified(None)  # 同步默认文案的字数显示
        self.after(100, self._poll_log_queue)

    # ---------- UI ----------
    def _card(self, master, title):
        frame = tk.LabelFrame(master, text=f" {title} ", bg=CARD_BG, fg="#333",
                              font=("Microsoft YaHei UI", 10, "bold"),
                              bd=0, highlightthickness=1, highlightbackground="#e3e6ee")
        frame.pack(fill="x", padx=14, pady=(10, 0))
        inner = tk.Frame(frame, bg=CARD_BG)
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        return inner

    def _build_ui(self):
        # 顶部说明
        top = tk.Frame(self, bg=ACCENT)
        top.pack(fill="x")
        tk.Label(top, text=APP_TITLE, bg=ACCENT, fg="white",
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=16, pady=10)

        # Step1 信息采集
        s1 = self._card(self, "Step 1 · 信息采集")
        s1.columnconfigure(1, weight=1)

        # 测试阶段默认值（正式使用时可删除 DEFAULT_* 常量）
        self.entry_title = tk.Entry(s1, font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
        self.entry_title.insert(0, DEFAULT_TITLE)
        self.entry_title.grid(row=0, column=1, sticky="ew", pady=4, padx=(6, 0))

        tk.Label(s1, text="抖音链接：", bg=CARD_BG, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_link = tk.Entry(s1, font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
        self.entry_link.insert(0, DEFAULT_LINK)
        self.entry_link.grid(row=1, column=1, sticky="ew", pady=4, padx=(6, 0))

        tk.Label(s1, text="口播文案：", bg=CARD_BG, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="nw", pady=4)
        copy_frame = tk.Frame(s1, bg=CARD_BG)
        copy_frame.grid(row=2, column=1, sticky="ew", pady=4, padx=(6, 0))
        self.txt_copy = tk.Text(copy_frame, height=6, font=("Microsoft YaHei UI", 10),
                                relief="solid", bd=1, wrap="word", undo=True)
        self.txt_copy.insert("1.0", DEFAULT_COPY)
        self.txt_copy.pack(fill="both", expand=True)
        self.txt_copy.bind("<<Modified>>", self._on_copy_modified)
        self.lbl_copy_count = tk.Label(copy_frame, text="0 / 50000", bg=CARD_BG, fg="#888",
                                       font=("Microsoft YaHei UI", 8), anchor="e")
        self.lbl_copy_count.pack(fill="x")

        # 文档根目录设置
        tk.Label(s1, text="文档根目录：", bg=CARD_BG, font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, sticky="w", pady=(10, 2))
        dir_frame = tk.Frame(s1, bg=CARD_BG)
        dir_frame.grid(row=3, column=1, sticky="ew", pady=(10, 2), padx=(6, 0))
        default_root = os.path.join(os.path.expanduser("~"), "Documents")
        self.var_docs_root = tk.StringVar(value=default_root)
        tk.Entry(dir_frame, textvariable=self.var_docs_root, font=("Microsoft YaHei UI", 9),
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=2)
        tk.Button(dir_frame, text="浏览…", command=self._browse_root,
                  font=("Microsoft YaHei UI", 9), relief="groove").pack(side="left", padx=(6, 0))

        # 开始按钮
        btn_row = tk.Frame(s1, bg=CARD_BG)
        btn_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.var_headless = tk.BooleanVar(value=False)
        tk.Checkbutton(btn_row, text="隐藏浏览器窗口（无头模式，失败时可关闭重试）",
                       variable=self.var_headless, bg=CARD_BG,
                       font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x")
        self.btn_start = tk.Button(btn_row, text="▶  开始（一键执行）", command=self._on_start,
                                   bg=ACCENT, fg="white", activebackground="#3d5be0", activeforeground="white",
                                   font=("Microsoft YaHei UI", 11, "bold"), relief="flat", padx=22, pady=6,
                                   cursor="hand2")
        self.btn_start.pack()

        # Step2 进度与日志
        s2 = self._card(self, "Step 2 · 自动化执行进度")
        self.lbl_step = tk.Label(s2, text="待开始 · 2.1 创建目录 → 2.2 归档音频 → 2.3 生成提示词 → 2.4 输出",
                                 bg=CARD_BG, fg="#555", font=("Microsoft YaHei UI", 9), anchor="w")
        self.lbl_step.pack(fill="x")
        self.progress = ttk.Progressbar(s2, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=8)

        self.txt_log = tk.Text(s2, height=10, bg="#1e1e2e", fg="#cdd6f4", font=("Consolas", 9),
                               relief="solid", bd=1, wrap="word", state="disabled")
        self.txt_log.pack(fill="both", expand=True)
        self.txt_log.tag_config("warn", foreground="#f9e2af")
        self.txt_log.tag_config("err", foreground="#f38ba8")
        self.txt_log.tag_config("ok", foreground="#a6e3a1")

        # Step3 成品提示词
        s3 = self._card(self, "Step 3 · 成品提示词（可一键复制）")
        head = tk.Frame(s3, bg=CARD_BG)
        head.pack(fill="x")
        self.lbl_result = tk.Label(head, text="等待生成…", bg=CARD_BG, fg="#888",
                                   font=("Microsoft YaHei UI", 9), anchor="w")
        self.lbl_result.pack(side="left")
        self.btn_copy = tk.Button(head, text="复制全部", command=self._on_copy, state="disabled",
                                  bg="#22a06b", fg="white", activebackground="#1b8558", activeforeground="white",
                                  font=("Microsoft YaHei UI", 9, "bold"), relief="flat", padx=14,
                                  cursor="hand2")
        self.btn_copy.pack(side="right")
        self.txt_prompt = tk.Text(s3, height=9, font=("Microsoft YaHei UI", 10),
                                  relief="solid", bd=1, wrap="word", state="disabled")
        self.txt_prompt.pack(fill="both", expand=True, pady=(6, 0))

    # ---------- 交互 ----------
    def _browse_root(self):
        d = filedialog.askdirectory(title="选择文档根目录")
        if d:
            self.var_docs_root.set(d)

    def _on_copy_modified(self, event):
        self.txt_copy.edit_modified(False)
        n = len(self.txt_copy.get("1.0", "end-1c"))
        color = "#d13438" if n > COPY_MAX else ("#b8860b" if n > COPY_WARN else "#888")
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

    def _show_prompt(self, text):
        self.txt_prompt.config(state="normal")
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.insert("1.0", text)
        self.txt_prompt.config(state="disabled")
        self.btn_copy.config(state="normal")
        self.lbl_result.config(text=f"已生成（{len(text)} 字符）", fg="#22a06b")

    def _on_copy(self):
        text = self.txt_prompt.get("1.0", "end-1c").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_result.config(text="已复制到剪贴板 ✓", fg="#22a06b")
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
        self.lbl_result.config(text="生成中…", fg="#888")
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
            self._set_progress(100, "全部完成 ✓")
            self._show_prompt(prompt)
            self._log("成品提示词已输出，可一键复制。", "ok")
        finally:
            self.running = False
            self.btn_start.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
