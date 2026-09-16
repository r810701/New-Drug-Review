# -*- coding: utf-8 -*-
"""
modules/ai_engine.py
=====================
把「知識庫（規則＋範例）＋ 使用者上傳文獻/表單 ＋ 藥品案件基本資料」
組成 Prompt，呼叫 Claude 產生每一張投影片的結構化內容（JSON），
回傳 schema.TopicContent，供 app.py 顯示編輯、再交給 ppt_builder 產生簡報。

設計重點：
  - 每個主題（1~10）都有專屬的「輸出 JSON 欄位schema」說明，讓模型輸出穩定好解析的結構，
    而不是整段自由文字（那樣後續 PPT 排版會很痛苦）。
  - System Prompt 由 Excel「決策邏輯與規則」動態組成，管理藥師更新 Excel 後，
    下一次生成就會套用新規則，不需要改程式碼。
  - 後台可透過 admin_overrides.json 覆蓋/追加 System Prompt（給主管臨時調整用）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import streamlit as st

import config
from modules.schema import Deck, DrugCase, KnowledgeBase, TenGridResult, TopicContent
from modules.utils import safe_json_loads

try:
    import anthropic
except ImportError:  # 讓沒裝 SDK 時模組仍可被 import（例如純編輯模式）
    anthropic = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None


# ---------------------------------------------------------------------------
# 後台可調參數（Prompt 覆蓋、十宮格門檻）
# ---------------------------------------------------------------------------
def load_admin_overrides() -> dict:
    if config.ADMIN_OVERRIDES_FILE.exists():
        return json.loads(config.ADMIN_OVERRIDES_FILE.read_text(encoding="utf-8"))
    return {"extra_system_prompt": "", "green_threshold": 5}


def save_admin_overrides(data: dict) -> None:
    config.ADMIN_OVERRIDES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 各主題輸出 JSON schema 說明（給模型看的欄位規格，非嚴格 jsonschema，用自然語言足夠）
# ---------------------------------------------------------------------------
TOPIC_JSON_FIELDS: dict[int, str] = {
    1: """{
  "trade_name_en": "英文商品名/規格", "trade_name_zh": "中文商品名",
  "generic_name": "學名", "photo_notes": "建議放置的藥品照片描述（外盒/鋁箔/針劑/裸錠正反面）"
}""",
    2: """{
  "generic_name": "", "strength_form": "劑量/劑型", "moa": "作用機轉",
  "nhi_price": "健保價/藥價", "needs_replace": "是/否",
  "replace_candidates": ["暫定取代藥品清單"], "similar_drugs": ["同類藥品清單"],
  "indication": "衛福部核准適應症全文", "application_reason": "申請理由條列(每點一句)",
  "applicant_physician": "提藥醫師 姓名/科別"
}""",
    3: """{
  "moa_summary": "2-4句機轉重點摘要，適合初學者理解",
  "moa_diagram_desc": "建議插入之機轉圖/疾病生理圖描述與來源",
  "citation": "[第一作者 et al., 期刊縮寫, 年份]"
}""",
    4: """{
  "guideline_rows": [
    {"country_or_society": "學會/國家", "year": "年份",
     "treatment_line": "1st-line/2nd-line/Add-on/Rescue",
     "drug_examples": ["該順位代表藥品學名1-3個"]}
  ],
  "summary": "1-2句地位總結"
}""",
    5: """{
  "trials": [
    {"trial_name": "", "citation": "Author et al., Journal, Year",
     "design": "", "population": "", "regimen": "",
     "key_results": [{"endpoint": "", "value_a": "", "value_b": "", "p_value": ""}],
     "conclusion_box": "一句話結論，如：療效指標A > B"}
  ]
}""",
    6: """{
  "trials": [
    {"trial_name": "", "citation": "Author et al., Journal, Year",
     "design": "", "population": "", "regimen": "",
     "adr_table": [{"category": "AEs/SAEs/Discontinuation/Most common", "drug_a": "", "drug_b": ""}],
     "conclusion_box": ""}
  ]
}""",
    7: """{
  "hta_rows": [
    {"agency": "NICE/PBAC/CADTH/CDE...", "year": "", "verdict": "", "key_findings": ""}
  ],
  "note_if_missing": "若查無資料要標記「查無資料」"
}""",
    8: """{
  "columns": ["申請藥品", "暫定取代藥品", "同類藥品(可多欄)"],
  "rows": [
    {"field": "適應症/差異/建議劑量/健保價/每日藥價/月均用量",
     "values": ["...", "...", "..."], "bold_advantage_idx": [0]}
  ]
}""",
    9: """{
  "info_box": {"applied_drug": "", "replace_drug": "", "similar_drug": "", "main_department": ""},
  "site_opinions": [
    {"site": "附醫/萬芳/雙和", "physician_opinion": "", "pharmacist_opinion": ""}
  ]
}""",
    10: """{
  "ten_grid": [
    {"item_index": 0, "light": "GREEN/YELLOW/RED", "rationale": "括號內判斷論述"}
    // 共 10 筆，index 0~9，對應十宮格 10 個項目，順序固定
  ],
  "high_alert": {"is_high_alert": false, "note": "AI初判是否為衛福部/ISMP高警訊藥品，藥師需人工確認"},
  "lasa": "自Google表單彙整之外觀/名稱相似品項",
  "review_history_note": "歷年審議結果(年分/不通過原因)，無資料填『無，首次申請』",
  "summary_points": ["3-4點綜合意見", "..."],
  "final_recommendation": "建議通過/建議通過(但不常備)/建議比價/建議不通過"
}""",
}

TOPIC_NAME_HINT = {
    1: "封面", 2: "申請總表", 3: "療效-機轉", 4: "療效-指引", 5: "療效-文獻",
    6: "安全性", 7: "醫療科技評估", 8: "藥品比較", 9: "臨床使用意見", 10: "綜合評估",
}


# ---------------------------------------------------------------------------
# Prompt 組裝
# ---------------------------------------------------------------------------
def build_system_prompt(kb: KnowledgeBase) -> str:
    overrides = load_admin_overrides()
    role_rule = next(
        (r.content for r in kb.decision_rules if r.item == "全域角色設定 (System Role)"), ""
    )
    parts = [
        role_rule or "你是專業、謹慎、注重實證品質的新藥審查藥師助理。",
        "\n以下是本院【決策邏輯與規則】完整規範，產生任何內容都必須嚴格遵守：",
        kb.rules_text(),
        "\n輸出規範：只輸出合法 JSON（不要附加說明文字、不要用 markdown code fence 包裹），"
        "欄位需完全符合使用者訊息中指定的 schema。專有名詞優先使用醫學常用縮寫。"
        "所有引用文獻／機轉圖需附出處；凡出現 PMID 或 DOI，請照規則格式書寫。",
        "\n【文獻引用鐵律 — 絕對禁止捏造】\n"
        "1. 若使用者訊息中的『使用者上傳/補充資料』段落附有真實文獻全文，你產生的所有作者/期刊/年份/數據，"
        "必須完全依照該全文，不可替換成你記憶中同類藥物/同適應症的其他知名試驗（例如不可把使用者提供的"
        "文獻，寫成你記得的另一篇更有名但不同年份/作者的試驗）。\n"
        "2. 若使用者沒有提供該主題的文獻全文，你可以依你所知的實證資料作答，但『citation』欄位必須誠實標註"
        "『(依AI訓練知識推論，非使用者提供文獻，建議人工查證出處)』，不可假裝是使用者提供的資料，"
        "也不可以捏造看似精確但你並不確定真偽的作者/期刊/年份/PMID/DOI。\n"
        "3. 每個主題各自獨立作答；不要只因為前面某個主題引用過某篇文獻，就不加查證地把同一篇套用到"
        "其他不相關的主題（不同主題如果引用同一篇文獻，必須是那篇文獻本身確實同時支持這些主題的論述）。",
    ]
    if overrides.get("extra_system_prompt"):
        parts.append("\n【主管臨時追加指示】\n" + overrides["extra_system_prompt"])
    return "\n".join(parts)


def build_few_shot_block(kb: KnowledgeBase, outcome_hint: Optional[str] = None) -> str:
    """
    依「本案可能的結論方向」（不須取代/需取代/建議比價）挑選對應的語句範例，
    讓 AI 模仿該情境下的論述語氣與結構。outcome_hint 為 None 時，三類各取 1 則。
    """
    snippets = kb.example_snippets
    if not snippets:
        return "（目前教材庫無語句範例，請以一般專業口吻撰寫）"

    if outcome_hint:
        picked = [s for s in snippets if s.category == outcome_hint][:3]
    else:
        picked = []
        for cat in ("不須取代品項", "需取代品項", "建議比價"):
            cat_items = [s for s in snippets if s.category == cat]
            if cat_items:
                picked.append(cat_items[0])

    lines = ["【語氣與論述風格參考範例（僅供模仿風格，內容請勿照抄）】"]
    for s in picked:
        lines.append(f"- ({s.category}/{s.subcategory})\n{s.text}")
    return "\n".join(lines)


def build_topic_user_prompt(
    topic_no: int,
    kb: KnowledgeBase,
    drug_case: DrugCase,
    user_context: str,
    outcome_hint: Optional[str] = None,
) -> str:
    spec = kb.topic(topic_no)
    ai_goal = spec.ai_goal if spec else ""
    sources = kb.sources_for(topic_no)
    schema_desc = TOPIC_JSON_FIELDS.get(topic_no, "{}")

    return f"""
