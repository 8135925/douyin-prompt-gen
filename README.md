# douyin-prompt-gen
抖音提示词生成1

## 功能
输入「标题 / 抖音链接（自动提取短链）/ 口播文案」，一键完成：
1. 在文档根目录（可配置）下创建以标题命名的工作目录
2. 浏览器自动化打开 `https://vidgap.com/douyin/audio/cn`，粘贴短链并下载音频，重命名为 `标题.mp3` 归档
3. 用模板生成发布提示词并支持一键复制

带进度条（2.1～2.4 步骤）与实时日志面板，异常（短链无效、站点超时/改版、无写入权限、非法文件名字符）均有提示。

## 运行
```powershell
pip install -r requirements.txt
playwright install chromium
python app.py
```

## 图标与打包成 exe
```powershell
pip install pillow pyinstaller
python gen_icon.py          # 生成 icon.ico（墨色圆角 + 白色"抖"字）
python -m PyInstaller --noconsole --onefile --icon=icon.ico --collect-all playwright --name DouyinPromptGen app.py
```
生成物在 `dist\DouyinPromptGen.exe`，双击即可运行。

注意：
- 打包只包含程序本体，不含 Chromium 内核。目标电脑需执行过 `playwright install chromium`（本机已装则无需处理）。
- 若在未装内核的电脑提示浏览器启动失败，运行 `pip install playwright && playwright install chromium` 后再打开 exe 即可。

