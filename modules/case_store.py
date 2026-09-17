# -*- coding: utf-8 -*-
"""
modules/case_store.py
=======================
本機端「新藥申請案」存取層：每個案件一個資料夾（data/cases/<slug>/），內含
  - case.json      : DrugCase 基本資料
  - deck.json       : Deck（10 個主題內容 + 十宮格結果），人工編輯後也存回這裡
  - uploads/<topic>/: 使用者上傳的文獻 PDF、截圖、Google 表單連結文字檔
  - outputs/        : 產生好的 .pptx

正式環境若要接資料庫，只需要置換本檔案內部實作，對外函式簽章保持不變即可。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import config
from modules.schema import Deck, DrugCase, TenGridResult, TopicContent


def _case_dir(slug: str) -> Path:
    d = config.CASES_DIR / slug
    (d / config.UPLOADS_DIRNAME).mkdir(parents=True, exist_ok=True)
    (d / config.OUTPUT_DIRNAME).mkdir(parents=True, exist_ok=True)
    return d


def list_cases() -> list[str]:
    if not config.CASES_DIR.exists():
        return []
    return sorted(p.name for p in config.CASES_DIR.iterdir() if p.is_dir())


def save_drug_case(drug_case: DrugCase) -> None:
    d = _case_dir(drug_case.slug)
    payload = asdict(drug_case)
    payload["created_at"] = drug_case.created_at.isoformat()
    payload["updated_at"] = datetime.now().isoformat()
    (d / "case.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_drug_case(slug: str) -> DrugCase | None:
    f = _case_dir(slug) / "case.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    data.pop("created_at", None)
    data.pop("updated_at", None)
    return DrugCase(**data)


def save_deck(deck: Deck) -> None:
    d = _case_dir(deck.drug_case.slug)
    payload = {
        "final_recommendation": deck.final_recommendation,
        "summary_points": deck.summary_points,
        "review_history_note": deck.review_history_note,
        "ten_grid": [asdict(r) for r in deck.ten_grid],
        "topics": {
            str(no): {
                "topic_no": tc.topic_no,
                "title": tc.title,
                "payload": tc.payload,
                "citations": tc.citations,
                "is_ai_generated": tc.is_ai_generated,
                "is_human_edited": tc.is_human_edited,
                "last_edited_by": tc.last_edited_by,
                "reviewer_note": tc.reviewer_note,
            }
            for no, tc in deck.topics.items()
        },
    }
    (d / "deck.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    save_drug_case(deck.drug_case)


def load_deck(slug: str) -> Deck | None:
    drug_case = load_drug_case(slug)
    if drug_case is None:
        return None
    f = _case_dir(slug) / "deck.json"
    deck = Deck(drug_case=drug_case)
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        deck.final_recommendation = data.get("final_recommendation", "")
        deck.summary_points = data.get("summary_points", [])
        deck.review_history_note = data.get("review_history_note", "")
        deck.ten_grid = [TenGridResult(**r) for r in data.get("ten_grid", [])]
        for no_str, t in data.get("topics", {}).items():
            deck.topics[int(no_str)] = TopicContent(
                topic_no=t["topic_no"], title=t.get("title", ""),
                payload=t.get("payload", {}), citations=t.get("citations", []),
                is_ai_generated=t.get("is_ai_generated", False),
                is_human_edited=t.get("is_human_edited", False),
                last_edited_by=t.get("last_edited_by", ""),
                reviewer_note=t.get("reviewer_note", ""),
            )
    return deck


def uploads_dir(slug: str, topic_no: int) -> Path:
    d = _case_dir(slug) / config.UPLOADS_DIRNAME / str(topic_no)
    d.mkdir(parents=True, exist_ok=True)
    return d


def outputs_dir(slug: str) -> Path:
    return _case_dir(slug) / config.OUTPUT_DIRNAME


# ---------------------------------------------------------------------------
# 結構化匯入設定（主題2/9 的表單網址、篩選條件、欄位對應）
# 存起來是為了避免藥師每次都要重新輸入一模一樣的網址跟欄位對應設定。
# ---------------------------------------------------------------------------
def _structured_config_path(slug: str) -> Path:
    return _case_dir(slug) / "structured_sources.json"


def save_structured_source(slug: str, topic_no: int, cfg: dict) -> None:
    path = _structured_config_path(slug)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[str(topic_no)] = cfg
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_structured_source(slug: str, topic_no: int) -> dict:
    path = _structured_config_path(slug)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get(str(topic_no), {})
