"""Render the illustrative README GIF. Optional dependency: Pillow.

Run from the repository root: python -m scripts.render_readme_animation
Pass --font and --bold-font for non-Windows Traditional Chinese fonts.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.timetable_guard import query_trains


ROOT = Path(__file__).resolve().parents[1]
BG = '#f3f6fa'
INK = '#182d48'
MUTED = '#52657b'
BLUE = '#3478b8'
PURPLE = '#8051a8'
LINE = '#dbe4ef'


def render(font_path, bold_path):
    result = query_trains('A1', 'A13', '2026-09-22T10:00:00+08:00', '普通車')
    if result['status'] != 'ok' or len(result['next_trains']) < 2:
        raise ValueError('The documented example requires two verified departures.')
    departures = [train['departure'][11:16] for train in result['next_trains'][:2]]
    fonts = {}

    def font(size, bold=False):
        key = size, bold
        if key not in fonts:
            fonts[key] = ImageFont.truetype(str(bold_path if bold else font_path), size)
        return fonts[key]

    titles = ['選擇旅程', '交給已訓練模型', '核對班表資料', '查看下一班']
    subtitles = ['起訖站、車種與時間，一次選好。',
                 'Qwen 載入本專案的 LoRA 訓練成果。',
                 '程式保留表單條件，查詢符合停靠規則的班次。',
                 '以班表為依據，顯示最近兩班預定發車時間。']
    step_labels = ['選站', '模型處理', '班表核對', '顯示結果']
    frames = []
    for stage in range(4):
        frame = Image.new('RGB', (1000, 630), BG)
        draw = ImageDraw.Draw(frame)

        def label(x, y, text, size=18, color=INK, bold=False):
            draw.text((x, y), text, font=font(size, bold), fill=color)

        def box(bounds, fill='white', outline=None, radius=16):
            draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=outline, width=1)

        def centered(bounds, text, size=18, color=INK, bold=False):
            x1, y1, x2, y2 = bounds
            draw.text(((x1 + x2) / 2, (y1 + y2) / 2), text,
                      font=font(size, bold), fill=color, anchor='mm')

        draw.rectangle((0, 0, 1000, 7), fill=BLUE)
        draw.rectangle((645, 0, 1000, 7), fill=PURPLE)
        label(38, 26, '下一站 / 機捷助手', 23, bold=True)
        label(715, 31, '操作流程示意 · 非實際錄影', 17, MUTED)
        label(38, 78, f'0{stage + 1}  {titles[stage]}', 34, bold=True)
        label(40, 130, subtitles[stage], 20, MUTED)

        box((38, 187, 599, 462))
        label(62, 209, '您的查詢', 16, MUTED)
        box((62, 246, 275, 339), '#eaf3fc')
        box((347, 246, 574, 339), '#f2ebf8')
        label(80, 259, 'A1', 25, BLUE, True)
        label(80, 299, '台北車站', 21, bold=True)
        centered((279, 246, 344, 339), '→', 34, MUTED)
        label(365, 259, 'A13', 25, PURPLE, True)
        label(365, 299, '第二航廈', 21, bold=True)
        box((62, 361, 172, 401), BLUE, radius=10)
        centered((62, 361, 172, 401), '普通車', 19, 'white', True)
        label(190, 368, '2026-09-22   10:00', 23, bold=True)
        label(63, 422, '臺灣時間 UTC+8  ·  保留 3 分鐘乘車緩衝', 16, MUTED)

        box((619, 187, 962, 462))
        if stage == 0:
            label(643, 211, '查詢條件', 16, MUTED)
            label(643, 256, '台北車站到第二航廈', 24, bold=True)
            label(643, 295, '下一班普通車幾點？', 24, bold=True)
            box((643, 360, 938, 419), BLUE, radius=12)
            centered((643, 360, 938, 419), '查詢班次  →', 22, 'white', True)
        elif stage == 1:
            label(643, 211, '已訓練模型', 16, MUTED)
            label(643, 252, 'Qwen3 4B + LoRA', 26, bold=True)
            label(643, 301, '收到明確的站碼與時間', 21)
            label(643, 339, '保留「普通車」條件', 21)
            box((643, 396, 938, 433), '#f2ebf8', radius=9)
            centered((643, 396, 938, 433), '本機執行 · 原始輸出可追查', 17, PURPLE)
        elif stage == 2:
            label(643, 211, '程式查表與核對', 16, MUTED)
            for index, content in enumerate(['A1 → A13，方向正確', '普通車，停靠目的站', '平日班表與乘車緩衝']):
                y = 260 + index * 49
                box((643, y, 669, y + 26), '#eaf3fc', radius=7)
                draw.line([(649, y + 13), (654, y + 18), (663, y + 8)], fill=BLUE, width=3)
                label(681, y - 1, content, 19)
            label(643, 420, '發車時間由資料核對後產生', 17, MUTED)
        else:
            label(643, 211, '最近兩班 · 預定發車', 16, MUTED)
            for index, departure in enumerate(departures):
                y = 248 + index * 79
                box((643, y, 938, y + 67), '#eaf3fc', radius=12)
                label(659, y + 8, departure, 34, BLUE, True)
                label(820, y + 23, '普通車', 21, BLUE, True)
            label(643, 420, '可到 A13 第二航廈 · 不需換車', 17, MUTED)

        for index, content in enumerate(step_labels):
            left = 38 + index * 238
            active = index == stage
            box((left, 495, left + 210, 549), BLUE if active else 'white', LINE, 12)
            centered((left, 495, left + 210, 549), f'{index + 1}  {content}',
                     20, 'white' if active else MUTED, active)
        label(39, 585, '示例日期固定為 2026-09-22。此為預定時刻，非即時列車資訊。', 16, MUTED)
        frames.append(frame)

    destination = ROOT / 'docs/assets'
    destination.mkdir(parents=True, exist_ok=True)
    frames[-1].save(destination / 'query-flow-poster.png')
    frames[0].save(destination / 'query-flow.gif', save_all=True, append_images=frames[1:],
                   duration=[2400, 2200, 2600, 4200], loop=0, disposal=2, optimize=False)
    print(f'Created {destination / "query-flow.gif"}; verified times: {", ".join(departures)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', type=Path, default=Path('C:/Windows/Fonts/msjh.ttc'))
    parser.add_argument('--bold-font', type=Path, default=Path('C:/Windows/Fonts/msjhbd.ttc'))
    args = parser.parse_args()
    render(args.font, args.bold_font)


if __name__ == '__main__':
    main()
