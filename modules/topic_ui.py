# -*- coding: utf-8 -*-
"""
modules/topic_ui.py
=====================
把 TopicContent.payload（AI 生成的結構化 JSON）轉成：
1. render_slide_preview_html()：模擬 PowerPoint 投影片外觀的「視覺化預覽卡片」
2. render_editable_form()：不需要碰 JSON/大括號的表單編輯介面

設計理念（重要，關係到好不好維護）：
10 個主題的 payload 結構彼此差異很大（主題3是幾句摘要文字，主題8是表格，
主題10是十宮格清單...），如果為每個主題各寫一份客製表單，未來 Excel
「主題架構規格」的 AI 代工目標一改欄位，程式就要跟著改 10 次。

這裡改用「通用欄位解析」：走訪 payload 的每個 key，依值的型別
（純文字 / 文字清單 / 物件清單 / 巢狀物件）自動選擇合適的元件：
- 純文字，短 → st.text_input；長/含換行 → st.text_area
- 文字清單（如條列式申請理由）→ 一行一則的 st.text_area
- 物件清單（如指引比較表、HTA 表、試驗數據列）→ st.data_editor
  （這是 Streamlit 內建的「試算表式」編輯器，可直接加列/刪列/改欄位，
  使用者操作起來像 Excel，完全不會碰到 JSON 語法）
- 巢狀物件（如臨床意見的資訊盒）→ 遞迴套用同一套規則

這樣不管 Excel 以後怎麼調整欄位，這裡都不需要跟著改。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

ACCENT = "#A61E2B"
ACCENT_DARK = "#7d1620"

# 常見技術欄位名稱 → 藥師看得懂的中文標籤（找不到就用 humanize_key 的通用規則退回）
FIELD_LABELS: dict[str, str] = {
    "trade_name_en": "英文商品名/規格", "trade_name_zh": "中文商品名", "generic_name": "學名",
    "photo_notes": "建議照片說明", "strength_form": "劑量/劑型", "moa": "作用機轉",
    "nhi_price": "健保價/藥價", "needs_replace": "須取代藥品", "replace_candidates": "暫定取代藥品",
    "similar_drugs": "同類藥品", "indication": "衛福部核准適應症", "application_reason": "申請理由",
    "applicant_physician": "提藥醫師", "moa_summary": "機轉重點摘要", "moa_diagram_desc": "建議機轉圖說明",
    "citation": "文獻出處", "guideline_rows": "各國/學會治療指引地位", "summary": "重點總結",
    "trials": "試驗數據", "trial_name": "試驗名稱", "design": "試驗設計", "population": "收案族群",
    "regimen": "治療處方", "key_results": "主要療效結果", "conclusion_box": "結論摘要",
    "adr_table": "不良反應比較", "hta_rows": "各國醫療科技評估", "note_if_missing": "查無資料時的說明",
    "columns": "比較欄位名稱", "rows": "比較項目", "info_box": "藥品資訊盒",
    "site_opinions": "各院區臨床意見", "applied_drug": "申請藥品", "replace_drug": "暫定取代藥品",
    "similar_drug": "同類藥品", "main_department": "主要開立科別", "physician_opinion": "醫師意見",
    "pharmacist_opinion": "藥師意見", "ten_grid": "十宮格評估", "high_alert": "高警訊藥品註記",
    "is_high_alert": "是否為高警訊藥品", "note": "備註", "lasa": "外觀/名稱相似品項",
    "review_history_note": "歷年審議結果", "summary_points": "綜合意見", "final_recommendation": "最終建議",
    "country_or_society": "學會/國家", "year": "年份", "treatment_line": "治療順位",
    "drug_examples": "代表藥品", "agency": "機構", "verdict": "評估結論", "key_findings": "重點發現",
    "field": "比較項目", "values": "各欄位數值", "endpoint": "療效指標", "value_a": "藥品A數值",
    "value_b": "藥品B數值", "p_value": "統計p值", "category": "項目", "drug_a": "藥品A",
    "drug_b": "藥品B", "site": "院區", "item_index": "項目序號", "light": "燈號",
    "rationale": "判斷論述",
}

# 這些欄位不會出現在編輯表單（內部用/由其他機制管理）
_HIDDEN_KEYS = {"_generation_error", "raw_text_fallback", "bold_advantage_idx"}


def humanize_key(key: str) -> str:
    return FIELD_LABELS.get(key, key.replace("_", " ").strip().capitalize())


def _is_list_of_str(v: Any) -> bool:
    return isinstance(v, list) and (len(v) == 0 or all(isinstance(x, (str, int, float)) for x in v))


def _is_list_of_dict(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(isinstance(x, dict) for x in v)


# ---------------------------------------------------------------------------
# 1. 視覺化投影片預覽卡片
# ---------------------------------------------------------------------------

def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_value_html(key: str, value: Any, depth: int = 0) -> str:
    label = humanize_key(key)
    indent = "margin-left:%dpx;" % (depth * 14)

    if value is None or value == "" or value == []:
        return ""

    if isinstance(value, (str, int, float, bool)):
        return f'<p style="{indent}margin:4px 0;"><b>{_esc(label)}：</b>{_esc(value)}</p>'

    if _is_list_of_str(value):
        items = "".join(f"<li>{_esc(v)}</li>" for v in value if str(v).strip())
        if not items:
            return ""
        return (
            f'<div style="{indent}margin:6px 0;"><b>{_esc(label)}：</b>'
            f'<ul style="margin:4px 0 4px 18px; padding:0;">{items}</ul></div>'
        )

    if _is_list_of_dict(value):
        cols = []
        for row in value:
            for k in row.keys():
                if k not in cols and k not in _HIDDEN_KEYS:
                    cols.append(k)
        head = "".join(f"<th>{_esc(humanize_key(c))}</th>" for c in cols)
        body_rows = []
        for row in value:
            cells = "".join(
                f"<td>{_esc(', '.join(map(str, row.get(c))) if isinstance(row.get(c), list) else row.get(c, ''))}</td>"
                for c in cols
            )
            body_rows.append(f"<tr>{cells}</tr>")
        return (
            f'<div style="{indent}margin:8px 0;"><b>{_esc(label)}：</b>'
            f'<table class="ndaw-slide-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table></div>'
        )

    if isinstance(value, dict):
        inner = "".join(
            _render_value_html(k, v, depth + 1) for k, v in value.items() if k not in _HIDDEN_KEYS
        )
        if not inner:
            return ""
        return f'<div style="{indent}margin:6px 0;"><b>{_esc(label)}：</b>{inner}</div>'

    return ""


def render_slide_preview_html(topic_no: int, title: str, payload: dict) -> str:
    """回傳完整 HTML（含 <style>），呈現成一張模擬 PPT 的 16:9 卡片。"""
    if isinstance(payload, list):
        # AI 有時會把整份結果直接輸出成清單（常見於一次比較 3 種以上藥品時），
        # 而不是包在字典裡，這裡轉換成統一格式，避免 payload.items() 直接當機。
        payload = {"rows": payload}
    body_parts = [
        _render_value_html(k, v) for k, v in payload.items() if k not in _HIDDEN_KEYS
    ]
    body_html = "".join(p for p in body_parts if p)

    if not body_html:
        body_html = (
            '<div class="ndaw-slide-empty">📭 尚無資料，請點擊上方「產生」按鈕讓 AI 生成內容，'
            "或直接在下方表單手動填寫。</div>"
        )

    return f"""<div class="ndaw-slide-outer">
