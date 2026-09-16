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
# 使用者上傳檔案的文字擷取（支援 PDF / Word / Excel / CSV / 純文字）
# ---------------------------------------------------------------------------
# 修正紀錄：原本上傳區塊只把「檔名」丟進 AI 的 Prompt，AI 從未讀過檔案實際內容，
# 導致引用文獻/數據完全是模型憑訓練知識腦補（例如同一篇知名試驗被套用到不相關主題）。
# 這裡改成真的解析檔案內容，讓 AI 有真實文獻全文可以引用。
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTRACTABLE_EXTS = {".pdf", ".txt", ".md", ".docx", ".xlsx", ".csv"}


def _extract_pdf_text_full(path: Path) -> str:
    try:
        import pypdf
    except ImportError:
        return "（系統尚未安裝 pypdf，無法解析此 PDF，請執行 `pip install pypdf`）"
    try:
        reader = pypdf.PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:  # noqa: BLE001
        return f"（PDF 解析失敗：{e}；此檔案內容 AI 無法讀取，請人工確認）"


def _extract_docx_text(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        return "（系統尚未安裝 python-docx，無法解析 Word 檔，請執行 `pip install python-docx`）"
    try:
        doc = docx.Document(str(path))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells_text = " | ".join(c.text.strip() for c in row.cells)
                if cells_text.strip(" |"):
                    parts.append(cells_text)
        return "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        return f"（Word 檔解析失敗：{e}；此檔案內容 AI 無法讀取，請人工確認）"


def _extract_excel_text(path: Path) -> str:
    if path.suffix.lower() == ".xls":
        return "（不支援舊版 .xls 格式，請於 Excel 另存新檔為 .xlsx 後重新上傳）"
    try:
        import openpyxl
    except ImportError:
        return "（系統尚未安裝 openpyxl，無法解析 Excel 檔）"
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        lines = []
        for ws in wb.worksheets:
            lines.append(f"[工作表：{ws.title}]")
            row_count = 0
            for row in ws.iter_rows(values_only=True):
                if any(v is not None and str(v).strip() != "" for v in row):
                    lines.append(" | ".join("" if v is None else str(v) for v in row))
                    row_count += 1
                if row_count > 300:  # 避免超大檔案把 Prompt 塞爆
                    lines.append("...(此工作表列數過多，已截斷)")
                    break
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"（Excel 檔解析失敗：{e}；此檔案內容 AI 無法讀取，請人工確認）"


def extract_text_from_upload(path: Path, max_chars: int = 8000) -> str:
    """
    嘗試擷取上傳檔案的文字內容，供塞進 AI Prompt 使用。
    回傳值一定是「可以直接顯示給使用者看」的字串（含失敗/不支援時的說明），
    呼叫端不需要再另外判斷是否擷取成功。
    圖片檔不走這裡——圖片是直接以視覺方式交給 AI（見 encode_image_for_claude /
    load_image_for_gemini），文字擷取對圖片沒有意義。
    """
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        text = _extract_pdf_text_full(path)
    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".docx":
        text = _extract_docx_text(path)
    elif suffix in (".xlsx", ".xls"):
        text = _extract_excel_text(path)
    elif suffix == ".csv":
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix in IMAGE_EXTS:
        return "（圖片檔案：將以視覺方式直接提供給 AI 辨識，非文字擷取）"
    else:
        return f"（不支援自動擷取 .{suffix.lstrip('.')} 檔案的文字內容，AI 無法讀取此檔案）"

    # 上面幾個分支若本身回傳的是「說明字串」（例如解析失敗訊息），直接原樣回傳，不要再截斷判斷
    if text.startswith("（") and text.endswith("）"):
        return text

    text = text.strip()
    if not text:
        return "（此檔案擷取不到文字，可能是掃描影像型 PDF 或空白文件；AI 無法讀取實際內容，" \
               "請人工確認或手動輸入摘要，否則 AI 只會憑一般知識作答，可能與本篇文獻不符）"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...(內容過長已截斷，原文共 {len(text)} 字元，AI 僅看得到前 {max_chars} 字元)"
    return text


# ---------------------------------------------------------------------------
# 圖片檔案：以視覺（vision）方式直接交給 AI 辨識，而非文字擷取
# ---------------------------------------------------------------------------
_MEDIA_TYPE_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}


def encode_image_for_claude(path: Path, max_dimension: int = 1568) -> tuple[str, str]:
    """
    回傳 (base64字串, media_type)，供 Claude vision API 的 image content block 使用。
    有裝 Pillow 時會先等比例縮小到長邊 <= max_dimension（Anthropic 官方建議值，
    超過這個尺寸只會增加費用/延遲，不會提升辨識品質）並轉存為 JPEG 以縮小檔案；
    沒裝 Pillow 時退回直接讀取原始檔案 bytes（仍可運作，只是可能較大張、較貴）。
    """
    import base64

    try:
        from PIL import Image
        import io

        img = Image.open(path)
        img = img.convert("RGB")
        w, h = img.size
        scale = min(1.0, max_dimension / max(w, h))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
    except ImportError:
        data = path.read_bytes()
        media_type = _MEDIA_TYPE_BY_SUFFIX.get(path.suffix.lower(), "image/jpeg")
        return base64.b64encode(data).decode("ascii"), media_type


def load_image_for_gemini(path: Path, max_dimension: int = 1568):
    """回傳 PIL.Image 物件供 Gemini SDK 直接放進 generate_content([...]) 的內容列表；
    沒裝 Pillow 時回傳 None，呼叫端應略過該張圖片並提示使用者。
    同樣等比縮小到長邊 <= max_dimension，避免圖片過大浪費 token/費用。"""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        w, h = img.size
        scale = min(1.0, max_dimension / max(w, h))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        return img
    except ImportError:
        return None
