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
from modules import ai_engine, auth, case_store, data_loader, ppt_builder
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
            st.caption(f"使用模型：`{config.DEFAULT_MODEL}`")
        else:
            key = st.text_input(
                "Gemini API Key",
                value=st.session_state.get("gemini_api_key", os.environ.get(config.GEMINI_API_KEY_ENV, "")),
                type="password",
                help="於 Google AI Studio 申請：https://aistudio.google.com/app/apikey"
                "；部署到內網時建議改用環境變數 GEMINI_API_KEY。",
            )
            st.session_state["gemini_api_key"] = key
            st.caption(f"使用模型：`{config.DEFAULT_GEMINI_MODEL}`")


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


def render_upload_section(drug_case: DrugCase) -> dict[int, str]:
    """讓使用者針對每個主題拖拉上傳文獻/貼上 Google 表單連結；回傳彙整後的文字上下文。"""
    st.markdown("#### 2️⃣ 針對各主題投餵補充資料（可選）")
    st.caption("可上傳文獻 PDF、截圖，或直接貼上 Google 表單/雲端連結；AI 會優先參考您提供的資料。")
    kb = data_loader.load_knowledge_base()
    user_context: dict[int, str] = {}

    cols = st.columns(2)
    for topic_no in range(1, config.NUM_TOPICS + 1):
        spec = kb.topic(topic_no)
        title = spec.slide_title_template.split("\n")[0] if spec else f"主題{topic_no}"
        with cols[(topic_no - 1) % 2].expander(f"主題 {topic_no}：{title}"):
            files = st.file_uploader(
                "上傳檔案（PDF / 圖片）", type=["pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True, key=f"upl_{drug_case.slug}_{topic_no}",
            )
            link_text = st.text_area(
                "或貼上連結/文字（Google 表單彙整、通訊錄、網址等）",
                key=f"link_{drug_case.slug}_{topic_no}", height=80,
            )
            saved_paths = []
            if files:
                target_dir = case_store.uploads_dir(drug_case.slug, topic_no)
                for f in files:
                    p = target_dir / f.name
                    p.write_bytes(f.getbuffer())
                    saved_paths.append(str(p))
            ctx_parts = []
            if saved_paths:
                ctx_parts.append("使用者上傳檔案：" + "、".join(Path(p).name for p in saved_paths))
            if link_text.strip():
                ctx_parts.append(link_text.strip())
            user_context[topic_no] = "\n".join(ctx_parts)
    return user_context


def render_generate_and_edit(drug_case: DrugCase, user_context: dict[int, str]) -> None:
    st.markdown("#### 3️⃣ 產生 / 編輯簡報內容")
    kb = data_loader.load_knowledge_base()

    deck = case_store.load_deck(drug_case.slug) or Deck(drug_case=drug_case)

    outcome_hint = st.selectbox(
        "（選填）預期結論方向，協助 AI 選用對應語氣範例",
        ["自動判斷", "不須取代品項", "需取代品項", "建議比價"],
        help="對應語句範例庫三大類別；不確定可選『自動判斷』。",
    )
    hint = None if outcome_hint == "自動判斷" else outcome_hint

    b1, b2 = st.columns([1, 1])
    if b1.button("🤖 一鍵產生全份簡報（AI）", type="primary", use_container_width=True):
        progress = st.progress(0.0, text="準備中...")

        def _cb(topic_no: int, content: TopicContent) -> None:
            progress.progress(topic_no / config.NUM_TOPICS, text=f"已完成主題 {topic_no}/{config.NUM_TOPICS}")

        try:
            deck = ai_engine.generate_full_deck(kb, drug_case, user_context, progress_callback=_cb)
            case_store.save_deck(deck)
            st.success("AI 已完成全份簡報初稿，請於下方逐頁校對。")
        except Exception as e:  # noqa: BLE001
            st.error(f"生成失敗：{e}")
        progress.empty()

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

        with st.expander(f"📑 主題 {topic_no}：{title}", expanded=False):
            gen_col, _ = st.columns([1, 3])
            if gen_col.button("只重新產生這頁", key=f"regen_{topic_no}"):
                try:
                    content = ai_engine.generate_topic_content(
                        topic_no, kb_local, drug_case, user_context.get(topic_no, ""), hint
                    )
                    deck.topics[topic_no] = content
                    case_store.save_deck(deck)
                    st.success("已重新產生，請確認下方內容。")
                except Exception as e:  # noqa: BLE001
                    st.error(f"生成失敗：{e}")

            edited_json = st.text_area(
                "內容（JSON，可直接編輯後按下方『套用編輯』）",
                value=_pretty_json(content.payload), height=220, key=f"json_{topic_no}",
            )
            if st.button("套用編輯", key=f"apply_{topic_no}"):
                import json as _json
                try:
                    content.payload = _json.loads(edited_json)
                    content.is_human_edited = True
                    content.last_edited_by = getattr(auth.current_user(), "display_name", "")
                    deck.topics[topic_no] = content
                    case_store.save_deck(deck)
                    st.success("已套用並儲存。")
                except Exception as e:  # noqa: BLE001
                    st.error(f"JSON 格式錯誤：{e}")

    st.markdown("#### 4️⃣ 下載簡報")
    if st.button("📥 產生並下載 .pptx", type="primary"):
        try:
            image_paths_by_topic = {
                1: list(case_store.uploads_dir(drug_case.slug, 1).glob("*"))
            }
            out_path = case_store.outputs_dir(drug_case.slug) / f"{drug_case.slug}_新進藥品評估.pptx"
            ppt_builder.build_deck_pptx(deck, kb_local, out_path, image_paths_by_topic)
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
        user_context = render_upload_section(drug_case)
        st.divider()
        render_generate_and_edit(drug_case, user_context)

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
