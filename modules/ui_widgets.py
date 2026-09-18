# -*- coding: utf-8 -*-
"""
modules/ui_widgets.py
======================
自製的可愛載入動畫元件（Streamlit 本身沒有這類效果，用純 CSS + Emoji 手刻，
不依賴外部圖片/GIF，也不需要額外套件，避免部署環境沒網路時素材連結失效）。

設計原則：
  - 全部用純 CSS keyframes 動畫（transform / opacity），不用會被某些瀏覽器
    擋掉的實驗性屬性（例如動畫 content 屬性），確保院內舊版瀏覽器也看得到。
  - 每個函式回傳「完整的一段 HTML 字串」（含自己的 <style>），呼叫端直接
    `st.markdown(html, unsafe_allow_html=True)` 丟進 st.empty() placeholder 即可，
    不需要额外掛載 JS，重繪也不會有殘影/沒清乾淨的問題。
  - 顏色沿用 config 定義的品牌色（棗紅 #A61E2B），視覺上跟主體介面一致，
    不會有「動畫另外長一個樣子」的違和感。

兩個元件對應的使用情境：
  1. seed_tree_indicator()：取代掉「AI 讀取單一主題資料」時預設呆板的轉圈圈，
     用於單一主題「只重新產生這頁」按鈕觸發後的等待畫面。
  2. dog_digging_progress()：取代「一鍵產生全份簡報」原本的純數字進度條，
     小狗在草地上隨進度往右移動並刨土，走到終點後叼骨頭搖尾巴慶祝完成。
"""
from __future__ import annotations

ACCENT = "#A61E2B"
ACCENT_DARK = "#7d1620"


def seed_tree_indicator(label: str = "AI 讀取資料中...") -> str:
    """
    種子 → 幼苗 → 大樹，三格循環淡入淡出（3 秒一輪），搭配文字說明。
    用在單一主題重新生成時取代預設 spinner。
    """
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
<span>🌱</span><span>🌿</span><span>🌳</span>
</div>
<div class="ndaw-seedtree-text">{label}</div>
</div>""".strip()


def dog_digging_progress(percent: float, status_text: str = "") -> str:
    """
    percent: 0~100。
    < 100：小狗蹲在草地土堆上輕輕刨土，並隨進度在草地上往右移動，泥屑不斷往後飛濺。
    >= 100：小狗走到草地最右側，叼著一根大骨頭，開心搖尾巴。
    status_text：下方的文字說明（例如「已完成主題 4/10」）。
    不顯示額外的數字進度條——狗狗在草地上的位置本身就是進度指示。
    """
    percent = max(0.0, min(100.0, percent))
    done = percent >= 100

    track_start, track_end = 9.0, 87.0
    dog_left = track_end if done else track_start + (track_end - track_start) * (percent / 100.0)

    if done:
        scene = """<div class="ndaw-dog-body"></div>
<div class="ndaw-dog-emoji ndaw-dog-happy">🐶</div>
<div class="ndaw-bone">🦴</div>""".strip()
        status_text = status_text or "🎉 全部完成！"
    else:
        dirt_particles = "".join(
            f'<span class="ndaw-dirt ndaw-dirt-{i}"></span>' for i in range(1, 6)
        )
        scene = f"""<div class="ndaw-dog-body"></div>
<div class="ndaw-dog-emoji ndaw-dog-dig">🐶</div>
{dirt_particles}""".strip()

    return f"""<div class="ndaw-dog-wrap">
