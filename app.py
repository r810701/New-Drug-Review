# -*- coding: utf-8 -*-
"""
app.py
======
新藥初審 AI 工作台 — Streamlit 入口。

頁面配置：
Sidebar : 登入 / 知識庫狀態與「🔄 載入最新資料庫」/ Anthropic API Key
Tab 1   : 📋 新藥審查工作台（建立案件、上傳文獻、AI 產生簡報、逐頁編輯、下載）
Tab 2   : 🧭 十宮格總覽（本案十宮格燈號一覽 + 人工覆核）
Tab 3   : ⚙️ 後台管理（僅 管理藥師/主管：Prompt 覆蓋、門檻調整、帳號管理、KB 檢視）

執行方式： streamlit run app.py
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

import config
from modules import (
    ai_engine, auth, case_store, data_loader, ppt_builder, structured_data,
    topic_ui, ui_widgets, utils,
)
from modules.schema import Deck, DrugCase, TopicContent
from modules.utils import truncate

st.set_page_config(page_title="新藥初審 AI 工作台", page_icon="💊", layout="wide")


# ---------------------------------------------------------------------------
# Sidebar：登入 + 知識庫狀態 + API Key
# ---------------------------------------------------------------------------

def render_sidebar_kb_panel() -> None:
    st.markdown("### 🧠 知識庫狀態")
    kb = data_loader.load_knowledge_base()
    st.caption(data_loader.kb_status_summary(kb))

    if auth.is_admin():
        if st.button("🔄 載入最新資料庫", use_container_width=True, type="primary"):
            with st.spinner("正在清除快取並重新掃描【新藥審查AI】資料夾..."):
                kb = data_loader.force_refresh_knowledge_base()
            st.success(data_loader.kb_status_summary(kb))
        with st.expander("🩺 檔案診斷（規則數對不上時請看這裡）"):
            st.caption(
                "如果按了上面的按鈕，規則/範例數量還是沒變，"
                "十之八九是您編輯的檔案跟這裡列的『實際讀取路徑』不是同一份——"
                "請比對下面的『最後修改時間』跟您剛剛存檔的時間對不對得上。"
            )
            for row in data_loader.kb_file_diagnostics():
                st.markdown(
                    f"**{row['項目']}** 最後修改：{row['最後修改時間']} "
                    f"（{row['檔案大小']}）\n\n`{row['實際讀取路徑']}`"
                )
    else:
        st.caption("（僅管理藥師/主管可手動重新整理資料庫）")

    with st.expander("🔑 AI 模型金鑰設定", expanded=True):
        provider = st.selectbox(
            "AI 供應商",
            config.ALL_PROVIDERS,
            index=config.ALL_PROVIDERS.index(st.session_state.get("ai_provider", config.DEFAULT_PROVIDER)),
            format_func=lambda p: config.PROVIDER_LABEL[p],
            help="兩者擇一即可運作；沒有 Anthropic 帳號的話，選 Google Gemini 並填入您自己的 Gemini API Key。",
        )
        st.session_state["ai_provider"] = provider

        if provider == config.PROVIDER_ANTHROPIC:
            key = st.text_input(
                "Anthropic API Key",
                value=st.session_state.get(
                    "anthropic_api_key", os.environ.get(config.ANTHROPIC_API_KEY_ENV, "")
                ),
                type="password",
                help="部署到內網時建議改用環境變數 ANTHROPIC_API_KEY，這裡僅供臨時測試。",
            )
            st.session_state["anthropic_api_key"] = key
            model = st.text_input(
                "模型名稱", value=st.session_state.get("anthropic_model", config.DEFAULT_MODEL),
                help="Anthropic 改版型號時可直接在此覆蓋，不需改程式碼重新部署。",
            )
            st.session_state["anthropic_model"] = model
        else:
            key = st.text_input(
                "Gemini API Key",
                value=st.session_state.get("gemini_api_key", os.environ.get(config.GEMINI_API_KEY_ENV, "")),
                type="password",
                help="於 Google AI Studio 申請：https://aistudio.google.com/app/apikey"
                     "；部署到內網時建議改用環境變數 GEMINI_API_KEY。",
            )
            st.session_state["gemini_api_key"] = key
            model = st.text_input(
                "模型名稱", value=st.session_state.get("gemini_model", config.DEFAULT_GEMINI_MODEL),
                help="Google 的 Gemini 型號常改版/停用（如 gemini-2.5-flash 已被 gemini-3.6-flash 取代）；"
                     "若又報「no longer available」，把錯誤訊息裡建議的新型號貼到這裡即可，不需改程式碼。",
            )
            st.session_state["gemini_model"] = model
        st.caption(f"目前使用模型：`{model}`")


# ---------------------------------------------------------------------------
# Tab 1：新藥審查工作台
# ---------------------------------------------------------------------------

def render_case_selector() -> DrugCase:
    st.markdown("#### 1️⃣ 選擇 / 建立新藥申請案")
    existing = case_store.list_cases()
    mode = st.radio("模式", ["建立新案件", "開啟既有案件"], horizontal=True, label_visibility="collapsed")

    if mode == "開啟既有案件" and existing:
        slug = st.selectbox("既有案件", existing)
        dc = case_store.load_drug_case(slug)
        if dc:
            return dc
        st.warning("讀取失敗，請改用建立新案件。")

    with st.form("new_case_form"):
        c1, c2, c3 = st.columns(3)
        case_id = c1.text_input("案號", placeholder="例如：案15")
        dept = c2.text_input("提藥科別", placeholder="例如：萬芳皮膚科")
        physician = c3.text_input("提藥醫師", placeholder="例如：沈孟暵醫師")
        c4, c5 = st.columns(2)
        trade_en = c4.text_input("英文商品名/規格", placeholder="Sotyktu 6mg/Tab")
        trade_zh = c5.text_input("中文商品名", placeholder="舒停復膜衣錠6毫克")
        generic = st.text_input("學名", placeholder="Deucravacitinib")
        submitted = st.form_submit_button("建立 / 更新案件基本資料", type="primary")

        if submitted and case_id:
            dc = DrugCase(
                case_id=case_id, applicant_department=dept, applicant_physician=physician,
                trade_name_en=trade_en, trade_name_zh=trade_zh, generic_name=generic,
            )
            case_store.save_drug_case(dc)
            st.success(f"已儲存案件「{case_id}」")
            return dc

    return DrugCase(case_id=case_id or "未命名案件", applicant_department=dept if 'dept' in dir() else "")


def render_upload_section(drug_case: DrugCase) -> tuple[dict[int, str], dict[int, list[Path]]]:
    """
    讓使用者針對每個主題拖拉上傳文獻/貼上 Google 表單連結。
    回傳 (user_context, image_paths_by_topic)：
      - user_context：PDF/Word/Excel/CSV/文字檔擷取出的內容 + 使用者手動貼的文字/連結
      - image_paths_by_topic：JPG/PNG 檔案路徑（不做文字擷取，交給 AI
