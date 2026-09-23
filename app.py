# -*- coding: utf-8 -*-
"""
app.py
======
新藥初審 AI 工作台 — Streamlit 入口。

版面重構（v2）：每個主題只有一個 expander，內含「投餵資料 → 產生 → 預覽 →
人工編輯」完整流程，取代先前「先統一投餵、再統一產生」的兩階段設計，
避免一鍵整批產生時，已手動編輯過的主題被無條件覆蓋掉。

頁面配置：
Sidebar : 登入 / 知識庫狀態與「🔄 載入最新資料庫」/ Anthropic API Key
Tab 1   : 📋 新藥審查工作台（建立案件、逐主題投餵/產生/編輯、下載）
Tab 2   : 🧭 十宮格總覽（本案十宮格燈號一覽 + 人工覆核）
Tab 3   : ⚙️ 後台管理（僅 管理藥師/主管：Prompt 覆蓋、門檻調整、帳號管理、KB 檢視）

執行方式： streamlit run app.py
"""
from __future__ import annotations

import json as _json
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
# Tab 1：案件選擇
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


# ---------------------------------------------------------------------------
# 主題2/9 專用：結構化匯入區塊
# ---------------------------------------------------------------------------

def _render_structured_import_block(
    topic_no: int, drug_case: DrugCase, deck: Deck, content: TopicContent,
) -> None:
    """
    主題 2/9 專用：完全不呼叫 LLM 的結構化資料匯入 UI。
    主題2對應的試算表鎖了分享權限，固定只走「上傳Excel檔案」；
    主題9支援「Google試算表網址」或「上傳Excel檔案」兩種來源。
    兩種來源都會先轉成CSV文字，沿用同一套解析邏輯，0 token 消耗，
    且保證逐字不改（尤其主題9的 Google 表單臨床意見）。
    """
    saved_cfg = case_store.load_structured_source(drug_case.slug, topic_no)
    default_map = config.TOPIC2_DEFAULT_COLUMN_MAP if topic_no == 2 else config.TOPIC9_DEFAULT_COLUMN_MAP
    source_label = "廠商/醫師填寫的新進藥品申請表" if topic_no == 2 else "各院區藥師填寫的臨床意見 Google 表單"
    st.caption(
        f"資料來源：{source_label}。系統會逐欄對應寫入，"
        "**完全不經過 AI 改寫**，原文長怎樣就長怎樣。"
    )

    if topic_no == 2:
        source_mode = "上傳 Excel 檔案"
    else:
        source_mode = st.radio(
            "資料來源方式", ["Google 試算表網址", "上傳 Excel 檔案"],
            horizontal=True, key=f"struct_source_{topic_no}",
            index=0 if saved_cfg.get("source_mode", "url") == "url" else 1,
            help="若 Google 試算表分享權限設定有問題導致抓取失敗，改用「上傳 Excel 檔案」"
                 "（把試算表下載成 .xlsx 再上傳）即可完全繞開權限問題。",
        )

    sheet_url = ""
    excel_file = None
    if source_mode == "Google 試算表網址":
        sheet_url = st.text_input(
            "Google 試算表網址", value=saved_cfg.get("sheet_url", ""), key=f"struct_url_{topic_no}",
            help="需設定「知道連結的人皆可檢視」權限，系統才抓得到內容。",
        )
    else:
        excel_file = st.file_uploader(
            "上傳 Excel 檔案（.xlsx）", type=["xlsx"], key=f"struct_excel_{topic_no}",
            help="把 Google 試算表下載成 Excel（檔案 → 下載 → Microsoft Excel）後在這裡上傳即可。",
        )

    fcol1, fcol2 = st.columns(2)
    filter_col = fcol1.text_input(
        "篩選欄位（選填，共用表單時用來只抓這個案件的列）",
        value=saved_cfg.get("filter_col", ""), key=f"struct_fcol_{topic_no}",
        placeholder="例如：藥品學名",
    )
    filter_val = fcol2.text_input(
        "篩選值", value=saved_cfg.get("filter_val", drug_case.generic_name if topic_no == 9 else ""),
        key=f"struct_fval_{topic_no}", placeholder="例如：Deucravacitinib",
    )

    with st.expander("⚙️ 欄位對應設定（表單欄位名稱跟預設猜測不一樣時，在這裡改）"):
        column_map = {}
        for field_key, default_col in default_map.items():
            column_map[field_key] = st.text_input(
                topic_ui.humanize_key(field_key),
                value=saved_cfg.get("column_map", {}).get(field_key, default_col),
                key=f"struct_col_{topic_no}_{field_key}",
            )

    btn_col1, btn_col2 = st.columns(2)
    preview_clicked = btn_col1.button("🔍 預覽偵測到的資料", key=f"struct_preview_{topic_no}")
    import_clicked = btn_col2.button("📥 匯入（0 Token）", key=f"struct_import_{topic_no}", type="primary")

    if preview_clicked or import_clicked:
        case_store.save_structured_source(
            drug_case.slug, topic_no,
            {
                "sheet_url": sheet_url, "filter_col": filter_col, "filter_val": filter_val,
                "column_map": column_map,
                "source_mode": "url" if source_mode == "Google 試算表網址" else "excel",
            },
        )

        fetched = ""
        fetched_ok = False
        if source_mode == "Google 試算表網址":
            if not sheet_url.strip():
                st.warning("請先貼上 Google 試算表網址。")
            else:
                fetched = utils.fetch_url_content(sheet_url, max_chars=40000)
                if fetched.startswith("（") and fetched.endswith("）"):
                    st.error(f"抓取失敗：{fetched}")
                else:
                    fetched_ok = True
        else:
            if excel_file is None:
                st.warning("請先上傳 Excel 檔案。")
            else:
                try:
                    fetched = utils.excel_to_csv_text(excel_file)
                    fetched_ok = True
                except Exception as e:  # noqa: BLE001
                    st.error(f"Excel 檔案讀取失敗：{e}")

        if fetched_ok:
            rows = (
                structured_data.parse_csv_two_row_header(fetched)
                if topic_no == 9 else structured_data.parse_csv_text(fetched)
            )
            filtered = structured_data.filter_rows(rows, filter_col, filter_val)
            detected_cols = structured_data.detect_columns(rows)

            if preview_clicked:
                st.info(f"偵測到欄位：{'、'.join(detected_cols) if detected_cols else '（無）'}")
                st.write(f"篩選前共 {len(rows)} 列，篩選後 {len(filtered)} 列：")
                st.dataframe(filtered[:20], use_container_width=True)

            if import_clicked:
                if not filtered:
                    st.warning("篩選後沒有任何資料列，請確認篩選欄位/篩選值是否正確，或先按「預覽」核對。")
                else:
                    if topic_no == 2:
                        new_payload = structured_data.build_topic2_payload(filtered[0], column_map)
                    else:
                        topic2_payload = deck.topics.get(2).payload if deck.topics.get(2) else None
                        new_payload = structured_data.build_topic9_payload(
                            filtered, column_map, drug_case=drug_case, topic2_payload=topic2_payload,
                        )
                    new_content = TopicContent(
                        topic_no=topic_no, title=content.title, reviewer_note=content.reviewer_note,
                        payload=new_payload, is_ai_generated=False, is_human_edited=False,
                    )
                    deck.topics[topic_no] = new_content
                    case_store.save_deck(deck)
                    st.success(f"已匯入 {len(filtered)} 列資料，內容逐字保留、未經 AI 改寫。")
                    st.rerun()


