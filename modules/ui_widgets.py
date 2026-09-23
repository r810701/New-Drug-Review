# -*- coding: utf-8 -*-
"""
modules/ui_widgets.py
======================
自製的可愛載入動畫元件（Streamlit 本身沒有這類效果，用純 CSS + Emoji 手刻，
不依賴外部圖片/GIF，也不需要額外套件，避免部署環境沒網路時素材連結失效）。

seed_tree_indicator()：AI 產生單一主題內容時的等待動畫。四組 emoji 輪流出現
（熊科／海洋／遊樂園／樂團），依 group_index 依序輪替（不是隨機），
每按一次「產生」就換下一組，累積使用次數越多能看到的組合越多樣。
"""
from __future__ import annotations

ACCENT = "#A61E2B"
ACCENT_DARK = "#7d1620"

_SEED_EMOJI_GROUPS = [
    ["🐻", "🐻\u200d❄️", "🐼"],
    ["🐬", "🪸", "🪼"],
    ["🎠", "🎡", "🎪"],
    ["🥁", "🎸", "🎺"],
]


def seed_tree_indicator(label: str = "AI 讀取資料中...", group_index: int = 0) -> str:
    """
    三格循環淡入淡出（3 秒一輪），搭配文字說明。用在單一主題產生/重新產生時
    取代預設呆板的 spinner。group_index 決定這次用哪一組 emoji（依序輪替）。
    """
    emojis = _SEED_EMOJI_GROUPS[group_index % len(_SEED_EMOJI_GROUPS)]
    return f"""<div class="ndaw-seedtree-wrap">
<style>
.ndaw-seedtree-wrap {{
    display:flex; align-items:center; gap:10px;
    padding:10px 14px; border-radius:10px;
    background:#F7F3F3; border:1px solid #E3D6D7;
    font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
}}
.ndaw-seedtree-stage {{
    position:relative; width:28px; height:28px; flex-shrink:0;
}}
.ndaw-seedtree-stage span {{
    position:absolute; inset:0; font-size:22px; line-height:28px; text-align:center;
    opacity:0; transform:scale(0.6);
    animation: ndaw-seedcycle 3s ease-in-out infinite;
}}
.ndaw-seedtree-stage span:nth-child(1) {{ animation-delay: 0s; }}
.ndaw-seedtree-stage span:nth-child(2) {{ animation-delay: 1s; }}
.ndaw-seedtree-stage span:nth-child(3) {{ animation-delay: 2s; }}
@keyframes ndaw-seedcycle {{
    0% {{ opacity:0; transform:scale(0.5) translateY(4px); }}
    8% {{ opacity:1; transform:scale(1) translateY(0); }}
    28% {{ opacity:1; transform:scale(1) translateY(0); }}
    36% {{ opacity:0; transform:scale(1.15) translateY(-4px); }}
    100% {{ opacity:0; }}
}}
.ndaw-seedtree-text {{
    font-size:13.5px; color:{ACCENT_DARK}; font-weight:600;
}}
</style>
<div class="ndaw-seedtree-stage">
<span>{emojis[0]}</span><span>{emojis[1]}</span><span>{emojis[2]}</span>
</div>
<div class="ndaw-seedtree-text">{label}</div>
</div>""".strip()
