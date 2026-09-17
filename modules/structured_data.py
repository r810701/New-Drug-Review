# -*- coding: utf-8 -*-
"""
modules/structured_data.py
============================
主題 1、2、9 的「0 Token」內容產生器：完全不呼叫任何 LLM，直接把結構化資料
（案件基本資料 / 廠商申請表 / Google 表單回覆）逐欄對應寫入 payload。

為什麼需要這個模組（別跟 ai_engine.py 混在一起）：
  這幾個主題的內容本質是「照抄」而不是「統整」，交給 LLM 處理有兩個問題：
    1. 花 token/額度，測試時很容易卡住（本院實際遇過 Gemini 免費額度用盡）。
    2. 語言模型不管 Prompt 寫得多嚴格，都有「順一下語句」的傾向，
       無法保證逐字不動——這對「Google 表單填了什麼就該長什麼樣」的
       臨床意見類內容是不可接受的（藥師簽過名的意見被 AI 換句話說）。
  這裡的函式全部是純字串/字典操作，輸出可以做到「輸入什麼、就長什麼樣」，
  100% 可預期、可重現、免費。
"""
from __future__ import annotations

import csv
import io
from typing import Optional

import config
from modules.schema import DrugCase


# ---------------------------------------------------------------------------
# CSV 解析（來源通常是 utils.fetch_url_content() 把 Google 試算表轉出的 CSV 文字）
# ---------------------------------------------------------------------------
def parse_csv_text(csv_text: str) -> list[dict[str, str]]:
    """把 CSV 文字轉成 list[dict]（欄位名 -> 該列的值）。
    只做「去除頭尾空白」，不做任何摘要/改寫/翻譯——確保逐字對應。"""
    f = io.StringIO(csv_text)
    reader = csv.DictReader(f)
    rows = []
    for row in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def filter_rows(rows: list[dict], filter_col: str, filter_val: str) -> list[dict]:
    """篩選出某欄位包含指定文字的列（用於一份共用表單裡篩出屬於這個案件的列）。
    filter_col 或 filter_val 空白就不篩選，回傳全部列。"""
    if not filter_col or not filter_val:
        return rows
    needle = filter_val.strip().lower()
    return [r for r in rows if needle in str(r.get(filter_col, "")).strip().lower()]


def detect_columns(rows: list[dict]) -> list[str]:
    """回傳偵測到的欄位名稱（供畫面上顯示，讓使用者核對欄位對應設定對不對）。"""
    if not rows:
        return []
    return list(rows[0].keys())


# ---------------------------------------------------------------------------
# 主題 1：封面（不需要任何外部資料源，案件建立時就已經有了）
# ---------------------------------------------------------------------------
def build_topic1_payload(drug_case: DrugCase) -> dict:
    return {
        "trade_name_en": drug_case.trade_name_en,
        "trade_name_zh": drug_case.trade_name_zh,
        "generic_name": drug_case.generic_name,
        "photo_notes": "外盒、鋁箔袋/內包裝、針劑本體或裸錠正反面（含尺規），等比縮放排列於下半部",
    }


# ---------------------------------------------------------------------------
# 主題 2：申請總表（來源：廠商/醫師填寫的新進藥品申請表，逐欄對應）
# ---------------------------------------------------------------------------
def build_topic2_payload(row: dict[str, str], column_map: dict[str, str]) -> dict:
    def get(field: str) -> str:
        col = column_map.get(field, "")
        return row.get(col, "") if col else ""

    replace_raw = get("replace_candidates")
    similar_raw = get("similar_drugs")
    reason_raw = get("application_reason")

    return {
        "generic_name": get("generic_name"),
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
# 主題 9：臨床使用意見（來源：各院區藥師填寫的 Google 表單，逐字照登）
# ---------------------------------------------------------------------------
def build_topic9_payload(
    rows: list[dict[str, str]],
    column_map: dict[str, str],
    drug_case: Optional[DrugCase] = None,
    topic2_payload: Optional[dict] = None,
    default_physician_opinion: str = config.TOPIC9_DEFAULT_PHYSICIAN_OPINION,
) -> dict:
    site_col = column_map.get("site", "")
    name_col = column_map.get("pharmacist_name", "")
    opinion_col = column_map.get("pharmacist_opinion", "")
    physician_col = column_map.get("physician_opinion", "")

    site_opinions = []
    for row in rows:
        site = row.get(site_col, "").strip() if site_col else ""
        # 藥師意見：完全照 Google 表單原文寫入，不做任何摘要/改寫/刪減
        opinion = row.get(opinion_col, "") if opinion_col else ""
        physician_opinion = (row.get(physician_col, "").strip() if physician_col else "") or default_physician_opinion
        pharmacist_name = row.get(name_col, "").strip() if name_col else ""

        if not site and not opinion:
            continue  # 整列空白（例如篩選後殘留的表頭列）就跳過

        site_opinions.append({
            "site": site,
            "physician_opinion": physician_opinion,
            "pharmacist_opinion": opinion,
            "pharmacist_name": pharmacist_name,  # 保留供追溯/核對，ppt 表格目前不需要這欄
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
