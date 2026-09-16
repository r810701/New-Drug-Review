# -*- coding: utf-8 -*-
"""
modules/ppt_builder.py
========================
把 schema.Deck（AI 生成 + 人工編輯後的內容）渲染成真正的 .pptx 檔案。

核心策略：
  - 直接以【母片.pptx】為畫布（10 張投影片剛好對應主題 1~10，版面/字型/配色
    完全繼承母片，符合「排版與視覺原則：完全依照投影片範例與母片的風格」）。
  - 主題 1、2、7、8、9、10 母片內已經有現成表格/資訊盒，用「依內容鍵值填格」的
    方式寫入，盡量保留母片原本的儲存格樣式。
  - 主題 3、4、5、6 母片只有標題，屬於「自由版面」主題，用共用的
    `_render_generic_content_slide()` 依 payload 動態畫出：重點摘要框、
    資料表格、結論強調框、右下角出處小字（對應 Excel「出處規範」）。
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Pt

import config
from modules.schema import Deck, KnowledgeBase, TopicContent

ACCENT_RED = RGBColor(0xA6, 0x1E, 0x2B)
TEXT_DARK = RGBColor(0x22, 0x22, 0x22)
BOX_FILL = RGBColor(0xF4, 0xE9, 0xEA)


# ---------------------------------------------------------------------------
# 低階小工具
# ---------------------------------------------------------------------------
def _set_cell_text(cell, text: str, *, size: int = 12, bold: bool = False,
                    color: Optional[RGBColor] = None, align=PP_ALIGN.LEFT) -> None:
    cell.text = "" if text is None else str(text)
    for para in cell.text_frame.paragraphs:
        para.alignment = align
        for run in para.runs:
            run.font.size = Pt(size)
            run.font.bold = bold
            if color:
                run.font.color.rgb = color
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE


def _add_textbox(slide, left, top, width, height, text: str, *, size=12,
                  bold=False, color=TEXT_DARK, align=PP_ALIGN.LEFT, wrap=True):
    box = slide.shapes.add_textbox(Emu(left), Emu(top), Emu(width), Emu(height))
    tf = box.text_frame
    tf.word_wrap = wrap
    lines = str(text).split("\n") if text else [""]
    for i, line in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = line
        para.alignment = align
        for run in para.runs:
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = color
    return box


def _add_table(slide, left, top, width, height, data: list[list[str]], *,
                header_rows: int = 1, header_fill=ACCENT_RED, header_font_color=RGBColor(255, 255, 255),
                body_size=11, header_size=11):
    rows, cols = len(data), len(data[0]) if data else 0
    shape = slide.shapes.add_table(rows, cols, Emu(left), Emu(top), Emu(width), Emu(height))
    table = shape.table
    for r, row_vals in enumerate(data):
        for c, val in enumerate(row_vals):
            is_header = r < header_rows
            cell = table.cell(r, c)
            _set_cell_text(
                cell, val,
                size=header_size if is_header else body_size,
                bold=is_header,
                color=header_font_color if is_header else TEXT_DARK,
                align=PP_ALIGN.CENTER if is_header else PP_ALIGN.LEFT,
            )
            if is_header:
                cell.fill.solid()
                cell.fill.fore_color.rgb = header_fill
    return table


def _find_shape(slide, name_contains: str = None, has_table: bool = False):
    for shp in slide.shapes:
        if has_table and not shp.has_table:
            continue
        if name_contains and name_contains not in shp.name:
            continue
        return shp
    return None


def _set_title(slide, text: str) -> None:
    for shp in slide.shapes:
        if shp.is_placeholder and shp.placeholder_format.idx == 0:
            shp.text_frame.text = text
            return
        if shp.is_placeholder and "標題" in shp.name:
            shp.text_frame.text = text
            return


# ---------------------------------------------------------------------------
# 主題 1：封面
# ---------------------------------------------------------------------------
def _fill_topic1_cover(slide, content: TopicContent, image_paths: list[Path]) -> None:
    p = content.payload
    _set_title(slide, f"新進藥品評估-{content.title or ''}".strip())

    name_block = "\n".join(
        filter(None, [p.get("trade_name_en", ""), p.get("trade_name_zh", ""), p.get("generic_name", "")])
    )
    _add_textbox(
        slide, left=500000, top=1000000, width=8100000, height=1200000,
        text=name_block, size=22, bold=True, align=PP_ALIGN.CENTER,
    )

    # 藥品照片：等比縮放並排於下半部（若使用者有上傳）
    if image_paths:
        n = min(len(image_paths), 4)
        gap = 150000
        total_w = 9144000 - 2 * 500000
        img_w = (total_w - gap * (n - 1)) // n
        left = 500000
        top = 2500000
        img_h = 2200000
        for i, img_path in enumerate(image_paths[:n]):
            try:
                slide.shapes.add_picture(str(img_path), Emu(left), Emu(top), width=Emu(img_w), height=Emu(img_h))
            except Exception:
                pass
            left += img_w + gap
    else:
        _add_textbox(
            slide, 500000, 2600000, 8100000, 800000,
            f"（建議上傳藥品照片：{p.get('photo_notes', '外盒/鋁箔袋/針劑本體/裸錠正反面')}）",
            size=12, align=PP_ALIGN.CENTER, color=RGBColor(0x99, 0x99, 0x99),
        )


# ---------------------------------------------------------------------------
# 主題 2：申請總表
# ---------------------------------------------------------------------------
def _fill_topic2_table(slide, content: TopicContent) -> None:
    p = content.payload
    _set_title(slide, "申請總表")
    tbl_shape = _find_shape(slide, has_table=True)
    if not tbl_shape:
        return
    table = tbl_shape.table

    drug_name = f"{p.get('generic_name', '')}"
    row1 = [
        drug_name,
        p.get("strength_form", ""),
        p.get("moa", ""),
        p.get("nhi_price", ""),
        p.get("needs_replace", ""),
        "、".join(p.get("similar_drugs", []) or []),
    ]
    for c, val in enumerate(row1):
        _set_cell_text(table.cell(1, c), val, size=11)

    _set_cell_text(table.cell(2, 0), "衛福部適應症", size=11, bold=True)
    _set_cell_text(table.cell(2, 3), f"申請理由 (提藥醫師：{p.get('applicant_physician', '')})",
                    size=11, bold=True)
    reason = "\n".join(f"• {x}" for x in (p.get("application_reason") or []))
    _set_cell_text(table.cell(3, 0), p.get("indication", ""), size=10)
    _set_cell_text(table.cell(3, 3), reason, size=10)

    if p.get("replace_candidates"):
        note = "須取代藥品：" + "、".join(p["replace_candidates"])
        _add_textbox(slide, 366551, 4550000, 8410897, 400000, note, size=10, color=ACCENT_RED)


# ---------------------------------------------------------------------------
# 主題 3~6：自由版面內容頁（機轉 / 指引 / 文獻 / 安全性）
# ---------------------------------------------------------------------------
def _render_generic_content_slide(slide, topic_no: int, content: TopicContent) -> None:
    p = content.payload
    _set_title(slide, content.title or config.NUM_TOPICS and "")

    top = 1050000
    if topic_no == 3:  # 療效-機轉
        _add_textbox(slide, 400000, top, 8300000, 900000, p.get("moa_summary", ""), size=14)
        _add_textbox(slide, 400000, top + 1000000, 8300000, 2400000,
                     f"【建議機轉圖/生理圖】\n{p.get('moa_diagram_desc', '')}",
                     size=12, color=RGBColor(0x66, 0x66, 0x66))
        citation = p.get("citation", "")

    elif topic_no == 4:  # 療效-指引
        rows = p.get("guideline_rows", [])
        data = [["學會/國家", "年份", "治療順位", "代表藥品(學名)"]]
        for r in rows:
            data.append([
                r.get("country_or_society", ""), r.get("year", ""),
                r.get("treatment_line", ""), "、".join(r.get("drug_examples", []) or []),
            ])
        if len(data) > 1:
            _add_table(slide, 400000, top, 8300000, 400000 * len(data), data)
        _add_textbox(slide, 400000, top + 400000 * len(data) + 150000, 8300000, 500000,
                     p.get("summary", ""), size=13, bold=True)
        citation = ""

    elif topic_no in (5, 6):  # 療效-文獻 / 安全性
        trials = p.get("trials", [])[:2]  # 一張投影片最多 2 個試驗（Excel 規則）
        col_w = 8300000 // max(len(trials), 1)
        left = 400000
        for trial in trials:
            _add_textbox(
                slide, left, top, col_w - 100000, 1400000,
                f"{trial.get('trial_name', '')}\n({trial.get('citation', '')})\n"
                f"{trial.get('design', '')}\n{trial.get('population', '')}\n{trial.get('regimen', '')}",
                size=11,
            )
            if topic_no == 5:
                rows = [["Endpoint", "藥A", "藥B", "P值"]]
                for kr in trial.get("key_results", []):
                    rows.append([kr.get("endpoint", ""), kr.get("value_a", ""),
                                 kr.get("value_b", ""), kr.get("p_value", "")])
            else:
                rows = [["項目", "藥A", "藥B"]]
                for adr in trial.get("adr_table", []):
                    rows.append([adr.get("category", ""), adr.get("drug_a", ""), adr.get("drug_b", "")])
            if len(rows) > 1:
                _add_table(slide, left, top + 1450000, col_w - 100000, 250000 * len(rows), rows, body_size=10, header_size=10)
            box_top = top + 1450000 + 250000 * len(rows) + 100000
            _add_textbox(slide, left, box_top, col_w - 100000, 500000,
                         trial.get("conclusion_box", ""), size=12, bold=True, color=ACCENT_RED)
            left += col_w
        citation = "; ".join(t.get("citation", "") for t in trials)
    else:
        citation = ""

    if citation:
        _add_textbox(slide, 5800000, 4750000, 3200000, 300000, citation,
                     size=9, color=RGBColor(0x77, 0x77, 0x77), align=PP_ALIGN.RIGHT)


# ---------------------------------------------------------------------------
# 主題 7：醫療科技評估（HTA）
# ---------------------------------------------------------------------------
def _fill_topic7_table(slide, content: TopicContent) -> None:
    p = content.payload
    _set_title(slide, "醫療科技評估")
    tbl_shape = _find_shape(slide, has_table=True)
    if not tbl_shape:
        return
    table = tbl_shape.table
    rows = p.get("hta_rows", [])
    if not rows:
        _set_cell_text(table.cell(1, 0), p.get("note_if_missing", "查無資料"), size=11)
        return

    needed_rows = len(rows) + 1
    while len(table.rows) < needed_rows:
        # python-pptx 沒有原生 add_row API 前的相容處理：透過 XML 複製最後一列
        tr = table._tbl.tr_lst[-1]
        new_tr = copy.deepcopy(tr)
        table._tbl.append(new_tr)

    for i, row in enumerate(rows, start=1):
        _set_cell_text(table.cell(i, 0), row.get("agency", ""), size=11)
        _set_cell_text(table.cell(i, 1), row.get("year", ""), size=11, align=PP_ALIGN.CENTER)
        _set_cell_text(table.cell(i, 2), row.get("verdict", ""), size=11, align=PP_ALIGN.CENTER)
        _set_cell_text(table.cell(i, 3), row.get("key_findings", ""), size=10)


# ---------------------------------------------------------------------------
# 主題 8：藥品比較
# ---------------------------------------------------------------------------
def _fill_topic8_table(slide, content: TopicContent) -> None:
    p = content.payload
    _set_title(slide, "藥品比較")
    tbl_shape = _find_shape(slide, has_table=True)
    if not tbl_shape:
        return
    table = tbl_shape.table
    columns = p.get("columns", ["申請藥品", "暫定取代藥品"])
    _set_cell_text(table.cell(0, 1), columns[0] if len(columns) > 0 else "", bold=True, align=PP_ALIGN.CENTER)
    if len(columns) > 1:
        _set_cell_text(table.cell(0, 2), columns[1] if len(columns) > 1 else "", bold=True, align=PP_ALIGN.CENTER)

    field_row_map = {"藥名": 1, "適應症": 2, "差異": 3, "建議劑量": 4, "健保價": 5, "每日藥價": 6, "月均用量": 7}
    for row in p.get("rows", []):
        r_idx = field_row_map.get(row.get("field", ""))
        if r_idx is None:
            continue
        values = row.get("values", [])
        bold_idx = set(row.get("bold_advantage_idx", []))
        for c, val in enumerate(values[: len(table.columns) - 1], start=1):
            is_adv = (c - 1) in bold_idx
            cell = table.cell(r_idx, c)
            _set_cell_text(cell, val, size=10, bold=is_adv)
            if is_adv:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xF7, 0xD9, 0xA8)  # 橘底標記優勢


# ---------------------------------------------------------------------------
# 主題 9：臨床使用意見
# ---------------------------------------------------------------------------
def _fill_topic9_table(slide, content: TopicContent) -> None:
    p = content.payload
    _set_title(slide, "臨床使用意見")
    info = p.get("info_box", {})
    for shp in slide.shapes:
        if not shp.has_table:
            continue
        table = shp.table
        headers = [table.cell(0, c).text for c in range(len(table.columns))]
        if "醫師意見" in headers:
            site_map = {o.get("site", ""): o for o in p.get("site_opinions", [])}
            for r in range(1, len(table.rows)):
                site = table.cell(r, 0).text.strip()
                o = site_map.get(site, {})
                _set_cell_text(table.cell(r, 1), o.get("physician_opinion", ""), size=11)
                _set_cell_text(table.cell(r, 2), o.get("pharmacist_opinion", ""), size=11)
        elif "申請藥品" in headers:
            _set_cell_text(table.cell(1, 0), info.get("applied_drug", ""), size=11, align=PP_ALIGN.CENTER)
            _set_cell_text(table.cell(1, 1), info.get("replace_drug", ""), size=11, align=PP_ALIGN.CENTER)
            _set_cell_text(table.cell(1, 2), info.get("similar_drug", ""), size=11, align=PP_ALIGN.CENTER)
            _set_cell_text(table.cell(2, 0), f"主要開立科別：{info.get('main_department', '')}", size=10)


# ---------------------------------------------------------------------------
# 主題 10：綜合評估（十宮格）
# ---------------------------------------------------------------------------
def _fill_topic10_table(slide, deck: Deck) -> None:
    _set_title(slide, "綜合評估")
    for shp in slide.shapes:
        if not shp.has_table:
            continue
        table = shp.table
        headers_r0 = [table.cell(0, c).text for c in range(len(table.columns))]

        # 十宮格本體（5 x 2 個評估項目 + 高警訊/LASA/歷年審議/綜合意見 列）
        if "文獻證明療效" in headers_r0[0]:
            by_idx = {r.item_index: r for r in deck.ten_grid}
            for i in range(10):
                r, c = (0, i) if i < 5 else (1, i - 5)
                result = by_idx.get(i)
                light = result.light if result else config.LIGHT_NA
                symbol = config.LIGHT_SYMBOL.get(light, "—")
                rationale = f"\n({result.rationale})" if result and result.rationale else ""
                cell = table.cell(r, c)
                _set_cell_text(cell, f"{symbol}{rationale}", size=9, align=PP_ALIGN.CENTER)
                cell.fill.solid()
                rgb = config.LIGHT_RGB.get(light, (255, 255, 255))
                # 淡化底色，避免蓋掉文字可讀性
                cell.fill.fore_color.rgb = RGBColor(*[min(255, v + 120) for v in rgb])
            _set_cell_text(table.cell(2, 1), "非高警訊藥品" if not deck.summary_points else
                            table.cell(2, 1).text, size=10)
            _set_cell_text(table.cell(3, 1), deck.review_history_note, size=10)
            summary_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(deck.summary_points))
            _set_cell_text(table.cell(4, 1), summary_text, size=10)

        # 建議通過 / 建議比價 / 建議不通過
        elif "建議通過" in headers_r0:
            col_map = {"建議通過": 0, "建議比價": 1, "建議不通過": 2}
            reco = deck.final_recommendation or ""
            for label, idx in col_map.items():
                mark = "✔" if label in reco else ""
                _set_cell_text(table.cell(1, idx), mark, size=16, bold=True, align=PP_ALIGN.CENTER)

        # 右上角資訊盒
        elif "申請藥品" in headers_r0:
            t2_content = deck.topics.get(2)
            t9_content = deck.topics.get(9)
            if t2_content:
                p2 = t2_content.payload
                _set_cell_text(table.cell(1, 0), p2.get("generic_name", ""), size=10, align=PP_ALIGN.CENTER)
                _set_cell_text(table.cell(1, 1), "、".join(p2.get("replace_candidates", []) or []),
                                size=10, align=PP_ALIGN.CENTER)
                _set_cell_text(table.cell(1, 2), "、".join(p2.get("similar_drugs", []) or []),
                                size=10, align=PP_ALIGN.CENTER)


# ---------------------------------------------------------------------------
# 對外主函式
# ---------------------------------------------------------------------------
TOPIC_DISPATCH_SIMPLE = {1, 2, 7, 8, 9, 10}


def build_deck_pptx(
    deck: Deck,
    kb: KnowledgeBase,
    output_path: Path,
    image_paths_by_topic: Optional[dict[int, list[Path]]] = None,
    master_pptx_path: Path = config.MASTER_PPTX_PATH,
) -> Path:
    """把整份 Deck 渲染成 pptx 檔，回傳輸出路徑。"""
    image_paths_by_topic = image_paths_by_topic or {}
    prs = Presentation(str(master_pptx_path))
    slides = list(prs.slides)

    for topic_no in range(1, config.NUM_TOPICS + 1):
        if topic_no - 1 >= len(slides):
            break
        slide = slides[topic_no - 1]
        content = deck.topics.get(topic_no)
        if content is None:
            continue

        if topic_no == 1:
            _fill_topic1_cover(slide, content, image_paths_by_topic.get(1, []))
        elif topic_no == 2:
            _fill_topic2_table(slide, content)
        elif topic_no in (3, 4, 5, 6):
            _render_generic_content_slide(slide, topic_no, content)
        elif topic_no == 7:
            _fill_topic7_table(slide, content)
        elif topic_no == 8:
            _fill_topic8_table(slide, content)
        elif topic_no == 9:
            _fill_topic9_table(slide, content)
        elif topic_no == 10:
            _fill_topic10_table(slide, deck)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    return output_path
