# -*- coding: utf-8 -*-
"""
modules/structured_data.py
============================
主題 1、2、9 的「0 Token」內容產生器：完全不呼叫任何 LLM，直接把結構化資料
（案件基本資料 / 廠商申請表 / Google 表單回覆）逐欄對應寫入 payload。
"""
from __future__ import annotations

import csv
import io
from typing import Optional

import config
from modules.schema import DrugCase

# ---------------------------------------------------------------------------
# CSV 解析
# ---------------------------------------------------------------------------

def _find_header_row_index(rows: list[list[str]], min_nonempty: int = 3) -> int:
    """
    有些Excel/表單在正式表頭上方，會多一列「季度/年度」之類的標題列
    （例如「115.Q1」單獨佔第一列，其餘欄位空白），如果直接把第一列當表頭，
    真正的欄位名稱（例如「學名」）就會被誤判成不存在，導致篩選/匯入失敗。
    這裡自動往下找「第一個看起來像正常表頭」的列（非空欄位數夠多），
    跳過前面的標題列。
    """
    for i, row in enumerate(rows):
        nonempty = sum(1 for c in row if (c or "").strip())
        if nonempty >= min_nonempty:
            return i
    return 0


def parse_csv_text(csv_text: str) -> list[dict[str, str]]:
    """把 CSV 文字轉成 list[dict]（欄位名 -> 該列的值）。
    會自動偵測、跳過表頭上方可能存在的標題列，只做「去除頭尾空白」，
    不做任何摘要/改寫/翻譯——確保逐字對應。"""
    all_rows = list(csv.reader(io.StringIO(csv_text)))
    if not all_rows:
        return []
    header_idx = _find_header_row_index(all_rows)
    header = [(h or "").strip() for h in all_rows[header_idx]]
    rows = []
    for raw in all_rows[header_idx + 1:]:
        if not any((c or "").strip() for c in raw):
            continue
        rows.append({
            header[i]: (raw[i].strip() if i < len(raw) and raw[i] else "")
            for i in range(len(header))
        })
    return rows


def parse_csv_two_row_header(csv_text: str) -> list[dict[str, str]]:
    """
    給像主題9這種「兩列式標題、按院區分組」的Google表單使用：
    第一列是院區名稱（合併儲存格匯出成CSV後，只有該組第一欄有值，
    其餘欄位是空字串）；第二列才是各院區底下的子欄位名稱
    （負責藥師、LASA品項、臨床意見）。這裡把兩列合併成單一複合欄名
    （例如「附醫_臨床意見」），之後就能沿用一般的 dict 列表流程。
    """
    reader = csv.reader(io.StringIO(csv_text))
    all_rows = list(reader)
    if len(all_rows) < 3:
        return []
    header1, header2 = all_rows[0], all_rows[1]
    filled1, last = [], ""
    for h in header1:
        h = (h or "").strip()
        if h:
            last = h
        filled1.append(last)
    n_cols = max(len(header1), len(header2))
    compound = []
    for i in range(n_cols):
        group = filled1[i] if i < len(filled1) else ""
        sub = (header2[i] or "").strip() if i < len(header2) else ""
        compound.append(f"{group}_{sub}" if sub else group)
    rows = []
    for raw in all_rows[2:]:
        if not any((c or "").strip() for c in raw):
            continue
        rows.append({compound[i]: (raw[i].strip() if i < len(raw) and raw[i] else "")
                     for i in range(len(compound))})
    return rows


def filter_rows(rows: list[dict], filter_col: str, filter_val: str) -> list[dict]:
    """篩選出某欄位包含指定文字的列。"""
    if not filter_col or not filter_val:
        return rows
    needle = filter_val.strip().lower()
    return [r for r in rows if needle in str(r.get(filter_col, "")).strip().lower()]


def detect_columns(rows: list[dict]) -> list[str]:
    """回傳偵測到的欄位名稱。"""
    if not rows:
        return []
    return list(rows[0].keys())

# ---------------------------------------------------------------------------
# 主題 1：封面
# ---------------------------------------------------------------------------

