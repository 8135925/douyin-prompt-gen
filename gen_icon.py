# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico：墨色圆角方块 + 白色『抖』字 + 陶土色装饰点。"""
from PIL import Image, ImageDraw, ImageFont

INK = (31, 29, 26, 255)        # #1f1d1a
ACCENT = (181, 101, 69, 255)   # #b56545
WHITE = (244, 242, 238, 255)   # #f4f2ee

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 墨色圆角底
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=INK)

# 陶土色装饰：右上角小圆 + 左下短横线
d.ellipse([S - 66, 26, S - 34, 58], fill=ACCENT)
d.rounded_rectangle([36, S - 60, 108, S - 48], radius=6, fill=ACCENT)

# 白色『抖』字
font = None
for fp in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
           r"C:\Windows\Fonts\simhei.ttf"):
    try:
        font = ImageFont.truetype(fp, 150)
        break
    except OSError:
        continue
if font is None:
    raise SystemExit("未找到系统中文字体")

bbox = d.textbbox((0, 0), "抖", font=font)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((S - w) / 2 - bbox[0], (S - h) / 2 - bbox[1] - 8), "抖", font=font, fill=WHITE)

# 多尺寸 ico
img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save("icon.png")
print("icon.ico / icon.png 已生成")
