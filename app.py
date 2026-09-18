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
                    f"**{row['項目']}**　最後修改：{row['最後修改時間']}　"
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
      - image_paths_by_topic：JPG/PNG 檔案路徑（不做文字擷取，交給 AI 以視覺方式直接辨識）
    一律以磁碟上『該案件/該主題』資料夾內容為準（不只看這次新選的檔案），
    避免換頁、重新整理、或按「只重新產生這頁」時，先前上傳的檔案被當作沒上傳過。
    """
    st.markdown("#### 2️⃣ 針對各主題投餵補充資料（可選）")
    st.caption(
        "支援 PDF、Word (.docx)、Excel (.xlsx)、CSV、純文字檔、圖片 (JPG/PNG)，"
        "或直接貼上 Google 表單/雲端連結；AI 會優先參考您提供的資料。"
    )
    kb = data_loader.load_knowledge_base()
    user_context: dict[int, str] = {}
    image_paths_by_topic: dict[int, list[Path]] = {}

    cols = st.columns(2)
    for topic_no in range(1, config.NUM_TOPICS + 1):
        spec = kb.topic(topic_no)
        title = spec.slide_title_template.split("\n")[0] if spec else f"主題{topic_no}"
        with cols[(topic_no - 1) % 2].expander(f"主題 {topic_no}：{title}"):
            files = st.file_uploader(
                "上傳檔案（PDF / Word / Excel / CSV / 圖片）",
                type=["pdf", "docx", "xlsx", "csv", "txt", "md", "png", "jpg", "jpeg"],
                accept_multiple_files=True, key=f"upl_{drug_case.slug}_{topic_no}",
            )
            link_text = st.text_area(
                "或貼上連結/文字（Google 表單彙整、通訊錄、網址等）",
                key=f"link_{drug_case.slug}_{topic_no}", height=80,
            )

            target_dir = case_store.uploads_dir(drug_case.slug, topic_no)
            if files:
                for f in files:
                    (target_dir / f.name).write_bytes(f.getbuffer())

            # 一律重新掃描磁碟上的檔案（含這次新上傳＋先前已存在的），確保不會「上傳過但沒被用到」
            all_files = sorted(target_dir.glob("*")) if target_dir.exists() else []
            doc_files = [p for p in all_files if p.suffix.lower() not in utils.IMAGE_EXTS]
            image_files = [p for p in all_files if p.suffix.lower() in utils.IMAGE_EXTS]

            ctx_parts = []
            for p in doc_files:
                # 修正：先前這裡只丟檔名給 AI，AI 從未讀過檔案內容，
                # 導致引用文獻/數據是模型憑訓練知識腦補，與使用者實際上傳的文獻不符。
                # 主題7的HTA報告篇幅長，改用關鍵字智慧擷取，避免真正的決策段落
                # 埋在文件中後段、被單純的「頭部截斷」漏掉。
                extracted = utils.extract_text_from_upload(p, keywords=config.TOPIC7_HTA_KEYWORDS if topic_no == 7 else None,)
                ctx_parts.append(f"== 使用者上傳檔案：{p.name} ==\n{extracted}")
                is_note = extracted.startswith("（") and extracted.endswith("）")
                if is_note:
                    st.caption(f"⚠️ {p.name}：{extracted}")
                else:
                    st.caption(f"✅ 已擷取「{p.name}」文字內容（{len(extracted)} 字元），將提供給 AI 參考")

            for p in image_files:
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
                    # 連結以外的純文字說明（例如使用者順手寫的備註）也一併保留
                    non_url_text = utils.strip_urls(link_text)
                    if non_url_text:
                        ctx_parts.append(f"== 使用者補充文字 ==\n{non_url_text}")
                else:
                    ctx_parts.append(f"== 使用者補充文字 ==\n{link_text.strip()}")

            user_context[topic_no] = "\n\n".join(ctx_parts)
            image_paths_by_topic[topic_no] = image_files
    return user_context, image_paths_by_topic


def _render_structured_import_block(
    topic_no: int, drug_case: DrugCase, deck: Deck, content: TopicContent, kb_local,
) -> None:
    """
    主題 1/2/9 專用：完全不呼叫 LLM 的結構化資料匯入 UI。
    取代原本「只重新產生這頁」的 AI 按鈕，改成「貼網址/套用案件資料 → 匯入」，
    0 token 消耗，且保證逐字不改（尤其主題9的 Google 表單臨床意見）。
    """
    if topic_no == 1:
        st.caption("封面內容直接沿用建立案件時填寫的英文/中文商品名，不需要、也不會呼叫 AI。")
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
        return

    # 主題2、9 共用：Google 試算表/表單網址 + 篩選 + 欄位對應，設定會存起來下次不用重填
    saved_cfg = case_store.load_structured_source(drug_case.slug, topic_no)
    default_map = config.TOPIC2_DEFAULT_COLUMN_MAP if topic_no == 2 else config.TOPIC9_DEFAULT_COLUMN_MAP
    source_label = "廠商/醫師填寫的新進藥品申請表" if topic_no == 2 else "各院區藥師填寫的臨床意見 Google 表單"

    st.caption(
        f"資料來源：{source_label}（Google 試算表連結）。系統會逐欄對應寫入，"
        "**完全不經過 AI 改寫**，原文長怎樣就長怎樣。"
    )
    sheet_url = st.text_input(
        "Google 試算表網址", value=saved_cfg.get("sheet_url", ""), key=f"struct_url_{topic_no}",
        help="需設定「知道連結的人皆可檢視」權限，系統才抓得到內容。",
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
            {"sheet_url": sheet_url, "filter_col": filter_col, "filter_val": filter_val, "column_map": column_map},
        )
        if not sheet_url.strip():
            st.warning("請先貼上 Google 試算表網址。")
        else:
            fetched = utils.fetch_url_content(sheet_url, max_chars=40000)
            if fetched.startswith("（") and fetched.endswith("）"):
                st.error(f"抓取失敗：{fetched}")
            else:
                rows = structured_data.parse_csv_text(fetched)
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


def render_generate_and_edit(
    drug_case: DrugCase, user_context: dict[int, str],
    image_paths_by_topic: dict[int, list[Path]],
) -> None:
    st.markdown("#### 3️⃣ 產生 / 編輯簡報內容")
    kb = data_loader.load_knowledge_base()

    deck = case_store.load_deck(drug_case.slug) or Deck(drug_case=drug_case)

    outcome_hint = st.selectbox(
        "（選填）預期結論方向，協助 AI 選用對應語氣範例",
        ["自動判斷", "不須取代品項", "需取代品項", "建議比價"],
        help="對應語句範例庫三大類別；不確定可選『自動判斷』。",
    )
    hint = None if outcome_hint == "自動判斷" else outcome_hint

    ai_topic_total = config.NUM_TOPICS - len(config.SKIP_LLM_TOPICS)  # 目前是 7（1/2/9 走結構化匯入）

    b1, b2 = st.columns([1, 1])
    if b1.button(f"🤖 一鍵產生 AI 主題（{ai_topic_total} 題，主題1/2/9 不耗用額度）",
                 type="primary", use_container_width=True):
        dog_placeholder = st.empty()
        dog_placeholder.markdown(
            ui_widgets.dog_digging_progress(0, f"已完成 0/{ai_topic_total} 個 AI 主題"),
            unsafe_allow_html=True,
        )
        status_area = st.empty()
        failed_topics: list[int] = []
        done_count = {"n": 0}

        def _cb(topic_no: int, content: TopicContent) -> None:
            ok = "_generation_error" not in content.payload
            done_count["n"] += 1
            if not ok:
                failed_topics.append(topic_no)
            label = (
                f"{'✅' if ok else '❌'} 已完成主題 {topic_no}/{config.NUM_TOPICS}"
                + ("（有主題失敗，將繼續產生其他主題）" if failed_topics else "")
            )
            dog_placeholder.markdown(
                ui_widgets.dog_digging_progress(topic_no / config.NUM_TOPICS * 100, label),
                unsafe_allow_html=True,
            )

        def _save(d: Deck) -> None:
            # 修正：原本失敗會讓已成功的主題整批遺失。現在每完成一個主題就立刻存檔，
            # 就算後面某個主題因為 API 配額/網路問題失敗，前面已成功的內容也不會不見，
            # 之後只需要對失敗的主題按「只重新產生這頁」，不用整份重打、浪費 API 額度。
            case_store.save_deck(d)

        deck = ai_engine.generate_full_deck(
            kb, drug_case, user_context, progress_callback=_cb,
            image_paths_by_topic=image_paths_by_topic,
            existing_deck=deck, save_callback=_save,
        )
        # 完成畫面（叼骨頭搖尾巴）留著不清掉，讓使用者看到「做完了」的回饋，
        # 不像原本進度條會直接消失、有點沒頭沒尾的感覺。

        if failed_topics:
            failed_str = "、".join(str(n) for n in failed_topics)
            status_area.warning(
                f"⚠️ 已完成 {ai_topic_total - len(failed_topics)}/{ai_topic_total} 個 AI 主題，"
                f"主題 {failed_str} 生成失敗（常見原因：API 配額用盡、網路逾時）。"
                "已成功的主題已經存檔，不需要重打；請展開下方對應主題，"
                "等一下再按「只重新產生這頁」個別重試即可。"
            )
        else:
            status_area.success(
                f"✅ {ai_topic_total} 個 AI 主題已完成初稿，請於下方逐頁校對。"
                "（主題1/2/9 請往下用「結構化匯入」，不需要也不會耗用 AI 額度）"
            )

    if b2.button("💾 儲存目前編輯內容", use_container_width=True):
        case_store.save_deck(deck)
        st.success("已儲存。")

    if not deck.topics:
        st.info("尚未產生內容，請先點擊上方「一鍵產生全份簡報」，或於下方個別主題手動產生。")

    kb_local = kb
    for topic_no in range(1, config.NUM_TOPICS + 1):
        spec = kb_local.topic(topic_no)
        title = spec.slide_title_template.split("\n")[0] if spec else f"主題{topic_no}"
        content = deck.topics.get(topic_no, TopicContent(topic_no=topic_no, title=title))

        has_error = "_generation_error" in content.payload
        status_icon = "❌ " if has_error else ("✅ " if content.is_ai_generated or content.is_human_edited else "")
        with st.expander(f"📑 {status_icon}主題 {topic_no}：{title}", expanded=has_error):
            if has_error:
                st.error(f"上次生成失敗：{content.payload['_generation_error']}")
            if topic_no in config.SKIP_LLM_TOPICS:
                _render_structured_import_block(topic_no, drug_case, deck, content, kb_local)
                content = deck.topics.get(topic_no, content)  # 匯入按鈕可能已更新 deck，重新取最新內容
            else:
                gen_col, _ = st.columns([1, 3])
                if gen_col.button("只重新產生這頁", key=f"regen_{topic_no}"):
                    seedtree_placeholder = st.empty()
                    seedtree_placeholder.markdown(
                        ui_widgets.seed_tree_indicator(f"AI 讀取主題 {topic_no} 資料中..."),
                        unsafe_allow_html=True,
                    )
                    old_note = content.reviewer_note  # 重新產生不該把藥師之前寫的審查備註洗掉
                    try:
                        content = ai_engine.generate_topic_content(
                            topic_no, kb_local, drug_case, user_context.get(topic_no, ""), hint,
                            image_paths=image_paths_by_topic.get(topic_no),
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
                        st.success("已重新產生，請確認下方內容。")
                    except Exception as e:  # noqa: BLE001
                        seedtree_placeholder.empty()
                        st.error(f"生成失敗：{e}")

            # ---- 1. 視覺化投影片預覽卡片 ----
            st.markdown(
                topic_ui.render_slide_preview_html(topic_no, content.title or title, content.payload),
                unsafe_allow_html=True,
            )

            # ---- 2. 人性化表單編輯（不碰 JSON/大括號） ----
            with st.form(key=f"edit_form_{topic_no}"):
                st.markdown("##### ✏️ 簡易編輯模式")
                new_title = st.text_input("投影片標題", value=content.title or title, key=f"title_{topic_no}")
                new_payload = topic_ui.render_editable_form(
                    topic_no, content.payload, key_prefix=f"field_{topic_no}"
                )
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
                    "內容（JSON）", value=_pretty_json(content.payload),
                    height=220, key=f"json_{topic_no}",
                )
                if st.button("套用 JSON", key=f"apply_json_{topic_no}"):
                    import json as _json
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

    st.markdown("#### 4️⃣ 下載簡報")
    if st.button("📥 產生並下載 .pptx", type="primary"):
        try:
            # 封面圖片只抓主題1資料夾內「真的是圖片」的檔案，避免同資料夾若有人誤傳 PDF/Word
            # 也被當成封面照片塞進 add_picture() 而噴錯。
            topic1_files = case_store.uploads_dir(drug_case.slug, 1).glob("*")
            cover_image_paths = {1: [p for p in topic1_files if p.suffix.lower() in utils.IMAGE_EXTS]}
            out_path = case_store.outputs_dir(drug_case.slug) / f"{drug_case.slug}_新進藥品評估.pptx"
            ppt_builder.build_deck_pptx(deck, kb_local, out_path, cover_image_paths)
            with open(out_path, "rb") as f:
                st.download_button(
                    "點此下載簡報（下載後仍可用 PowerPoint 手動編修）",
                    data=f.read(), file_name=out_path.name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
        except Exception as e:  # noqa: BLE001
            st.error(f"簡報產生失敗：{e}")


def _pretty_json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)


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
        user_context, image_paths_by_topic = render_upload_section(drug_case)
        st.divider()
        render_generate_and_edit(drug_case, user_context, image_paths_by_topic)

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