def build_topic1_payload(drug_case: DrugCase) -> dict:
    return {
        "trade_name_en": drug_case.trade_name_en,
        "trade_name_zh": drug_case.trade_name_zh,
        "generic_name": drug_case.generic_name,
        "photo_notes": "外盒、鋁箔袋/內包裝、針劑本體或裸錠正反面（含尺規），等比縮放排列於下半部",
    }

# ---------------------------------------------------------------------------
# 主題 2：申請總表
# ---------------------------------------------------------------------------

def build_topic2_payload(row: dict[str, str], column_map: dict[str, str]) -> dict:
    def get(field: str) -> str:
        col = column_map.get(field, "")
        return row.get(col, "") if col else ""

    replace_raw = get("replace_candidates")
    similar_raw = get("similar_drugs")
    reason_raw = get("application_reason")

    trade_name = get("trade_name")
    generic_name = get("generic_name")
    # 使用者要求「藥名(學名)」那格同時顯示商品名，一眼就能看出是哪個品牌的藥；
    # 商品名跟學名一樣時（或商品名沒填）就不重複顯示。
    if trade_name and generic_name and trade_name != generic_name:
        display_name = f"{trade_name}（{generic_name}）"
    else:
        display_name = trade_name or generic_name

    return {
        "generic_name": display_name,
        "strength_form": get("strength_form"),
        "moa": get("moa"),
        "nhi_price": get("nhi_price"),
        "needs_replace": get("needs_replace"),
        "replace_candidates": [s.strip() for s in replace_raw.replace("\n", "、").split("、") if s.strip()],
        "similar_drugs": [s.strip() for s in similar_raw.replace("\n", "、").split("、") if s.strip()],
        "indication": get("indication"),
        "application_reason": [s.strip() for s in reason_raw.split("\n") if s.strip()],
        "applicant_physician": get("applicant_physician"),
    }

# ---------------------------------------------------------------------------
# 主題 9：臨床使用意見
# ---------------------------------------------------------------------------

def build_topic9_payload(
    rows: list[dict[str, str]],
    column_map: dict[str, str],
    drug_case: Optional[DrugCase] = None,
    topic2_payload: Optional[dict] = None,
) -> dict:
    sites = [column_map.get(k, "").strip() for k in ("site_1", "site_2", "site_3")]
    sites = [s for s in sites if s]
    name_suffix = column_map.get("pharmacist_name_suffix", "負責藥師")
    lasa_suffix = column_map.get("lasa_suffix", "LASA")
    opinion_suffix = column_map.get("opinion_suffix", "臨床意見")

    def _find(row: dict, site: str, suffix_keyword: str) -> str:
        prefix = f"{site}_"
        for col, val in row.items():
            if col.startswith(prefix) and suffix_keyword in col:
                return (val or "").strip()
        return ""

    site_opinions = []
    for row in rows:
        for site in sites:
            pharmacist_name = _find(row, site, name_suffix)
            lasa = _find(row, site, lasa_suffix)
            opinion = _find(row, site, opinion_suffix)
            if not pharmacist_name and not opinion:
                continue
            parts = []
            if pharmacist_name:
                parts.append(f"【負責藥師】{pharmacist_name}")
            if lasa:
                parts.append(f"【LASA品項】{lasa}")
            if opinion:
                parts.append(f"【臨床意見】{opinion}")
            site_opinions.append({
                "site": site,
                "physician_opinion": config.TOPIC9_DEFAULT_PHYSICIAN_OPINION,
                "pharmacist_opinion": "\n".join(parts),
                "pharmacist_name": pharmacist_name,
            })

    info_box = {"main_department": drug_case.applicant_department if drug_case else ""}
    if topic2_payload:
        info_box["applied_drug"] = topic2_payload.get("generic_name", "") or (
            drug_case.generic_name if drug_case else ""
        )
        info_box["replace_drug"] = topic2_payload.get("needs_replace", "")
        info_box["similar_drug"] = "、".join(topic2_payload.get("similar_drugs", []) or [])
    elif drug_case:
        info_box["applied_drug"] = drug_case.generic_name

    return {"info_box": info_box, "site_opinions": site_opinions}
