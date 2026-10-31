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

