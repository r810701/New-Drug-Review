
# -*- coding: utf-8 -*-
"""
config.py
=========
新藥初審 AI 工作台 - 全域設定檔。

所有「路徑、檔名、可調參數」都集中在這裡，其他模組一律 `from config import ...`，
避免路徑/檔名字串散落在各處造成日後維護困難。
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. 核心資料夾路徑
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
KB_DIR = Path(os.environ.get("NEWDRUG_KB_DIR", BASE_DIR / "kb_sample"))

EXCEL_MODULE_FILENAME = "新藥初審_AI_工作台模組.xlsx"
MASTER_PPTX_FILENAME = "母片.pptx"
EXAMPLE_TEXT_FILENAME = "語句描述文字檔.txt"
EXAMPLE_SLIDE_GLOB_PDF = "投影片範例*.pdf"
EXAMPLE_SLIDE_GLOB_PPTX = "投影片範例*.pptx"

EXCEL_PATH = KB_DIR / EXCEL_MODULE_FILENAME
MASTER_PPTX_PATH = KB_DIR / MASTER_PPTX_FILENAME
EXAMPLE_TEXT_PATH = KB_DIR / EXAMPLE_TEXT_FILENAME

SHEET_TOPIC_SPEC = "主題架構規格"
SHEET_DECISION_RULES = "決策邏輯與規則"
SHEET_DATA_SOURCES = "資料源"
SHEET_VENDOR_DOCS = "廠商文件"

# ---------------------------------------------------------------------------
# 2. 使用者資料儲存位置（本機端案件庫；正式環境建議改接資料庫）
# ---------------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
CASES_DIR = DATA_DIR / "cases"  # 每個新藥申請案一個子資料夾
UPLOADS_DIRNAME = "uploads"  # 案件內：使用者上傳的文獻/表單
OUTPUT_DIRNAME = "outputs"  # 案件內：產生的簡報輸出
USERS_FILE = DATA_DIR / "users.json"  # 簡易帳號/角色設定
ADMIN_OVERRIDES_FILE = DATA_DIR / "admin_overrides.json"  # 後台可調參數（Prompt、門檻）覆蓋檔

for d in (DATA_DIR, CASES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 3. 角色權限
# ---------------------------------------------------------------------------
ROLE_USER = "使用者"
ROLE_ADMIN = "管理藥師 / 主管"
ALL_ROLES = (ROLE_USER, ROLE_ADMIN)

# ---------------------------------------------------------------------------
# 4. AI 模型設定（支援 Anthropic Claude 或 Google Gemini 擇一使用）
# ---------------------------------------------------------------------------
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GEMINI = "gemini"
ALL_PROVIDERS = (PROVIDER_ANTHROPIC, PROVIDER_GEMINI)
PROVIDER_LABEL = {
    PROVIDER_ANTHROPIC: "Anthropic Claude",
    PROVIDER_GEMINI: "Google Gemini",
}

ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"

DEFAULT_PROVIDER = os.environ.get("NEWDRUG_AI_PROVIDER", PROVIDER_ANTHROPIC)
DEFAULT_MODEL = os.environ.get("NEWDRUG_AI_MODEL", "claude-sonnet-4-5")
DEFAULT_GEMINI_MODEL = os.environ.get("NEWDRUG_GEMINI_MODEL", "gemini-3.6-flash")

MAX_TOKENS_PER_TOPIC = 3000
MAX_IMAGES_PER_TOPIC = 4

# ---------------------------------------------------------------------------
# 5. 十宮格燈號（顏色 / 符號），對應「決策邏輯與規則」的燈號定義
# ---------------------------------------------------------------------------
LIGHT_GREEN = "GREEN"
LIGHT_YELLOW = "YELLOW"
LIGHT_RED = "RED"
LIGHT_NA = "NA"

LIGHT_SYMBOL = {
    LIGHT_GREEN: "🟢",
    LIGHT_YELLOW: "🔺",
    LIGHT_RED: "❌",
    LIGHT_NA: "—",
}
LIGHT_LABEL = {
    LIGHT_GREEN: "綠圈",
    LIGHT_YELLOW: "黃三角",
    LIGHT_RED: "紅叉",
    LIGHT_NA: "未評估",
}
LIGHT_RGB = {
    LIGHT_GREEN: (0x38, 0xA1, 0x69),
    LIGHT_YELLOW: (0xE0, 0xA1, 0x1E),
    LIGHT_RED: (0xC0, 0x39, 0x2B),
    LIGHT_NA: (0x99, 0x99, 0x99),
}

TEN_GRID_ITEMS = [
    "文獻證明療效相同或較優於現有藥品",
    "文獻證明安全性相同或較優於現有藥品",
    "體系無作用類似之藥品",
    "符合政策面特殊需求",
    "符合醫療面特殊需求",
    "國內同儕使用經驗",
    "體系有使用經驗",
    "臨床需求共識度",
    "價格/成本符合經濟效益",
    "廠商供應穩定度及企業永續作為或其他",
]
TEN_GRID_MANDATORY_IDX = [0, 1]
TEN_GRID_KEY_ITEMS_IDX = [2, 4, 7]

# ---------------------------------------------------------------------------
# 6. 主題總數
# ---------------------------------------------------------------------------
NUM_TOPICS = 10

# ---------------------------------------------------------------------------
# 7. 0-Token 結構化匯入（不使用 LLM 的主題）
# ---------------------------------------------------------------------------
# 主題1 封面：案件建立時藥師已經手動輸入過藥品英中文名，直接沿用即可。
# 主題2 申請總表：來源是廠商/醫師填寫的「新進藥品申請表」（結構化表單），逐欄對應即可。
# 主題9 臨床使用意見：來源是各院區藥師填寫的 Google 表單，逐字照登，AI 改寫反而是風險
# （語言模型天生有「順一下文字」的傾向，光靠 Prompt 規則無法保證 100% 逐字不動）。
# 一律用 Python 直接解析結構化資料寫入 payload，完全不呼叫 LLM，0 token 消耗。
SKIP_LLM_TOPICS = {1, 2, 9}

TOPIC2_DEFAULT_COLUMN_MAP = {
    "generic_name": "學名",
    "strength_form": "劑量/劑型",
    "moa": "作用機轉",
    "nhi_price": "健保價/藥價",
    "needs_replace": "須取代藥品",
    "replace_candidates": "暫定取代藥品",
    "similar_drugs": "同類藥品",
    "indication": "衛福部核准適應症",
    "application_reason": "申請理由",
    "applicant_physician": "提藥醫師",
}

# 主題9「各院區臨床意見」Google 表單為「兩列式標題、按院區分組」的橫向格式：
# 第一列是院區名稱（附醫/萬芳/雙和，合併儲存格橫跨3欄），第二列才是各院區底下
# 的子欄位名稱（負責藥師、院內是否有LASA品項、臨床意見）。
# site_1~3：院區名稱，順序需與表單一致；表單院區名稱不同時直接在畫面上改這裡即可。
# *_suffix：子欄位名稱關鍵字，用「欄名包含這幾個字」比對（非完全比對），
# 避免不同季度表單子欄位命名有些微差異（例如「院內是否有LASA品項」vs「院內是否LASA品項」）就對不上。
TOPIC9_DEFAULT_COLUMN_MAP = {
    "site_1": "附醫",
    "site_2": "萬芳",
    "site_3": "雙和",
    "pharmacist_name_suffix": "負責藥師",
    "lasa_suffix": "LASA",
    "opinion_suffix": "臨床意見",
}

TOPIC9_DEFAULT_PHYSICIAN_OPINION = "為提申請之科別，不另行詢問。"

# ---------------------------------------------------------------------------
# 8. 主題7「醫療科技評估(HTA)」PDF關鍵字智慧擷取
# ---------------------------------------------------------------------------
TOPIC7_HTA_KEYWORDS = [
    "NICE", "PBAC", "CADTH", "CDE", "HTA",
    "health technology assessment", "reimbursement", "recommend",
    "committee decision", "appraisal", "final decision",
    "核准給付", "不予給付", "拒絕給付", "有條件給付", "藥物給付項目及支付標準",
]
