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
# 【新藥審查AI】資料夾＝系統的「大腦」。預設抓專案內的 kb_sample，
# 部署到醫院內網時，請把環境變數 NEWDRUG_KB_DIR 指到真正的共用資料夾
# （例如 Google Drive 同步資料夾、NAS 路徑）。
BASE_DIR = Path(__file__).resolve().parent
KB_DIR = Path(os.environ.get("NEWDRUG_KB_DIR", BASE_DIR / "kb_sample"))

# 資料夾內固定檔名（管理藥師更新資料庫時，檔名務必維持一致，
# 若要改檔名，也只需要改這裡一處）
EXCEL_MODULE_FILENAME = "新藥初審_AI_工作台模組.xlsx"
MASTER_PPTX_FILENAME = "母片.pptx"
EXAMPLE_TEXT_FILENAME = "語句描述文字檔.txt"
# 投影片範例可能有多份（範例1、範例2...），用 glob pattern 抓取
EXAMPLE_SLIDE_GLOB_PDF = "投影片範例*.pdf"
EXAMPLE_SLIDE_GLOB_PPTX = "投影片範例*.pptx"

EXCEL_PATH = KB_DIR / EXCEL_MODULE_FILENAME
MASTER_PPTX_PATH = KB_DIR / MASTER_PPTX_FILENAME
EXAMPLE_TEXT_PATH = KB_DIR / EXAMPLE_TEXT_FILENAME

# Excel 內固定的工作表名稱（對應「主題架構規格」「決策邏輯與規則」「資料源」「廠商文件」）
SHEET_TOPIC_SPEC = "主題架構規格"
SHEET_DECISION_RULES = "決策邏輯與規則"
SHEET_DATA_SOURCES = "資料源"
SHEET_VENDOR_DOCS = "廠商文件"

# ---------------------------------------------------------------------------
# 2. 使用者資料儲存位置（本機端案件庫；正式環境建議改接資料庫）
# ---------------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
CASES_DIR = DATA_DIR / "cases"          # 每個新藥申請案一個子資料夾
UPLOADS_DIRNAME = "uploads"             # 案件內：使用者上傳的文獻/表單
OUTPUT_DIRNAME = "outputs"              # 案件內：產生的簡報輸出
USERS_FILE = DATA_DIR / "users.json"    # 簡易帳號/角色設定
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
# 建議透過環境變數注入金鑰，勿寫死於程式碼／版本控制中。
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
# 2026/6/1 起 gemini-2.0-flash 系列已停用；2026/10/16 起 gemini-2.5-flash 系列亦將停用，
# 官方建議改用 GA 穩定版 gemini-3.6-flash（見 Gemini API release notes）。
# 因應 Google 模型改版頻繁，此值僅為「找不到使用者自訂設定時」的退回值，
# 使用者可直接在側邊欄「AI 模型金鑰設定」輸入其他型號字串覆蓋，不需改程式碼重新部署。
DEFAULT_GEMINI_MODEL = os.environ.get("NEWDRUG_GEMINI_MODEL", "gemini-3.6-flash")
MAX_TOKENS_PER_TOPIC = 3000
# 每個主題最多送幾張圖片給 AI 視覺辨識（控制費用/延遲；仿單/文獻截圖通常 1-3 張就夠）
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
# PPTX 填色用（RGB）
LIGHT_RGB = {
    LIGHT_GREEN: (0x38, 0xA1, 0x69),
    LIGHT_YELLOW: (0xE0, 0xA1, 0x1E),
    LIGHT_RED: (0xC0, 0x39, 0x2B),
    LIGHT_NA: (0x99, 0x99, 0x99),
}

# 十宮格 10 個評估項目（固定順序，對應 Excel「十宮格判定邏輯」1~10 點）
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
# 必要項目（依規則：療效、安全性 2 項必須為綠圈，10 項總分需 ≥5 綠圈才「建議通過」）
TEN_GRID_MANDATORY_IDX = [0, 1]
TEN_GRID_KEY_ITEMS_IDX = [2, 4, 7]  # 體系無同類品 / 醫療面特殊需求 / 臨床需求共識度（3 項關鍵項目）

# ---------------------------------------------------------------------------
# 6. 主題總數
# ---------------------------------------------------------------------------
NUM_TOPICS = 10

# ---------------------------------------------------------------------------
# 7. 0-Token 結構化匯入（不使用 LLM 的主題）
# ---------------------------------------------------------------------------
# 這幾個主題的內容本質上是「照抄結構化資料」而非「需要 AI 統整判讀」：
#   主題1 封面：案件建立時藥師已經手動輸入過藥品英中文名，直接沿用即可。
#   主題2 申請總表：來源是廠商/醫師填寫的「新進藥品申請表」（結構化表單），逐欄對應即可。
#   主題9 臨床使用意見：來源是各院區藥師填寫的 Google 表單，逐字照登，AI 改寫反而是風險
#     （語言模型天生有「順一下文字」的傾向，光靠 Prompt 規則無法保證 100% 逐字不動）。
# 一律用 Python 直接解析結構化資料寫入 payload，完全不呼叫 LLM，0 token 消耗。
SKIP_LLM_TOPICS = {1, 2, 9}

# 主題2「新進藥品申請表」欄位對應的預設猜測（找不到時使用者可在畫面上自行修改對應的
# 實際表單欄位名稱，不需要改程式碼；欄位名稱用「表單上的完整欄位文字」比對）
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

# 主題9「各院區臨床意見」Google 表單欄位對應預設猜測
TOPIC9_DEFAULT_COLUMN_MAP = {
    "site": "院區",
    "pharmacist_name": "負責藥師",
    "pharmacist_opinion": "臨床意見",
    "physician_opinion": "醫師意見",  # 選填；表單沒有這欄就會用下面的固定套語
}
TOPIC9_DEFAULT_PHYSICIAN_OPINION = "為提申請之科別，不另行詢問。"
TOPIC9_DEFAULT_PHYSICIAN_OPINION = "請在此輸入預設的醫師意見文字"
# ---------------------------------------------------------------------------
# 8. 主題7「醫療科技評估(HTA)」PDF關鍵字智慧擷取
# ---------------------------------------------------------------------------
# 文件可能長達10~200頁，與其死板地只送前 max_chars 字元（真正的給付決策
# 段落很可能不在文件開頭），改成優先擷取包含以下關鍵字的段落，
# 字元上限不變，但能抓到真正跟決策相關的內容，而非文件開頭的背景/方法學章節。
TOPIC7_HTA_KEYWORDS = [
    "NICE", "PBAC", "CADTH", "CDE", "HTA",
    "health technology assessment", "reimbursement", "recommend",
    "committee decision", "appraisal", "final decision",
    "核准給付", "不予給付", "拒絕給付", "有條件給付", "藥物給付項目及支付標準",
]