# ---------------------------------------------------------------------------
# 每個主題的完整工作區塊：投餵 → 產生 → 預覽 → 編輯，全部在同一個 expander 裡
# ---------------------------------------------------------------------------

def _render_upload_widget(topic_no: int, drug_case: DrugCase) -> tuple[str, list[Path]]:
    """
    通用上傳元件（主題1、3~8、10 共用）：拖曳上傳文獻/圖片、貼連結。
    回傳 (擷取後的文字內容, 圖片檔案路徑清單)。
    主題1不會呼叫AI，這裡擷取出的PDF/Word文字目前不會被實際使用——只有照片
    會被用到（插入簡報封面），畫面上會誠實標註這點，避免誤以為文字有生效。
    """
    files = st.file_uploader(
        "上傳檔案（PDF / Word / Excel / CSV / 圖片）",
        type=["pdf", "docx", "xlsx", "csv", "txt", "md", "png", "jpg", "jpeg"],
        accept_multiple_files=True, key=f"upl_{drug_case.slug}_{topic_no}",
    )
    link_text = st.text_area(
        "或貼上連結/文字", key=f"link_{drug_case.slug}_{topic_no}", height=70,
    )

    target_dir = case_store.uploads_dir(drug_case.slug, topic_no)
    if files:
        for f in files:
            (target_dir / f.name).write_bytes(f.getbuffer())

    all_files = sorted(target_dir.glob("*")) if target_dir.exists() else []
    doc_files = [p for p in all_files if p.suffix.lower() not in utils.IMAGE_EXTS]
    image_files = [p for p in all_files if p.suffix.lower() in utils.IMAGE_EXTS]

    ctx_parts = []
    for p in doc_files:
        extracted = utils.extract_text_from_upload(
            p, keywords=config.TOPIC7_HTA_KEYWORDS if topic_no == 7 else None,
        )
        ctx_parts.append(f"== 使用者上傳檔案：{p.name} ==\n{extracted}")
        is_note = extracted.startswith("（") and extracted.endswith("）")
        if is_note and p.suffix.lower() == ".pdf" and "掃描影像型" in extracted:
            # 這份PDF其實是照片包裝成的檔案，擷取不到文字很正常，
            # 改成把每一頁轉成圖片，跟一般JPG/PNG一樣被使用（封面插圖／AI視覺辨識）。
            rendered = utils.pdf_pages_to_images(p, target_dir / "_pdf_pages")
            if rendered:
                image_files.extend(rendered)
                st.caption(f"🖼️ 「{p.name}」偵測為圖片型PDF，已自動轉成 {len(rendered)} 張圖片使用")
            else:
                st.caption(f"⚠️ {p.name}：{extracted}")
        elif topic_no == 1:
            st.caption(
                f"ℹ️ 已擷取「{p.name}」文字內容（{len(extracted)} 字元），"
                "但主題1目前不呼叫AI，此文字僅供您自行參考，尚未被系統實際使用。"
            )
        else:
            st.caption(f"✅ 已擷取「{p.name}」文字內容（{len(extracted)} 字元），將提供給 AI 參考")

    for p in image_files:
        if topic_no == 1:
            st.caption(f"🖼️ 「{p.name}」將作為封面照片插入簡報第1頁")
        else:
            st.caption(f"🖼️ 「{p.name}」將以圖片方式直接提供給 AI 視覺辨識（非文字擷取）")
    if len(image_files) > config.MAX_IMAGES_PER_TOPIC:
        st.caption(
            f"⚠️ 本主題圖片共 {len(image_files)} 張，超過單次送出上限 "
            f"{config.MAX_IMAGES_PER_TOPIC} 張，只有前 {config.MAX_IMAGES_PER_TOPIC} 張會被 AI 看到。"
        )

    if link_text.strip():
        urls = utils.extract_urls(link_text)
        if urls:
            for url in urls:
                fetched = utils.fetch_url_content(url)
                ctx_parts.append(f"== 使用者貼上連結：{url} ==\n{fetched}")
                is_note = fetched.startswith("（") and fetched.endswith("）")
                if is_note:
                    st.caption(f"⚠️ 連結擷取失敗：{fetched}")
                else:
                    st.caption(f"✅ 已抓取連結內容（{len(fetched)} 字元），將提供給 AI 參考")
            non_url_text = utils.strip_urls(link_text)
            if non_url_text:
                ctx_parts.append(f"== 使用者補充文字 ==\n{non_url_text}")
        else:
            ctx_parts.append(f"== 使用者補充文字 ==\n{link_text.strip()}")

    return "\n\n".join(ctx_parts), image_files