<style>
.ndaw-slide-outer {{ margin-bottom:10px; }}
.ndaw-slide-card {{
    min-height:160px; background:#fff; border-radius:14px;
    box-shadow:0 2px 12px rgba(0,0,0,.10); border:1px solid #e6e0e0;
    display:flex; flex-direction:column; overflow:hidden;
    font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
}}
.ndaw-slide-topbar {{
    background:linear-gradient(90deg,{ACCENT},{ACCENT_DARK}); color:#fff;
    padding:10px 20px; font-weight:700; font-size:15px; flex-shrink:0;
}}
.ndaw-slide-body {{
    padding:12px 22px; max-height:420px; overflow-y:auto; font-size:12.5px; color:#2a2a2a; flex:1; line-height:1.5;
}}
.ndaw-slide-empty {{
    color:#999; font-size:13px; text-align:center; margin-top:30px; padding:0 20px;
}}
.ndaw-slide-table {{ border-collapse:collapse; width:100%; margin-top:4px; font-size:11.5px; }}
.ndaw-slide-table th, .ndaw-slide-table td {{
    border:1px solid #e6e0e0; padding:4px 7px; text-align:left; vertical-align:top;
}}
.ndaw-slide-table th {{ background:#F7F3F3; color:{ACCENT_DARK}; }}
</style>
<div class="ndaw-slide-card">
<div class="ndaw-slide-topbar">主題 {topic_no}：{_esc(title)}</div>
<div class="ndaw-slide-body">{body_html}</div>
</div>
</div>""".strip()


# ---------------------------------------------------------------------------
# 2. 人性化表單編輯（不碰 JSON）
# ---------------------------------------------------------------------------

def _edit_scalar(key: str, value: Any, key_prefix: str) -> Any:
    label = humanize_key(key)
    text = "" if value is None else str(value)
    if len(text) > 50 or "\n" in text:
        return st.text_area(label, value=text, key=f"{key_prefix}_{key}", height=90)
    return st.text_input(label, value=text, key=f"{key_prefix}_{key}")


def _edit_list_of_str(key: str, value: list, key_prefix: str) -> list[str]:
    label = humanize_key(key)
    text = "\n".join(str(v) for v in value)
    raw = st.text_area(f"{label}（每行一則）", value=text, key=f"{key_prefix}_{key}", height=110)
    return [line.strip() for line in raw.split("\n") if line.strip()]


def _edit_list_of_dict(key: str, value: list[dict], key_prefix: str) -> list[dict]:
    label = humanize_key(key)
    df = pd.DataFrame(value)
    st.caption(f"**{label}**（可直接點欄位修改內容，右下角 ➕ 可新增列、勾選列後按 Delete 可刪除）")
    edited = st.data_editor(
        df, key=f"{key_prefix}_{key}", num_rows="dynamic", use_container_width=True, hide_index=True,
    )
    records = edited.to_dict(orient="records")

    # data_editor 空列會補 NaN，清掉整列都是空值的殘留列。
    # 注意：欄位值本身可能是 list（例如「代表藥品」不只一個），對 list 呼叫 pd.isna()
    # 會回傳逐元素比較的陣列而不是單一 True/False，要先排除掉才不會炸。
    def _is_na(v: Any) -> bool:
        if isinstance(v, (list, dict, tuple)):
            return False
        try:
            return bool(pd.isna(v))
        except (TypeError, ValueError):
            return False

    cleaned = []
    for r in records:
        r = {k: ("" if _is_na(v) else v) for k, v in r.items()}
        if any(str(v).strip() for v in r.values()):
            cleaned.append(r)
    return cleaned


def _edit_dict(key: str, value: dict, key_prefix: str) -> dict:
    label = humanize_key(key)
    st.markdown(f"**{label}**")
    new_value = {}
    for k, v in value.items():
        if k in _HIDDEN_KEYS:
            new_value[k] = v
            continue
        new_value[k] = _edit_field(k, v, f"{key_prefix}_{key}")
    return new_value


def _edit_field(key: str, value: Any, key_prefix: str) -> Any:
    if _is_list_of_dict(value):
        return _edit_list_of_dict(key, value, key_prefix)
    if _is_list_of_str(value):
        return _edit_list_of_str(key, value, key_prefix)
    if isinstance(value, dict):
        return _edit_dict(key, value, key_prefix)
    return _edit_scalar(key, value, key_prefix)


def render_editable_form(topic_no: int, payload: dict, key_prefix: str) -> dict:
    """
    依 payload 現有欄位畫出對應表單元件，回傳「目前表單上的值」組成的新 payload
    （呼叫端要在按下『套用修改』時才把回傳值寫回 content.payload 並存檔，
    避免使用者只是打字打到一半、還沒按套用就被當成正式內容）。
    """
    if isinstance(payload, list):
        payload = {"rows": payload}
    if not payload or set(payload.keys()) <= _HIDDEN_KEYS:
        st.caption("目前沒有可編輯的欄位，請先產生內容，或使用最下方「進階：新增欄位」。")
        return dict(payload)

    new_payload = {}
    for key, value in payload.items():
        if key in _HIDDEN_KEYS:
            new_payload[key] = value
            continue
        new_payload[key] = _edit_field(key, value, key_prefix)
    return new_payload
