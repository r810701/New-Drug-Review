# 💊 新藥初審 AI 工作台

以 Streamlit 建置的新藥審查藥師輔助工具。系統的「大腦」是 **【新藥審查AI】** 資料夾
（`kb_sample/`，正式環境請改指到共用網路資料夾），其中：

| 檔案 | 角色 |
|---|---|
| `新藥初審_AI_工作台模組.xlsx` | 最高指導原則：主題架構規格 / 決策邏輯與規則 / 資料源 / 廠商文件 |
| `母片.pptx` | 簡報母片（10 張投影片對應主題 1~10，決定視覺風格） |
| `投影片範例*.pdf/pptx` | 標準教材庫（排版參考） |
| `語句描述文字檔.txt` | 論述語氣 few-shot 範例（不須取代 / 需取代 / 建議比價 三大類） |

## 專案結構

```
app.py                      # Streamlit 入口（UI 組裝）
config.py                   # 全域路徑/角色/門檻等設定，唯一 source of truth
modules/
  schema.py                 # 資料結構（DrugCase / TopicContent / Deck / TenGridResult...）
  data_loader.py             # 知識庫讀取＋快取＋「🔄 載入最新資料庫」清快取邏輯
  ai_engine.py               # Prompt 組裝 + 呼叫 Claude + JSON 解析 + 十宮格自動判定
  ppt_builder.py             # 把 Deck 渲染成 .pptx（直接在母片的 10 張投影片上填值）
  case_store.py              # 案件/簡報內容本機端存取（JSON），可替換成資料庫
  auth.py                    # 角色權限（使用者 / 管理藥師）
  utils.py                   # 檔案指紋、PubMed/DOI 連結組裝、JSON 安全解析
kb_sample/                   # 【新藥審查AI】資料夾範例內容
data/                        # 執行期產生：使用者帳號、案件、上傳檔、輸出簡報
```

## 安裝與執行

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...           # 或於側邊欄輸入
export NEWDRUG_KB_DIR=/path/to/新藥審查AI     # 選填，預設用專案內 kb_sample
streamlit run app.py
```

預設帳號（**上線前務必於「後台管理→使用者管理」修改或刪除**）：

- `admin` / `admin`（管理藥師 / 主管）
- `pharmacist` / `user`（一般使用者）

## 功能對應需求

1. **自動化產生新藥審查簡報**：`ai_engine.generate_full_deck()` 依 Excel 規則逐主題生成結構化 JSON，
   `ppt_builder.build_deck_pptx()` 渲染成 pptx。
2. **人工編輯**：每個主題以 JSON 編輯框呈現，可直接改內容後「套用編輯」；十宮格另有專屬覆核 UI（分頁 2）。
3. **下載後仍可編輯**：輸出為標準 `.pptx`（繼承母片版型），PowerPoint 可直接開啟修改。
4. **一鍵快取清除與向量重整**：側邊欄「🔄 載入最新資料庫」（僅管理藥師可見），呼叫
   `data_loader.force_refresh_knowledge_base()`：清 `st.cache_data`/`st.cache_resource`，
   重新掃描 Excel、PDF 範例、語句文字檔，並顯示 `✅ 已載入 X 份範例、規則 X 條...` 狀態列。
5. **權限管理**：`modules/auth.py`，`config.ROLE_USER` / `config.ROLE_ADMIN` 兩種角色；
   後台分頁僅管理藥師可見。
6. **文獻/連結上傳與交換**：「2️⃣ 針對各主題投餵補充資料」區塊，逐主題上傳 PDF/圖片或貼連結，
   會併入該主題的 AI 生成 Prompt；AI 生成的文獻引用亦會依 Excel 規則自動組裝 PubMed/DOI 連結
   （`modules/utils.py: autolink_citation`）。

## 延伸/待辦（標註在程式碼內，方便後續維護者接手）

- `case_store.py` 目前用本機 JSON，正式上線建議換成資料庫（介面已抽象化，置換不影響 `app.py`）。
- `ppt_builder._render_generic_content_slide()`（主題 3~6）目前用程式化版面配置；
  若要更貼近人工排版範例的精緻度，可改為「先產生 python-pptx 版面 → 開放使用者拖拉調整」。
- `ai_engine.py` 的機轉圖 / HTA 圖表目前僅產生「文字描述」，尚未串接圖片生成或圖庫檢索；
  可在 `TOPIC_JSON_FIELDS[3]` 增加圖片 URL 欄位後，於 `ppt_builder` 讀取插入。
- 十宮格「國內同儕使用經驗」「LASA」等仰賴 Google 表單資料，目前由使用者於上傳區塊貼文字模擬，
  之後可接 Google Sheets API 直接讀取。