def render_topic_section(topic_no: int, drug_case: DrugCase, deck: Deck, kb_local, hint) -> None:
    """單一主題的完整工作區塊：投餵資料 → 產生 → 預覽 → 人工編輯，全部收在同一個 expander。"""
    spec = kb_local.topic(topic_no)
    title_default = spec.slide_title_template.split("\n")[0] if spec else f"主題{topic_no}"
    content = deck.topics.get(topic_no, TopicContent(topic_no=topic_no, title=title_default))
    has_error = "_generation_error" in content.payload
    status_icon = "❌ " if has_error else ("✅ " if content.is_ai_generated or content.is_human_edited else "")

    with st.expander(f"📑 {status_icon}主題 {topic_no}：{title_default}", expanded=True):
        if has_error:
            st.error(f"上次生成失敗：{content.payload['_generation_error']}")

        st.markdown("##### 📎 投餵資料")
        image_files: list[Path] = []
        topic_context = ""

        if topic_no in (2, 9):
            _render_structured_import_block(topic_no, drug_case, deck, content)
            content = deck.topics.get(topic_no, content)
        else:
            topic_context, image_files = _render_upload_widget(topic_no, drug_case)

            st.markdown("##### 🤖 產生")
            if topic_no == 1:
                if st.button("📥 套用案件資料（0 Token）", key="import_topic1"):
                    new_content = TopicContent(
                        topic_no=1, title=content.title, reviewer_note=content.reviewer_note,
                        payload=structured_data.build_topic1_payload(drug_case),
                        is_ai_generated=False, is_human_edited=False,
                    )
                    deck.topics[1] = new_content
                    case_store.save_deck(deck)
                    st.success("已套用案件資料。")
                    st.rerun()
            else:
                already_has_content = content.is_ai_generated or content.is_human_edited
                btn_label = "🔄 重新產生本頁內容" if already_has_content else "🤖 AI 產生本頁內容"
                if st.button(btn_label, key=f"regen_{topic_no}", type="primary"):
                    counter = st.session_state.get("anim_group_counter", 0)
                    st.session_state["anim_group_counter"] = counter + 1
                    seedtree_placeholder = st.empty()
                    seedtree_placeholder.markdown(
                        ui_widgets.seed_tree_indicator(
                            f"AI 讀取主題 {topic_no} 資料中...", group_index=counter,
                        ),
                        unsafe_allow_html=True,
                    )
                    old_note = content.reviewer_note
                    try:
                        content = ai_engine.generate_topic_content(
                            topic_no, kb_local, drug_case, topic_context, hint,
                            image_paths=image_files,
                        )
                        content.reviewer_note = old_note
                        deck.topics[topic_no] = content
                        if topic_no == config.NUM_TOPICS and "_generation_error" not in content.payload:
                            deck.ten_grid = ai_engine.generate_ten_grid(content.payload)
                            deck.summary_points = content.payload.get("summary_points", [])
                            deck.review_history_note = content.payload.get("review_history_note", "")
                            ai_reco = content.payload.get("final_recommendation")
                            deck.final_recommendation = ai_reco or ai_engine.compute_recommendation(deck.ten_grid)
                        case_store.save_deck(deck)
                        seedtree_placeholder.empty()
                        st.success("已產生，請確認下方內容。")
                    except Exception as e:  # noqa: BLE001
                        seedtree_placeholder.empty()
                        st.error(f"生成失敗：{e}")

        st.markdown("##### 👁️ 預覽")
        st.markdown(
            topic_ui.render_slide_preview_html(topic_no, content.title or title_default, content.payload),
            unsafe_allow_html=True,
        )

        st.markdown("##### ✏️ 人工編輯")
        with st.form(key=f"edit_form_{topic_no}"):
            new_title = st.text_input("投影片標題", value=content.title or title_default, key=f"title_{topic_no}")
            new_payload = topic_ui.render_editable_form(topic_no, content.payload, key_prefix=f"field_{topic_no}")
            new_note = st.text_area(
                "🗒️ 審查備註（僅供內部工作紀錄，不會出現在簡報上；重新產生此頁時會保留）",
                value=content.reviewer_note, key=f"note_{topic_no}", height=70,
            )
            applied = st.form_submit_button("✅ 套用修改", type="primary")
            if applied:
                content.title = new_title
                content.payload = new_payload
                content.reviewer_note = new_note
                content.is_human_edited = True
                content.last_edited_by = getattr(auth.current_user(), "display_name", "")
                deck.topics[topic_no] = content
                case_store.save_deck(deck)
                st.success("已套用修改並儲存，上方預覽卡片已同步更新。")
                st.rerun()

        with st.expander("🛠️ 進階：原始 JSON（複雜的巢狀內容，或想整段貼上/複製時使用）"):
            edited_json = st.text_area(
                "內容（JSON）", value=_pretty_json(content.payload), height=200, key=f"json_{topic_no}",
            )
            if st.button("套用 JSON", key=f"apply_json_{topic_no}"):
                try:
                    content.payload = _json.loads(edited_json)
                    content.is_human_edited = True
                    content.last_edited_by = getattr(auth.current_user(), "display_name", "")
                    deck.topics[topic_no] = content
                    case_store.save_deck(deck)
                    st.success("已套用並儲存。")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"JSON 格式錯誤：{e}")