請為以下新藥申請案，產生【主題 {topic_no}：{TOPIC_NAME_HINT.get(topic_no, '')}】投影片的內容。

【藥品基本資料】
- 案號：{drug_case.case_id}
- 英文商品名/規格：{drug_case.trade_name_en}
- 中文商品名：{drug_case.trade_name_zh}
- 學名：{drug_case.generic_name}
- 提藥科別/醫師：{drug_case.applicant_department} / {drug_case.applicant_physician}

【本頁 AI 代工目標（來自 Excel 主題架構規格）】
{ai_goal}

【本頁建議資料源優先順位（來自 Excel 資料源）】
{sources}

【使用者本次上傳/貼上的補充資料（文獻全文、Google表單彙整、連結等，若為空代表尚未提供，
請依上方資料源優先順位自行以你所知的實證資料作答，並誠實標註「建議人工覆核」）】
{user_context or "(無使用者上傳資料)"}

{build_few_shot_block(kb, outcome_hint)}

【輸出 JSON 欄位規格，請務必只輸出符合此結構的合法 JSON】
{schema_desc}
""".strip()


# ---------------------------------------------------------------------------
# 呼叫 LLM（雙供應商：Anthropic Claude / Google Gemini，擇一即可運作）
# ---------------------------------------------------------------------------
def get_current_provider() -> str:
    """目前使用者於側邊欄選擇的供應商；未選擇時退回 config 預設值。"""
    return st.session_state.get("ai_provider", config.DEFAULT_PROVIDER)


def get_current_model(provider: Optional[str] = None) -> str:
    """
    目前實際會使用的模型字串：優先讀使用者於側邊欄輸入的覆蓋值，
    否則退回 config 預設值。Gemini/Claude 型號常常改版，
    做成可覆蓋是為了型號一失效，使用者不用等改程式碼就能自己換。
    """
    provider = provider or get_current_provider()
    if provider == config.PROVIDER_GEMINI:
        return st.session_state.get("gemini_model") or config.DEFAULT_GEMINI_MODEL
    return st.session_state.get("anthropic_model") or config.DEFAULT_MODEL


def _call_claude(system_prompt: str, user_prompt: str, model: Optional[str] = None) -> str:
    if anthropic is None:
        raise RuntimeError("尚未安裝 anthropic SDK，請先 `pip install anthropic`。")
    api_key = st.session_state.get("anthropic_api_key") or os.environ.get(
        config.ANTHROPIC_API_KEY_ENV
    )
    if not api_key:
        raise RuntimeError(
            "尚未設定 Anthropic API Key，請於側邊欄「AI 模型金鑰設定」輸入，"
            "或改在下拉選單切換為 Google Gemini。"
        )
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model or get_current_model(config.PROVIDER_ANTHROPIC),
        max_tokens=config.MAX_TOKENS_PER_TOPIC,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


def _call_gemini(system_prompt: str, user_prompt: str, model: Optional[str] = None) -> str:
    if genai is None:
        raise RuntimeError("尚未安裝 google-generativeai SDK，請先 `pip install google-generativeai`。")
    api_key = st.session_state.get("gemini_api_key") or os.environ.get(config.GEMINI_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            "尚未設定 Gemini API Key，請於側邊欄「AI 模型金鑰設定」輸入，"
            "或改在下拉選單切換為 Anthropic Claude。"
        )
    genai.configure(api_key=api_key)
    model_name = model or get_current_model(config.PROVIDER_GEMINI)
    try:
        gen_model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            generation_config={
                "max_output_tokens": config.MAX_TOKENS_PER_TOPIC,
                "response_mime_type": "application/json",
            },
        )
        resp = gen_model.generate_content(user_prompt)
        return resp.text or ""
    except Exception as e:  # noqa: BLE001
        # Google 常在錯誤訊息裡直接告知「請改用哪個型號」，把它原樣往上拋讓使用者看到，
        # 比包成通用訊息更好判斷是不是又改版了。
        raise RuntimeError(f"Gemini 模型「{model_name}」呼叫失敗：{e}") from e


def call_llm(system_prompt: str, user_prompt: str, model: Optional[str] = None) -> str:
    """依目前選定的供應商分派呼叫；回傳原始文字（預期是 JSON 字串）。"""
    provider = get_current_provider()
    if provider == config.PROVIDER_GEMINI:
        return _call_gemini(system_prompt, user_prompt, model)
    return _call_claude(system_prompt, user_prompt, model)


# ---------------------------------------------------------------------------
# 對外主函式
# ---------------------------------------------------------------------------
def generate_topic_content(
    topic_no: int,
    kb: KnowledgeBase,
    drug_case: DrugCase,
    user_context: str = "",
    outcome_hint: Optional[str] = None,
) -> TopicContent:
    system_prompt = build_system_prompt(kb)
    user_prompt = build_topic_user_prompt(topic_no, kb, drug_case, user_context, outcome_hint)

    raw = call_llm(system_prompt, user_prompt)
    payload = safe_json_loads(raw) or {"raw_text_fallback": raw}

    spec = kb.topic(topic_no)
    title = spec.slide_title_template.split("\n")[0] if spec else TOPIC_NAME_HINT.get(topic_no, "")

    return TopicContent(
        topic_no=topic_no,
        title=title,
        payload=payload,
        ai_raw_response=raw,
        is_ai_generated=True,
    )


def generate_ten_grid(payload: dict) -> list[TenGridResult]:
    results = []
    for item in payload.get("ten_grid", []):
        idx = int(item.get("item_index", 0))
        name = config.TEN_GRID_ITEMS[idx] if 0 <= idx < len(config.TEN_GRID_ITEMS) else f"項目{idx}"
        results.append(
            TenGridResult(
                item_index=idx,
                item_name=name,
                light=item.get("light", config.LIGHT_NA),
                rationale=item.get("rationale", ""),
            )
        )
    return results


def compute_recommendation(ten_grid: list[TenGridResult]) -> str:
    """
    依 Excel「十宮格判定邏輯」摘要出的自動判斷（僅供參考，最終仍需藥師確認）：
      - 療效/安全性（idx 0,1）必須都是綠圈，否則直接「建議不通過」
      - 綠圈數 >=5 -> 建議通過；否則看是否體系內有同類品 -> 建議比價；都不是 -> 建議不通過
    """
    by_idx = {r.item_index: r for r in ten_grid}
    mandatory_ok = all(
        by_idx.get(i) and by_idx[i].light == config.LIGHT_GREEN
        for i in config.TEN_GRID_MANDATORY_IDX
    )
    if not mandatory_ok:
        return "建議不通過"

    green_count = sum(1 for r in ten_grid if r.light == config.LIGHT_GREEN)
    overrides = load_admin_overrides()
    threshold = int(overrides.get("green_threshold", 5))

    has_similar_drug_in_system = by_idx.get(2) and by_idx[2].light == config.LIGHT_RED
    if green_count >= threshold:
        return "建議通過" if not has_similar_drug_in_system else "建議通過(但不常備)"
    if has_similar_drug_in_system:
        return "建議比價"
    return "建議不通過"


def generate_full_deck(
    kb: KnowledgeBase,
    drug_case: DrugCase,
    user_context_by_topic: dict[int, str],
    progress_callback=None,
) -> Deck:
    deck = Deck(drug_case=drug_case)
    for topic_no in range(1, config.NUM_TOPICS + 1):
        content = generate_topic_content(
            topic_no, kb, drug_case, user_context_by_topic.get(topic_no, "")
        )
        deck.topics[topic_no] = content
        if progress_callback:
            progress_callback(topic_no, content)

        if topic_no == config.NUM_TOPICS:
            deck.ten_grid = generate_ten_grid(content.payload)
            deck.summary_points = content.payload.get("summary_points", [])
            deck.review_history_note = content.payload.get("review_history_note", "")
            ai_reco = content.payload.get("final_recommendation")
            deck.final_recommendation = ai_reco or compute_recommendation(deck.ten_grid)
    return deck
