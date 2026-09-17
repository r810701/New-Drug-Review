# -*- coding: utf-8 -*-
"""
modules/data_loader.py
=======================
「新藥初審 AI 工作台」的大腦讀取器。

負責：
  1. 解析【新藥審查AI】資料夾內的 Excel（主題架構規格 / 決策邏輯與規則 / 資料源 / 廠商文件）
  2. 掃描標準教材庫（投影片範例 PDF/PPTX、語句描述文字檔）building few-shot 範例庫
  3. 提供「一鍵載入最新資料庫」：清除 Streamlit 快取＋依檔案指紋重新掃描
  4. 回傳統一的 KnowledgeBase 物件給 ai_engine / ppt_builder / app 使用

設計重點：所有「讀檔」函式都用 st.cache_data(hash_funcs / key 依 fingerprint) 包裝，
一般使用者操作不會重新掃描磁碟；只有 fingerprint 改變（檔案被更新）或按下
「🔄 載入最新資料庫」時才會真正重讀。
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl
import streamlit as st

import config
from modules.schema import (
    DataSourceSpec,
    DecisionRule,
    ExampleSnippet,
    KnowledgeBase,
    TopicSpec,
    VendorDoc,
)
from modules.utils import compute_dir_fingerprint

KB_FILE_PATTERNS = ("*.xlsx", "*.pptx", "*.pdf", "*.txt")


# ---------------------------------------------------------------------------
# Excel 解析
# ---------------------------------------------------------------------------
def _parse_topic_spec(ws) -> list[TopicSpec]:
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        try:
            topic_no = int(row[0])
        except (TypeError, ValueError):
            continue
        out.append(
            TopicSpec(
                topic_no=topic_no,
                max_pages=int(row[1]) if row[1] else 1,
                slide_title_template=str(row[2] or ""),
                ai_goal=str(row[3] or ""),
            )
        )
    return out


def _parse_decision_rules(ws) -> list[DecisionRule]:
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or all(v is None for v in row[:3]):
            continue
        out.append(
            DecisionRule(
                category=str(row[0] or ""),
                item=str(row[1] or ""),
                content=str(row[2] or ""),
            )
        )
    return out


def _parse_data_sources(ws) -> list[DataSourceSpec]:
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        try:
            topic_no = int(row[0])
        except (TypeError, ValueError):
            continue
        out.append(
            DataSourceSpec(
                topic_no=topic_no,
                slide_title=str(row[1] or ""),
                sources_text=str(row[2] or ""),
            )
        )
    return out


def _parse_vendor_docs(ws) -> list[VendorDoc]:
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        try:
            seq = int(row[0])
        except (TypeError, ValueError):
            continue
        out.append(VendorDoc(seq=seq, doc_name=str(row[1] or "")))
    return out


def parse_excel_module(excel_path: Path) -> tuple[list, list, list, list]:
    """讀取『新藥初審_AI_工作台模組.xlsx』四個工作表，回傳四個 list。"""
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    topics = _parse_topic_spec(wb[config.SHEET_TOPIC_SPEC])
    rules = _parse_decision_rules(wb[config.SHEET_DECISION_RULES])
    sources = _parse_data_sources(wb[config.SHEET_DATA_SOURCES])
    vendor_docs = _parse_vendor_docs(wb[config.SHEET_VENDOR_DOCS])
    return topics, rules, sources, vendor_docs


# ---------------------------------------------------------------------------
# 標準教材庫（few-shot 範例）掃描
# ---------------------------------------------------------------------------
# 語句描述文字檔.txt 是以「【分類】」區塊 + 「範例/範例1/範例2...」子區塊構成
_CATEGORY_HEADER_RE = re.compile(r"^【(.+?)】\s*$", re.MULTILINE)


def _split_example_text(raw_text: str) -> list[ExampleSnippet]:
    snippets: list[ExampleSnippet] = []

    # 先用兩個空行以上，切出大分類段落：不須取代品項 / 需取代品項 / 建議比價
    macro_blocks = re.split(r"\n{2,}(?=需取代品項|建議比價)", raw_text)
    # 若沒切成功（原始檔沒有明顯空行分隔），保底整份當一塊處理
    if len(macro_blocks) == 1:
        macro_blocks = [raw_text]

    current_macro = "不須取代品項"
    for block in macro_blocks:
        stripped = block.strip()
        if stripped.startswith("需取代品項"):
            current_macro = "需取代品項"
        elif stripped.startswith("建議比價"):
            current_macro = "建議比價"

        # 再依【子分類】切
        parts = _CATEGORY_HEADER_RE.split(block)
        if len(parts) > 1:
            # parts = [before, subcat1, text1, subcat2, text2, ...]
            it = iter(parts[1:])
            for subcat, body in zip(it, it):
                for ex_text in re.split(r"\n(?=範例\d*\s*\n)", body.strip()):
                    ex_text = ex_text.strip()
                    if ex_text:
                        snippets.append(
                            ExampleSnippet(
                                category=current_macro,
                                subcategory=subcat.strip(),
                                text=ex_text,
                            )
                        )
        else:
            body = block.strip()
            if body:
                for ex_text in re.split(r"\n(?=範例\d*\s*\n)", body):
                    ex_text = ex_text.strip()
                    if ex_text:
                        snippets.append(
                            ExampleSnippet(
                                category=current_macro,
                                subcategory="(未分類)",
                                text=ex_text,
                            )
                        )
    return snippets


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        import pypdf
    except ImportError:
        return ""
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def scan_example_corpus(kb_dir: Path) -> tuple[list[ExampleSnippet], dict[str, str]]:
    """
    掃描：
      - 語句描述文字檔.txt -> 依分類切出的 few-shot 範例句
      - 投影片範例*.pdf     -> 整份文字（作為 AI 產出「排版風格 / 論述語氣」的參考語料）
    """
    snippets: list[ExampleSnippet] = []
    text_path = kb_dir / config.EXAMPLE_TEXT_FILENAME
    if text_path.exists():
        raw = text_path.read_text(encoding="utf-8", errors="ignore")
        snippets = _split_example_text(raw)

    slide_texts: dict[str, str] = {}
    for pdf_path in sorted(kb_dir.glob(config.EXAMPLE_SLIDE_GLOB_PDF)):
        text = _extract_pdf_text(pdf_path)
        if text:
            slide_texts[pdf_path.name] = text

    return snippets, slide_texts


# ---------------------------------------------------------------------------
# 對外主入口：載入整包知識庫（含快取）
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_kb_cached(kb_dir_str: str, fingerprint: str) -> KnowledgeBase:
    """
    真正執行磁碟 I/O 的函式。cache key 是 (kb_dir, fingerprint)，
    只要 fingerprint 沒變，Streamlit 就不會重新執行本函式本體。
    """
    kb_dir = Path(kb_dir_str)
    excel_path = kb_dir / config.EXCEL_MODULE_FILENAME

    topics, rules, sources, vendor_docs = [], [], [], []
    if excel_path.exists():
        topics, rules, sources, vendor_docs = parse_excel_module(excel_path)

    snippets, slide_texts = scan_example_corpus(kb_dir)

    return KnowledgeBase(
        topic_specs=topics,
        decision_rules=rules,
        data_sources=sources,
        vendor_docs=vendor_docs,
        example_snippets=snippets,
        slide_example_texts=slide_texts,
        fingerprint=fingerprint,
    )


def load_knowledge_base(kb_dir: Path = config.KB_DIR) -> KnowledgeBase:
    """一般頁面呼叫這支：自動依檔案指紋決定要不要重讀。"""
    fingerprint = compute_dir_fingerprint(kb_dir, KB_FILE_PATTERNS)
    return _load_kb_cached(str(kb_dir), fingerprint)


def force_refresh_knowledge_base(kb_dir: Path = config.KB_DIR) -> KnowledgeBase:
    """
    對應畫面上的【🔄 載入最新資料庫】按鈕：
      1. 清掉本模組與 AI/PPT 模組可能用到的快取
      2. 重新計算指紋、重新掃描磁碟
      3. 回傳新的 KnowledgeBase，供 app.py 顯示「已載入 XX 篇範例、規則 XX 條」
    """
    st.cache_data.clear()
    st.cache_resource.clear()
    return load_knowledge_base(kb_dir)


def kb_status_summary(kb: KnowledgeBase) -> str:
    n_examples = len(kb.example_snippets)
    n_rules = len(kb.decision_rules)
    n_slide_pdfs = len(kb.slide_example_texts)
    n_topics = len(kb.topic_specs)
    return (
        f"✅ 已載入 {n_slide_pdfs} 份經典簡報範例、"
        f"語句範例 {n_examples} 則、決策規則 {n_rules} 條、"
        f"主題架構 {n_topics} 項（指紋碼：{kb.fingerprint}）"
    )


def kb_file_diagnostics(kb_dir: Path = config.KB_DIR) -> list[dict]:
    """
    列出【新藥審查AI】資料夾內每個關鍵檔案的「實際解析路徑、最後修改時間、檔案大小」。
    用途：當管理藥師覺得「明明改了 Excel，按了載入最新資料庫，內容卻還是舊的」，
    十之八九是編輯到了別份檔案（沒有真的存到 App 實際讀取的這個路徑）。
    這個列表讓人一眼就能比對「最後修改時間」跟自己剛剛存檔的時間對不對得上，
    不需要用猜的，也不用檔案指紋碼這種不好肉眼判讀的東西。
    """
    import datetime as _dt

    targets = [
        ("Excel 規則檔", kb_dir / config.EXCEL_MODULE_FILENAME),
        ("母片", kb_dir / config.MASTER_PPTX_FILENAME),
        ("語句範例文字檔", kb_dir / config.EXAMPLE_TEXT_FILENAME),
    ]
    rows = []
    for label, path in targets:
        if path.exists():
            stat = path.stat()
            rows.append({
                "項目": label,
                "實際讀取路徑": str(path.resolve()),
                "最後修改時間": _dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "檔案大小": f"{stat.st_size / 1024:.1f} KB",
            })
        else:
            rows.append({
                "項目": label, "實際讀取路徑": str(path.resolve()),
                "最後修改時間": "⚠️ 檔案不存在", "檔案大小": "-",
            })
    for pdf_path in sorted(kb_dir.glob(config.EXAMPLE_SLIDE_GLOB_PDF)):
        stat = pdf_path.stat()
        rows.append({
            "項目": f"範例PDF：{pdf_path.name}",
            "實際讀取路徑": str(pdf_path.resolve()),
            "最後修改時間": _dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "檔案大小": f"{stat.st_size / 1024:.1f} KB",
        })
    return rows
