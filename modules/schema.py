# -*- coding: utf-8 -*-
"""
modules/schema.py
==================
集中定義專案中流動的資料結構（dataclasses），讓各模組之間傳遞的物件有明確型別，
IDE 補全與後續維護都比丟 dict 乾淨很多。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 知識庫（【新藥審查AI】資料夾）解析後的結構
# ---------------------------------------------------------------------------
@dataclass
class TopicSpec:
    """對應 Excel「主題架構規格」每一列"""
    topic_no: int
    max_pages: int
    slide_title_template: str
    ai_goal: str


@dataclass
class DecisionRule:
    """對應 Excel「決策邏輯與規則」每一列"""
    category: str
    item: str
    content: str


@dataclass
class DataSourceSpec:
    """對應 Excel「資料源」每一列"""
    topic_no: int
    slide_title: str
    sources_text: str


@dataclass
class VendorDoc:
    """對應 Excel「廠商文件」每一列"""
    seq: int
    doc_name: str


@dataclass
class ExampleSnippet:
    """從『語句描述文字檔.txt』或投影片 PDF 範例擷取出的 few-shot 教材片段"""
    category: str          # 例如：不須取代品項 / 需取代品項 / 建議比價
    subcategory: str       # 例如：NA/全新藥理機轉
    text: str
    source: str = "語句描述文字檔"


@dataclass
class KnowledgeBase:
    """整包知識庫載入後的物件，供 ai_engine / ppt_builder 使用"""
    topic_specs: list[TopicSpec] = field(default_factory=list)
    decision_rules: list[DecisionRule] = field(default_factory=list)
    data_sources: list[DataSourceSpec] = field(default_factory=list)
    vendor_docs: list[VendorDoc] = field(default_factory=list)
    example_snippets: list[ExampleSnippet] = field(default_factory=list)
    slide_example_texts: dict[str, str] = field(default_factory=dict)  # 檔名 -> 全文
    fingerprint: str = ""          # 知識庫檔案指紋（用於快取判斷／畫面顯示）
    loaded_at: datetime = field(default_factory=datetime.now)

    def topic(self, topic_no: int) -> Optional[TopicSpec]:
        for t in self.topic_specs:
            if t.topic_no == topic_no:
                return t
        return None

    def sources_for(self, topic_no: int) -> str:
        for s in self.data_sources:
            if s.topic_no == topic_no:
                return s.sources_text
        return ""

    def rules_text(self, category_filter: Optional[str] = None) -> str:
        rows = self.decision_rules
        if category_filter:
            rows = [r for r in rows if category_filter in r.category]
        return "\n".join(f"- [{r.category} / {r.item}] {r.content}" for r in rows)


# ---------------------------------------------------------------------------
# 藥品申請案 / 簡報內容
# ---------------------------------------------------------------------------
@dataclass
class DrugCase:
    """一個新藥申請案的基本資訊"""
    case_id: str                       # 案號，例如 "案15"
    trade_name_en: str = ""
    trade_name_zh: str = ""
    generic_name: str = ""
    strength: str = ""                 # 規格（劑量/含量/劑型）
    applicant_hospital: str = ""       # 提藥院區
    applicant_department: str = ""     # 提藥科別
    applicant_physician: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def slug(self) -> str:
        base = self.case_id.strip().replace(" ", "_")
        return base or "未命名案件"


@dataclass
class TopicContent:
    """單一主題（投影片）的內容，AI 生成後可被人工編輯，最後交給 ppt_builder 渲染"""
    topic_no: int
    title: str = ""
    # payload 是自由結構的 dict，因為每個主題的欄位不同（表格 / 條列 / 圖片路徑...）
    payload: dict[str, Any] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)   # 出處（含自動組裝的 PubMed/DOI 連結）
    ai_raw_response: str = ""
    is_ai_generated: bool = False
    is_human_edited: bool = False
    last_edited_by: str = ""
    last_edited_at: Optional[datetime] = None
    # 藥師審查時留的備註/待確認事項；純內部工作紀錄，不會出現在最終 pptx 投影片上，
    # 也不會因為「只重新產生這頁」被 AI 蓋掉（regen 時會沿用舊值）。
    reviewer_note: str = ""


@dataclass
class TenGridResult:
    """十宮格單一格子的判定結果"""
    item_index: int
    item_name: str
    light: str            # GREEN / YELLOW / RED / NA -> config.LIGHT_*
    rationale: str = ""   # 括號內的評級判斷論述
    is_human_overridden: bool = False


@dataclass
class Deck:
    """整份簡報：10 個主題內容 + 十宮格結果"""
    drug_case: DrugCase
    topics: dict[int, TopicContent] = field(default_factory=dict)
    ten_grid: list[TenGridResult] = field(default_factory=list)
    final_recommendation: str = ""   # 建議通過 / 建議比價 / 建議不通過
    summary_points: list[str] = field(default_factory=list)  # 綜合意見 3~4 點
    review_history_note: str = ""    # 歷年審議結果（年分/不通過原因）
