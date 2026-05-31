#!/usr/bin/env python3
"""
生成 NL2DSL Demo GIF —— 模拟终端查询效果

用法:
    python scripts/generate_demo_gif.py

输出:
    docs/demo.gif  — 完整动画
    docs/demo.png  — 静态首帧（README 兼容）

依赖:
    pip install Pillow
"""

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── 配置 ──────────────────────────────────────────────
WIDTH, HEIGHT = 900, 520
BG_COLOR = (13, 17, 23)  # GitHub dark bg
FG_COLOR = (201, 209, 217)  # 正文灰白
ACCENT = (47, 129, 247)  # 蓝色强调
GREEN = (35, 197, 94)  # 成功绿
YELLOW = (210, 153, 34)  # 处理中黄
RED = (248, 81, 73)  # 错误红
PURPLE = (188, 140, 255)  # SQL 紫

def find_font():
    """尝试找系统中文字体"""
    candidates = [
        # Windows
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    # fallback: PIL 默认
    return None

FONT_PATH = find_font()

def get_font(size):
    if FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()

FONT = get_font(15)
FONT_BOLD = get_font(16)
FONT_SMALL = get_font(13)
FONT_TITLE = get_font(18)

def hex_color(r, g, b, a=255):
    return (r, g, b, a)

# ── 绘制单帧 ──────────────────────────────────────────
def create_frame():
    img = Image.new("RGBA", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 终端顶部栏
    draw.rectangle((0, 0, WIDTH, 36), fill=(22, 27, 34))
    # 三个圆点
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        x = 18 + i * 20
        draw.ellipse([x, 13, x + 12, 25], fill=color)
    draw.text((55, 10), "NL2DSL Demo — zsh", font=FONT_SMALL, fill=(139, 148, 158))

    # 底部边框线
    draw.line([(0, 36), (WIDTH, 36)], fill=(48, 54, 61), width=1)

    return img, draw


def draw_prompt(img, draw, text, y_offset, cursor_visible=True):
    """绘制一行提示符文本"""
    prompt = "$ "
    x = 20
    draw.text((x, y_offset), prompt, font=FONT, fill=ACCENT)
    x += draw.textlength(prompt, font=FONT)
    draw.text((x, y_offset), text, font=FONT, fill=FG_COLOR)
    if cursor_visible:
        cursor_x = x + draw.textlength(text, font=FONT)
        draw.rectangle(
            (cursor_x + 1, y_offset, cursor_x + 9, y_offset + 18),
            fill=(201, 209, 217),
        )
    return img


def draw_line(draw, text, y, color=FG_COLOR, font=None, indent=0):
    """绘制普通文本行"""
    font = font or FONT
    x = 20 + indent
    draw.text((x, y), text, font=font, fill=color)


def draw_box(draw, text, y, color, prefix=""):
    """绘制带前缀的信息行"""
    x = 20
    if prefix:
        draw.text((x, y), prefix, font=FONT, fill=color)
        x += draw.textlength(prefix, font=FONT)
    draw.text((x, y), text, font=FONT, fill=FG_COLOR)


def draw_table(draw, headers, rows, y_start, col_widths):
    """绘制简单表格"""
    x_start = 20
    row_h = 28
    pad = 10

    # 表头背景
    draw.rectangle(
        (x_start, y_start, x_start + sum(col_widths) + pad * 2 * len(col_widths), y_start + row_h),
        fill=(33, 38, 45),
    )

    x = x_start + pad
    for i, h in enumerate(headers):
        draw.text((x, y_start + 5), h, font=FONT_BOLD, fill=FG_COLOR)
        x += col_widths[i] + pad * 2

    # 分隔线
    y_line = y_start + row_h
    draw.line(
        [(x_start, y_line), (x_start + sum(col_widths) + pad * 2 * len(col_widths), y_line)],
        fill=(48, 54, 61),
        width=1,
    )

    # 数据行
    for ri, row in enumerate(rows):
        y = y_line + 1 + ri * row_h
        x = x_start + pad
        for i, cell in enumerate(row):
            draw.text((x, y + 5), str(cell), font=FONT, fill=FG_COLOR)
            x += col_widths[i] + pad * 2


# ── 生成所有帧 ────────────────────────────────────────
def generate_frames():
    frames = []

    # 开场：空终端 + 光标闪烁（3帧）
    for _ in range(3):
        img, draw = create_frame()
        draw_prompt(img, draw, "", 50, cursor_visible=True)
        frames.append(img.convert("RGB"))

    # 打字效果：逐字输入查询
    query = "查询华东销售额最高的5个产品"
    for i in range(1, len(query) + 1):
        img, draw = create_frame()
        draw_prompt(img, draw, query[:i], 50, cursor_visible=(i % 2 == 0))
        frames.append(img.convert("RGB"))

    # 输入完成，回车（2帧）
    for _ in range(2):
        img, draw = create_frame()
        draw_prompt(img, draw, query, 50, cursor_visible=False)
        frames.append(img.convert("RGB"))

    # 阶段 1：思考中（带旋转 spinner）
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    stage1_lines = [
        ("正在理解查询意图...", YELLOW),
        ("识别实体: 华东地区, 销售额, 产品", GREEN),
        ("识别意图: single_query", GREEN),
    ]
    for si in range(len(stage1_lines) * 4 + 8):
        img, draw = create_frame()
        draw_prompt(img, draw, query, 50, cursor_visible=False)
        y = 85
        for li, (text, color) in enumerate(stage1_lines):
            frame_idx = si - li * 4
            if frame_idx >= 0:
                s = spinner[si % len(spinner)] if frame_idx < 8 and li == min(si // 4, len(stage1_lines) - 1) else "✓"
                prefix = f"{s} "
                draw_box(draw, text, y, color if s != "⠋" else YELLOW, prefix)
                y += 25
        frames.append(img.convert("RGB"))

    # 阶段 2：语义匹配
    stage2_lines = [
        ("语义层匹配...", YELLOW),
        ('"销售额" → metrics.sales_amount = SUM(pay_amount)', GREEN),
        ('"华东" → dimensions.region = \'HD\'', GREEN),
        ('"产品" → dimensions.product_name', GREEN),
    ]
    for si in range(len(stage2_lines) * 3 + 6):
        img, draw = create_frame()
        draw_prompt(img, draw, query, 50, cursor_visible=False)
        y = 85
        # 显示已完成的 stage1
        for text, color in stage1_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        for li, (text, color) in enumerate(stage2_lines):
            frame_idx = si - li * 3
            if frame_idx >= 0:
                s = spinner[si % len(spinner)] if frame_idx < 6 and li == min(si // 3, len(stage2_lines) - 1) else "✓"
                prefix = f"{s} "
                draw_box(draw, text, y, color if s == "✓" else YELLOW, prefix)
                y += 25
        frames.append(img.convert("RGB"))

    # 阶段 3：生成 DSL
    dsl_json = """{
  "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
  "dimensions": ["product_name", "region"],
  "filters": {
    "op": "and",
    "children": [
      {"field": "region", "operator": "=", "value": "华东"}
    ]
  },
  "order_by": [{"field": "sales_amount", "direction": "desc"}],
  "limit": 5,
  "data_source": "orders"
}"""
    dsl_lines = dsl_json.split("\n")

    for si in range(8):
        img, draw = create_frame()
        draw_prompt(img, draw, query, 50, cursor_visible=False)
        y = 85
        for text, color in stage1_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        for text, color in stage2_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        draw_box(draw, "生成 DSL...", y, YELLOW, f"{spinner[si % len(spinner)]} ")
        y += 25
        # 逐行显示 DSL
        for li, line in enumerate(dsl_lines):
            if si >= li + 2:
                draw_line(draw, line, y, PURPLE, FONT_SMALL, indent=20)
                y += 20
        frames.append(img.convert("RGB"))

    # 阶段 4：执行 SQL
    for si in range(6):
        img, draw = create_frame()
        draw_prompt(img, draw, query, 50, cursor_visible=False)
        y = 85
        for text, color in stage1_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        for text, color in stage2_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        draw_box(draw, "生成 DSL...", y, GREEN, "✓ ")
        y += 25
        for line in dsl_lines:
            draw_line(draw, line, y, PURPLE, FONT_SMALL, indent=20)
            y += 20
        y += 5
        draw_box(draw, "执行 SQL...", y, YELLOW, f"{spinner[si % len(spinner)]} ")
        y += 25
        sql_line = "SELECT product_name, SUM(pay_amount) ... FROM orders ..."
        if si >= 3:
            draw_line(draw, sql_line, y, (139, 148, 158), FONT_SMALL, indent=20)
        frames.append(img.convert("RGB"))

    # 阶段 5：安全扫描通过
    for si in range(4):
        img, draw = create_frame()
        draw_prompt(img, draw, query, 50, cursor_visible=False)
        y = 85
        for text, color in stage1_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        for text, color in stage2_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        draw_box(draw, "生成 DSL...", y, GREEN, "✓ ")
        y += 25
        for line in dsl_lines:
            draw_line(draw, line, y, PURPLE, FONT_SMALL, indent=20)
            y += 20
        y += 5
        draw_box(draw, "执行 SQL...", y, GREEN, "✓ ")
        y += 25
        draw_line(draw, "SELECT product_name, SUM(pay_amount) ...", y, (139, 148, 158), FONT_SMALL, indent=20)
        y += 25
        scan_text = "安全扫描: 通过 | 权限检查: 通过"
        draw_box(draw, scan_text, y, GREEN, "✓ ")
        frames.append(img.convert("RGB"))

    # 阶段 6：返回结果表格
    headers = ["排名", "产品名称", "地区", "销售额"]
    rows = [
        ["1", "iPhone 15 Pro", "华东", "¥2,450,000"],
        ["2", "Mate 60 Pro", "华东", "¥1,890,000"],
        ["3", "MacBook Air M3", "华东", "¥1,560,000"],
        ["4", "iPad Pro", "华东", "¥980,000"],
        ["5", "AirPods Pro", "华东", "¥720,000"],
    ]
    col_widths = [50, 180, 80, 130]

    for si in range(6):
        img, draw = create_frame()
        draw_prompt(img, draw, query, 50, cursor_visible=False)
        y = 85
        for text, color in stage1_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        for text, color in stage2_lines:
            draw_box(draw, text, y, color, "✓ ")
            y += 25
        y += 5
        draw_box(draw, "生成 DSL...", y, GREEN, "✓ ")
        y += 25
        for line in dsl_lines[:4]:
            draw_line(draw, line, y, PURPLE, FONT_SMALL, indent=20)
            y += 20
        y += 5
        draw_box(draw, "执行 SQL...", y, GREEN, "✓ ")
        y += 25
        draw_line(draw, "SELECT product_name, SUM(pay_amount) ...", y, (139, 148, 158), FONT_SMALL, indent=20)
        y += 25
        draw_box(draw, "安全扫描: 通过 | 权限检查: 通过", y, GREEN, "✓ ")
        y += 30

        if si >= 2:
            draw_line(draw, "查询结果:", y, FG_COLOR, FONT_BOLD)
            y += 25
        if si >= 3:
            draw_table(draw, headers, rows[: min(si - 1, 5)], y, col_widths)

        frames.append(img.convert("RGB"))

    # 最终帧：停留久一点
    final_frame = frames[-1]
    for _ in range(15):
        frames.append(final_frame)

    return frames


# ── 主程序 ────────────────────────────────────────────
def main():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("请先安装 Pillow: pip install Pillow")
        sys.exit(1)

    # 确保 docs 目录存在
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)

    gif_path = docs_dir / "demo.gif"
    png_path = docs_dir / "demo.png"

    print("[Generate] Generating demo frames...")
    frames = generate_frames()
    print(f"   Total: {len(frames)} frames")

    print(f"[Save] GIF: {gif_path}")
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=80,  # ms per frame
        loop=0,
        optimize=True,
    )

    # 同时保存静态首帧
    print(f"[Save] PNG: {png_path}")
    frames[-1].save(png_path, "PNG")

    # 计算文件大小
    gif_size = gif_path.stat().st_size / 1024
    png_size = png_path.stat().st_size / 1024
    print(f"\n[Done] Complete!")
    print(f"   demo.gif: {gif_size:.1f} KB")
    print(f"   demo.png: {png_size:.1f} KB")
    print(f"\n[Usage] Add to README:")
    print(f'   ![Demo](docs/demo.gif)')


if __name__ == "__main__":
    main()