def render_case_workspace(drug_case: DrugCase) -> None:
    kb = data_loader.load_knowledge_base()
    deck = case_store.load_deck(drug_case.slug) or Deck(drug_case=drug_case)

    st.markdown("#### 2️⃣ 逐主題投餵資料 / 產生 / 編輯")
    outcome_hint = st.selectbox(
        "（選填）預期結論方向，協助 AI 選用對應語氣範例",
        ["自動判斷", "不須取代品項", "需取代品項", "建議比價"],
        help="對應語句範例庫三大類別；不確定可選『自動判斷』。",
    )
    hint = None if outcome_hint == "自動判斷" else outcome_hint

    for topic_no in range(1, config.NUM_TOPICS + 1):
        render_topic_section(topic_no, drug_case, deck, kb, hint)

    st.markdown("#### 3️⃣ 下載簡報")
    if st.button("📥 產生並下載 .pptx", type="primary"):
        try:
            topic1_files = case_store.uploads_dir(drug_case.slug, 1).rglob("*")
            cover_image_paths = {1: [p for p in topic1_files if p.suffix.lower() in utils.IMAGE_EXTS]}
            out_path = case_store.outputs_dir(drug_case.slug) / f"{drug_case.slug}_新進藥品評估.pptx"
            ppt_builder.build_deck_pptx(deck, kb, out_path, cover_image_paths)
            with open(out_path, "rb") as f:
                st.download_button(
                    "點此下載簡報（下載後仍可用 PowerPoint 手動編修）",
                    data=f.read(), file_name=out_path.name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
        except Exception as e:  # noqa: BLE001
            st.error(f"簡報產生失敗：{e}")


def _pretty_json(obj) -> str:
    return _json.dumps(obj, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tab 2：十宮格總覽
# ---------------------------------------------------------------------------

def render_ten_grid_tab(drug_case: DrugCase) -> None:
    st.markdown("### 🧭 十宮格總覽與人工覆核")
    deck = case_store.load_deck(drug_case.slug)
    if not deck or not deck.ten_grid:
        st.info("尚未產生主題 10（綜合評估）內容，請先於「新藥審查工作台」分頁產生簡報。")
        return

    cols = st.columns(5)
    for i, result in enumerate(deck.ten_grid):
        col = cols[i % 5]
        with col:
            st.markdown(f"**{result.item_name}**")
            light = st.selectbox(
                "燈號", [config.LIGHT_GREEN, config.LIGHT_YELLOW, config.LIGHT_RED, config.LIGHT_NA],
                index=[config.LIGHT_GREEN, config.LIGHT_YELLOW, config.LIGHT_RED, config.LIGHT_NA].index(result.light)
                if result.light in (config.LIGHT_GREEN, config.LIGHT_YELLOW, config.LIGHT_RED, config.LIGHT_NA) else 3,
                format_func=lambda x: f"{config.LIGHT_SYMBOL[x]} {config.LIGHT_LABEL[x]}",
                key=f"grid_light_{i}",
                label_visibility="collapsed",
            )
            rationale = st.text_input("判斷論述", value=result.rationale, key=f"grid_rat_{i}", label_visibility="collapsed")
            if light != result.light or rationale != result.rationale:
                result.light = light
                result.rationale = rationale
                result.is_human_overridden = True

    st.divider()
    reco = ai_engine.compute_recommendation(deck.ten_grid)
    st.metric("依十宮格自動推算之建議（僅供參考）", reco)

    deck.final_recommendation = st.selectbox(
        "最終審查結論（人工確認）",
        ["建議通過", "建議通過(但不常備)", "建議比價", "建議不通過"],
        index=["建議通過", "建議通過(但不常備)", "建議比價", "建議不通過"].index(deck.final_recommendation)
        if deck.final_recommendation in ["建議通過", "建議通過(但不常備)", "建議比價", "建議不通過"] else 0,
    )

    if st.button("儲存十宮格覆核結果", type="primary"):
        case_store.save_deck(deck)
        st.success("已儲存人工覆核結果。")


# ---------------------------------------------------------------------------
# Tab 3：後台管理（僅管理藥師/主管）
# ---------------------------------------------------------------------------

def render_admin_tab() -> None:
    st.markdown("### ⚙️ 後台管理")
    kb = data_loader.load_knowledge_base()

    st.markdown("#### Prompt 與判定門檻")
    overrides = ai_engine.load_admin_overrides()
    extra_prompt = st.text_area(
        "System Prompt 臨時追加指示（會附加在 Excel 規則之後，立即生效）",
        value=overrides.get("extra_system_prompt", ""), height=140,
    )
    threshold = st.slider(
        "十宮格「建議通過」綠圈門檻（預設 5，對應規則：10項評分≥5）",
        min_value=3, max_value=10, value=int(overrides.get("green_threshold", 5)),
    )
    if st.button("儲存後台設定", type="primary"):
        ai_engine.save_admin_overrides({"extra_system_prompt": extra_prompt, "green_threshold": threshold})
        st.success("已儲存，下次生成即套用新設定。")

    st.divider()
    st.markdown("#### 📚 知識庫內容檢視")
    t1, t2, t3, t4 = st.tabs(["主題架構規格", "決策邏輯與規則", "資料源", "廠商文件清單"])
    with t1:
        st.dataframe(
            [{"主題": t.topic_no, "頁數上限": t.max_pages, "標題": truncate(t.slide_title_template, 30),
              "AI目標": truncate(t.ai_goal, 60)} for t in kb.topic_specs],
            use_container_width=True,
        )
    with t2:
        st.dataframe(
            [{"類別": r.category, "項目": r.item, "內容": truncate(r.content, 80)} for r in kb.decision_rules],
            use_container_width=True,
        )
    with t3:
        st.dataframe(
            [{"主題": s.topic_no, "標題": s.slide_title, "資料源": truncate(s.sources_text, 80)} for s in kb.data_sources],
            use_container_width=True,
        )
    with t4:
        st.dataframe([{"項次": v.seq, "文件名稱": v.doc_name} for v in kb.vendor_docs], use_container_width=True)

    with st.expander(f"🗂 語句範例庫（{len(kb.example_snippets)} 則）"):
        for s in kb.example_snippets[:30]:
            st.markdown(f"**[{s.category} / {s.subcategory}]**\n\n{truncate(s.text, 200)}")

    st.divider()
    st.markdown("#### 👥 使用者 / 權限管理")
    users = auth.list_users()
    for uname, info in users.items():
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(uname)
        c2.write(info["display_name"])
        c3.write(info["role"])
        if uname != "admin" and c4.button("刪除", key=f"del_{uname}"):
            auth.delete_user(uname)
            st.rerun()

    with st.form("add_user_form"):
        st.caption("新增 / 更新使用者")
        u = st.text_input("帳號")
        d = st.text_input("顯示名稱")
        r = st.selectbox("角色", config.ALL_ROLES)
        pin = st.text_input("密碼/PIN", type="password")
        if st.form_submit_button("儲存使用者"):
            if u and pin:
                auth.upsert_user(u, d or u, r, pin)
                st.success(f"已儲存使用者 {u}")
                st.rerun()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("💊 新藥初審 AI 工作台")

    with st.sidebar:
        render_sidebar_kb_panel()
        user = auth.require_login_ui()

    if not user:
        st.info("請先於左側登入以使用系統。")
        st.caption("預設帳號：admin/admin（管理藥師）、pharmacist/user（一般使用者）— 請上線前務必修改。")
        return

    if user.role == config.ROLE_ADMIN:
        tab1, tab2, tab3 = st.tabs(["📋 新藥審查工作台", "🧭 十宮格總覽", "⚙️ 後台管理"])
    else:
        tab1, tab2 = st.tabs(["📋 新藥審查工作台", "🧭 十宮格總覽"])
        tab3 = None

    with tab1:
        drug_case = render_case_selector()
        st.session_state["current_case_slug"] = drug_case.slug
        st.divider()
        render_case_workspace(drug_case)

    with tab2:
        slug = st.session_state.get("current_case_slug")
        if slug:
            dc = case_store.load_drug_case(slug) or DrugCase(case_id=slug)
            render_ten_grid_tab(dc)
        else:
            st.info("請先於「新藥審查工作台」分頁選擇或建立案件。")

    if tab3 is not None:
        with tab3:
            render_admin_tab()


if __name__ == "__main__":
    main()
