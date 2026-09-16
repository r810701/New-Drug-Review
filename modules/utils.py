# -*- coding: utf-8 -*-
"""
modules/utils.py
=================
共用小工具：檔案指紋（供快取失效判斷）、PubMed/DOI 連結組裝、
文字清理、JSON 安全解析等。不依賴 Streamlit，方便單元測試。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 檔案指紋：用來偵測「管理藥師是否更新過知識庫檔案」
# ---------------------------------------------------------------------------
def compute_dir_fingerprint(dir_path: Path, patterns: tuple[str, ...] = ("*",)) -> str:
    """
    對資料夾內符合 patterns 的檔案，依「檔名 + mtime + size」算出一組 sha256 指紋。
    只要管理藥師更新/覆蓋了任何一個知識庫檔案，這組指紋就會改變，
    可以作為 st.cache_data 的 cache key，達成「一鍵清快取 + 有更新才重算」的效果。
    """
    if not dir_path.exists():
        return "EMPTY"
    entries = []
    for pattern in patterns:
        for p in sorted(dir_path.rglob(pattern)):
            if p.is_file():
                stat = p.stat()
                entries.append(f"{p.relative_to(dir_path)}|{stat.st_mtime_ns}|{stat.st_size}")
    joined = "\n".join(entries)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# PubMed / DOI 連結組裝（對應 Excel 規則：「文獻查證與交付」）
# ---------------------------------------------------------------------------
def pubmed_url(pmid: str) -> str:
    pmid = pmid.strip()
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def doi_url(doi: str) -> str:
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return f"https://doi.org/{doi}"


def autolink_citation(raw: str) -> str:
    """
    輸入形如 'PMID: 42387275' 或 'DOI:10.1001/xxx' 的字串，
    回傳含完整跳轉網址的引用文字；辨識不出來就原樣回傳。
    """
    raw = raw.strip()
    m = re.search(r"PMID[:\s]*([0-9]{4,9})", raw, flags=re.IGNORECASE)
    if m:
        return f"{raw} → {pubmed_url(m.group(1))}"
    m = re.search(r"DOI[:\s]*(10\.\S+)", raw, flags=re.IGNORECASE)
    if m:
        return f"{raw} → {doi_url(m.group(1))}"
    return raw


# ---------------------------------------------------------------------------
# 文字/JSON 處理
# ---------------------------------------------------------------------------
def strip_code_fences(text: str) -> str:
    """去除 LLM 回覆中常見的 ```json ... ``` 包裹"""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def safe_json_loads(text: str) -> Optional[Any]:
    """盡量把 LLM 回覆解析成 JSON；失敗回傳 None（呼叫端要自行處理 fallback）"""
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 嘗試擷取第一個 { ... } 或 [ ... ] 區塊再解析一次
        m = re.search(r"(\{.*\}|\[.*\])", cleaned, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
        return None


def abbreviate_common_terms(text: str) -> str:
    """
    套用 Excel 規則「文字精簡規範 / 專有名詞縮寫原則」的常見對照表。
    這裡只放最常見、不會有歧義的縮寫；不確定的交給 AI 自行判斷，不強制取代。
    """
    mapping = {
        "JAK inhibitor": "JAKi",
        "SGLT2 inhibitor": "SGLT2i",
        "Rheumatoid Arthritis": "RA",
        "Ulcerative Colitis": "UC",
        "Crohn's disease": "CD",
        "Psoriatic Arthritis": "PsA",
        "Ankylosing Spondylitis": "AS",
    }
    for full, abbr in mapping.items():
        text = re.sub(re.escape(full), abbr, text, flags=re.IGNORECASE)
    return text


def truncate(text: str, n: int = 60) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------------------
# 使用者上傳檔案的文字擷取
# ---------------------------------------------------------------------------
# 修正紀錄：原本上傳區塊只把「檔名」丟進 AI 的 Prompt，AI 從未讀過檔案實際內容，
# 導致引用文獻/數據完全是模型憑訓練知識腦補（例如同一篇知名試驗被套用到不相關主題）。
# 這裡改成真的解析 PDF/文字檔內容，讓 AI 有真實文獻全文可以引用。
def extract_text_from_upload(path: Path, max_chars: int = 8000) -> str:
    """
    嘗試擷取上傳檔案的文字內容，供塞進 AI Prompt 使用。
    回傳值一定是「可以直接顯示給使用者看」的字串（含失敗/不支援時的說明），
    呼叫端不需要再另外判斷是否擷取成功。
    """
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import pypdf
        except ImportError:
            return "（系統尚未安裝 pypdf，無法解析此 PDF，請執行 `pip install pypdf`）"
        try:
            reader = pypdf.PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:  # noqa: BLE001
            return f"（PDF 解析失敗：{e}；此檔案內容 AI 無法讀取，請人工確認）"
    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix in (".png", ".jpg", ".jpeg"):
        return (
            "（圖片檔案：目前系統不會自動辨識圖片內文字，AI 無法讀取此檔案的實際內容；"
            "如有關鍵數據，請直接在下方文字欄位手動輸入摘要，否則 AI 只會憑一般知識作答）"
        )
    else:
        return f"（不支援自動擷取 .{suffix.lstrip('.')} 檔案的文字內容，AI 無法讀取此檔案）"

    text = text.strip()
    if not text:
        return "（此檔案擷取不到文字，可能是掃描影像型 PDF；AI 無法讀取實際內容，" \
               "請人工確認或手動輸入摘要，否則 AI 只會憑一般知識作答，可能與本篇文獻不符）"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...(內容過長已截斷，原文共 {len(text)} 字元，AI 僅看得到前 {max_chars} 字元)"
    return text
