"""生成真实联调用的图片素材（商品图、证据截图）。

用 bundled Python + Pillow 一次性生成，产物提交到 e2e_lifecycle/assets/；
harness 运行时不依赖 Pillow，只上传这些文件。用法：
    /Users/iy88/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3 make_assets.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
random.seed(20261029)

FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def font(size: int) -> ImageFont.FreeTypeFont:
    if size not in FONT_CACHE:
        FONT_CACHE[size] = ImageFont.truetype(FONT, size)
    return FONT_CACHE[size]


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def background(w: int, h: int, top, bottom) -> Image.Image:
    img = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=mix(top, bottom, y / max(1, h - 1)))
    return img


def vignette(img: Image.Image, strength: int = 70) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    for i in range(strength):
        alpha = int(255 * (1 - i / strength) * 0.12)
        d.rectangle([i, i, w - i, h - i], outline=alpha)
    dark = Image.new("RGB", (w, h), (20, 24, 22))
    return Image.composite(img, dark, mask.point(lambda v: 255 - v))


def label(img: Image.Image, text: str, sub: str | None = None, pos=None, color=(255, 255, 255)):
    d = ImageDraw.Draw(img)
    w, h = img.size
    x, y = pos or (48, h - 150)
    d.text((x, y), text, font=font(44), fill=color, stroke_width=2, stroke_fill=(20, 30, 25))
    if sub:
        d.text((x, y + 62), sub, font=font(26), fill=(236, 242, 238))
    return img


def product(textbook_style: str, title: str, sub: str, top, bottom, kind: str) -> Image.Image:
    img = background(900, 675, top, bottom)
    d = ImageDraw.Draw(img)
    # 场景：桌面背景 + 柔和光斑
    for _ in range(26):
        x = random.randint(-60, 960)
        y = random.randint(-40, 720)
        r = random.randint(30, 130)
        d.ellipse([x - r, y - r, x + r, y + r], fill=mix(top, (255, 255, 255), random.uniform(0.05, 0.16)))
    d.rectangle([0, 560, 900, 675], fill=mix(bottom, (30, 30, 30), 0.35))
    if kind == "book":
        d.rounded_rectangle([250, 90, 650, 620], radius=10, fill=(246, 243, 233), outline=(190, 185, 170), width=2)
        d.rectangle([250, 90, 300, 620], fill=(60, 92, 74))
        d.text((320, 150), "高等数学", font=font(58), fill=(52, 60, 55))
        d.text((320, 230), "第七版 · 上册", font=font(30), fill=(90, 100, 94))
        d.line([(330, 300), (600, 300)], fill=(150, 160, 150), width=2)
        for i in range(5):
            d.line([(330, 340 + i * 22), (590, 340 + i * 22)], fill=(170, 176, 170), width=1)
        d.text((320, 500), "同济大学数学系", font=font(24), fill=(110, 118, 112))
    elif kind == "keyboard":
        d.rounded_rectangle([120, 250, 780, 560], radius=18, fill=(38, 42, 48), outline=(90, 96, 104), width=3)
        for row in range(4):
            for col in range(14):
                x = 150 + col * 44
                y = 280 + row * 58
                d.rounded_rectangle([x, y, x + 36, y + 46], radius=6, fill=(58, 64, 72), outline=(120, 126, 134))
        d.rounded_rectangle([330, 512, 570, 548], radius=6, fill=(70, 76, 84), outline=(130, 136, 144))
    elif kind == "bike":
        d.ellipse([170, 350, 410, 590], outline=(60, 66, 62), width=14)
        d.ellipse([490, 350, 730, 590], outline=(60, 66, 62), width=14)
        d.line([(290, 470), (420, 250), (520, 250), (610, 470)], fill=(48, 82, 66), width=12)
        d.line([(290, 470), (440, 470)], fill=(48, 82, 66), width=10)
        d.line([(420, 250), (400, 200), (460, 200)], fill=(70, 74, 70), width=8)
        d.ellipse([420, 470, 470, 520], fill=(40, 44, 42))
    elif kind == "lamp":
        d.polygon([(430, 130), (600, 300), (260, 300)], fill=(250, 226, 140))
        d.rectangle([420, 300, 440, 520], fill=(70, 74, 72))
        d.rounded_rectangle([320, 520, 540, 560], radius=10, fill=(58, 62, 60))
        d.ellipse([250, 620, 850, 720], fill=(90, 80, 50))
    elif kind == "camera":
        d.rounded_rectangle([250, 240, 650, 520], radius=22, fill=(52, 56, 60), outline=(120, 126, 132), width=4)
        d.ellipse([360, 290, 540, 470], fill=(30, 34, 38), outline=(150, 156, 160), width=6)
        d.ellipse([410, 340, 490, 420], fill=(60, 90, 110))
        d.rounded_rectangle([430, 180, 520, 240], radius=8, fill=(70, 74, 80))
    elif kind == "racket":
        d.ellipse([220, 130, 520, 430], outline=(40, 60, 50), width=14)
        for i in range(-4, 5):
            d.line([(270 + i * 28, 170), (270 + i * 28, 400)], fill=(190, 196, 190), width=2)
            d.line([(260, 180 + i * 28), (490, 180 + i * 28)], fill=(190, 196, 190), width=2)
        d.line([(380, 430), (560, 600)], fill=(40, 60, 50), width=14)
        d.ellipse([300, 360, 700, 620], fill=(240, 244, 240))
    elif kind == "mug":
        d.rounded_rectangle([280, 200, 600, 520], radius=26, fill=(232, 236, 232), outline=(180, 188, 182), width=3)
        d.arc([540, 250, 720, 430], start=-80, end=80, fill=(200, 208, 202), width=18)
        d.rectangle([320, 320, 560, 380], fill=(47, 107, 79))
        d.text((352, 328), "CAMPUS", font=font(34), fill=(255, 255, 255))
    elif kind == "notes":
        d.rectangle([230, 80, 670, 640], fill=(250, 249, 242), outline=(200, 198, 188), width=2)
        for i in range(18):
            y = 130 + i * 26
            d.line([(280, y), (620 - (i % 4) * 40, y)], fill=(150, 156, 158), width=1)
        d.text((300, 100), "线性代数笔记", font=font(34), fill=(60, 64, 62))
        d.rectangle([230, 80, 262, 640], fill=(226, 92, 72))
    elif kind == "violation":
        d.rounded_rectangle([90, 160, 810, 620], radius=16, fill=(252, 250, 244), outline=(220, 180, 100), width=3)
        d.text((140, 200), "代写作业 论文辅导", font=font(52), fill=(190, 70, 40))
        d.text((140, 290), "包过 · 价格私聊 · 24小时在线", font=font(34), fill=(120, 80, 40))
        for i, line in enumerate(["课程作业代写", "毕业论文包过", "润色降重一条龙"]):
            d.text((150, 380 + i * 52), "· " + line, font=font(30), fill=(120, 110, 100))
        d.ellipse([640, 470, 780, 610], fill=(230, 80, 60))
        d.text((684, 512), "违规", font=font(34), fill=(255, 255, 255))
    img = vignette(img)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 520, 900, 675], fill=(20, 30, 25, 0))
    label(img, title, sub)
    return img


def evidence_scene(title: str, sub: str, kind: str) -> Image.Image:
    img = background(900, 1200, (238, 241, 238), (214, 222, 216))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 900, 96], fill=(30, 47, 40))
    d.text((36, 26), sub, font=font(30), fill=(236, 244, 238))
    if kind == "chat":
        # 模拟聊天截图（证据）
        y = 150
        bubbles = [
            ("买家", "你好，这个可以便宜点吗？", False),
            ("卖家", "可以，不过需要先付定金 50 元到我的个人账户", True),
            ("买家", "平台不是不支持站外付款吗……", False),
            ("卖家", "放心，先交定金，发货后再补尾款", True),
        ]
        for who, text, right in bubbles:
            bw = 560 if not right else 440
            x = 660 - bw if right else 60
            d.rounded_rectangle([x, y, x + bw, y + 110], radius=16, fill=(214, 232, 220) if right else (255, 255, 255))
            d.text((x + 24, y + 18), who, font=font(24), fill=(90, 100, 94))
            d.text((x + 24, y + 52), text, font=font(28), fill=(30, 40, 34))
            y += 140
        d.text((60, 780), "截图来源：交易分支消息（示意）", font=font(24), fill=(90, 100, 94))
    elif kind == "listing":
        d.rounded_rectangle([60, 150, 840, 800], radius=16, fill=(252, 251, 246), outline=(220, 214, 200), width=3)
        d.text((100, 190), "代写作业 论文辅导", font=font(44), fill=(170, 60, 40))
        d.text((100, 272), "价格：50.00 元", font=font(30), fill=(60, 64, 60))
        d.text((100, 330), "分类：无关服务或推广内容", font=font(28), fill=(110, 80, 60))
        d.multiline_text((100, 400), "课程作业代写\n毕业论文包过\n润色降重一条龙\n价格私聊，24小时在线", font=font(30), fill=(70, 74, 70), spacing=16)
        d.ellipse([610, 640, 790, 820], fill=(220, 70, 50))
        d.text((650, 690), "违规", font=font(38), fill=(255, 255, 255))
        d.text((100, 900), "截图来源：商品详情（示意）", font=font(24), fill=(90, 100, 94))
    else:
        d.text((70, 160), "证据说明", font=font(40), fill=(40, 52, 46))
        d.multiline_text((70, 240), title, font=font(30), fill=(60, 70, 64), spacing=20)
    return img


def main() -> None:
    items = [
        ("product_textbook.jpg", product("book", "高等数学教材（第七版）", "上册下册 · 九成新 · 无笔记", (206, 216, 208), (160, 176, 166), "book")),
        ("product_keyboard.jpg", product("keyboard", "机械键盘 87 键", "红轴 · 功能正常 · 附键帽", (196, 202, 210), (150, 158, 168), "keyboard")),
        ("product_bike.jpg", product("bike", "山地自行车", "骑了一学期 · 车况良好", (222, 218, 196), (172, 178, 152), "bike")),
        ("product_lamp.jpg", product("lamp", "护眼台灯与收纳盒", "宿舍闲置 · 暖光可调", (206, 210, 226), (150, 158, 178), "lamp")),
        ("product_camera.jpg", product("camera", "微单相机（二手）", "快门数少 · 含原装电池", (208, 212, 216), (154, 160, 168), "camera")),
        ("product_racket.jpg", product("racket", "羽毛球拍一对", "轻量碳素 · 送手胶", (206, 220, 206), (152, 180, 160), "racket")),
        ("product_mug.jpg", product("mug", "校园纪念马克杯", "全新未拆封", (218, 216, 210), (168, 160, 150), "mug")),
        ("product_notes.jpg", product("notes", "线性代数复习笔记", "手写整理 · 重点标注", (224, 220, 206), (176, 172, 154), "notes")),
        ("product_violation.jpg", product("violation", "代写作业与论文辅导", "明显与二手闲置交易无关", (228, 220, 200), (186, 170, 140), "violation")),
        ("product_second.jpg", product("book", "考研英语真题（近十年）", "答案完整 · 有少量标注", (214, 222, 214), (162, 180, 166), "notes")),
        ("product_second2.jpg", product("keyboard", "蓝牙机械键盘", "茶轴 · 附赠腕托", (198, 208, 216), (148, 160, 172), "keyboard")),
        ("evidence_chat.jpg", evidence_scene("", "交易分支消息截图", "chat")),
        ("evidence_listing.jpg", evidence_scene("", "商品详情截图", "listing")),
    ]
    for name, img in items:
        path = ASSETS / name
        img.save(path, "JPEG", quality=82, optimize=True)
        print(name, path.stat().st_size)
    print("done", len(items))


if __name__ == "__main__":
    main()