<style>
.ndaw-dog-wrap {{
    font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
    background:#F7F3F3; border:1px solid #E3D6D7; border-radius:12px;
    padding:14px 16px 12px; margin:6px 0 10px;
}}
.ndaw-dog-scene {{
    position:relative; height:60px; overflow:hidden;
}}
.ndaw-dog-mover {{
    position:absolute; bottom:0; left:{dog_left:.1f}%;
    transform:translateX(-50%);
    transition:left .4s ease;
}}
.ndaw-dog-body {{
    position:absolute; left:calc(50% - 19px); bottom:8px;
    width:38px; height:24px; border-radius:52% 52% 46% 46%;
    background:
        radial-gradient(circle at 30% 25%, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 30%),
        radial-gradient(circle at 70% 70%, rgba(120,70,15,0.25) 0%, rgba(120,70,15,0) 35%),
        linear-gradient(165deg, #E8B45E 0%, #C9822E 55%, #B06F24 100%);
    box-shadow:
        inset -4px -5px 5px rgba(110,62,10,0.4),
        inset 3px 3px 5px rgba(255,240,210,0.55),
        0 2px 3px rgba(0,0,0,0.12);
}}
.ndaw-dog-body::before {{
    content:""; position:absolute; left:50%; bottom:2px; transform:translateX(-50%);
    width:16px; height:10px; border-radius:50%;
    background:linear-gradient(180deg,#F5DDB0,#E8C589);
    opacity:0.9;
}}
.ndaw-dog-body::after {{
    content:""; position:absolute; left:-3px; bottom:-1px;
    width:8px; height:6px; border-radius:50%;
    background:#B06F24;
    box-shadow:26px 0 0 #B06F24;
    opacity:0.85;
}}
.ndaw-dog-emoji {{
    position:absolute; left:calc(50% - 18px); bottom:10px;
    font-size:28px; line-height:1; display:inline-block;
    transform-origin:bottom center;
}}
.ndaw-dog-dig {{ animation: ndaw-digbounce 0.5s ease-in-out infinite alternate; }}
@keyframes ndaw-digbounce {{
    0%   {{ transform: translateY(0) scale(1,1) rotate(-2deg); }}
    50%  {{ transform: translateY(3px) scale(1.04,0.94) rotate(0deg); }}
    100% {{ transform: translateY(0) scale(1,1) rotate(2deg); }}
}}
.ndaw-dog-happy {{ animation: ndaw-wag 0.5s ease-in-out infinite; transform-origin:bottom center; }}
@keyframes ndaw-wag {{
    0% {{ transform: rotate(-8deg); }}
    50% {{ transform: rotate(8deg); }}
    100% {{ transform: rotate(-8deg); }}
}}
.ndaw-bone {{
    position:absolute; left:calc(50% + 10px); bottom:20px; font-size:18px;
    animation: ndaw-bonebounce 1.1s ease-in-out infinite;
}}
@keyframes ndaw-bonebounce {{
    0%,100% {{ transform: translateY(0) rotate(-10deg); }}
    50% {{ transform: translateY(-3px) rotate(10deg); }}
}}
.ndaw-ground {{
    position:absolute; left:0; right:0; bottom:0; height:12px;
}}
.ndaw-ground::before {{
    content:""; position:absolute; left:6%; right:6%; top:0; height:4px;
    background:linear-gradient(90deg,#8FBF6B,#6FA34F);
    border-radius:3px 3px 0 0;
}}
.ndaw-ground::after {{
    content:""; position:absolute; left:6%; right:6%; top:4px; height:8px;
    background:linear-gradient(90deg,#B98E63,#9C6B3E);
    border-radius:0 0 3px 3px; opacity:0.75;
}}
.ndaw-dirt {{
    position:absolute; bottom:16px; left:calc(50% - 4px);
    width:6px; height:6px; border-radius:50%;
    background:#9C6B3E; opacity:0;
    animation: ndaw-fly 0.9s ease-out infinite;
}}
.ndaw-dirt-1 {{ animation-delay:0.00s; }}
.ndaw-dirt-2 {{ animation-delay:0.15s; }}
.ndaw-dirt-3 {{ animation-delay:0.30s; }}
.ndaw-dirt-4 {{ animation-delay:0.45s; }}
.ndaw-dirt-5 {{ animation-delay:0.60s; }}
@keyframes ndaw-fly {{
    0% {{ opacity:0; transform:translate(0,0) scale(0.6); }}
    15% {{ opacity:1; }}
    100% {{ opacity:0; transform:translate(-24px,-26px) scale(1); }}
}}
.ndaw-dog-status {{
    margin-top:6px; font-size:12.5px; color:{ACCENT_DARK}; font-weight:600; text-align:center;
}}
</style>
<div class="ndaw-dog-scene"><div class="ndaw-ground"></div><div class="ndaw-dog-mover">{scene}</div></div>
<div class="ndaw-dog-status">{status_text}</div>
</div>""".strip()
