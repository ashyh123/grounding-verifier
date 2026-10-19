"""Local bilingual human-note form. Records opinions for later English revision, never gold.

Run: python -m annotation.adjudication --port 8101
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLAIM = "ragtruth-9775-c19"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    start: int
    end: int
    quote: str = Field(min_length=1, max_length=10000)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text_zh: str = Field(min_length=1, max_length=4000)
    verdict: Literal["SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "UNCERTAIN"]
    reason_zh: str = Field(default="", max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)


class Notes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str
    stage: Literal["first_judgment", "revision_notes"]
    first_judgment: Literal["SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "UNCERTAIN"] | None = None
    action: Literal["keep", "split", "defer"] | None = None
    items: list[Item] = Field(default_factory=list, max_length=20)
    upstream_note_zh: str = Field(default="", max_length=6000)


class ReviewFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str
    source_sha256: str
    outcome: Literal["agree", "change", "uncertain"]
    comment_zh: str = Field(default="", max_length=6000)


def make_app(drafts: Path = ROOT / "data/annotation/drafts.jsonl",
             translations: Path = ROOT / "data/annotation/adjudication_zh.json",
             notes_path: Path = ROOT / "data/annotation/adjudication_notes.jsonl",
             reviews_path: Path = ROOT / "data/annotation/pilot5_review_20261020.jsonl",
             feedback_path: Path = ROOT / "data/annotation/pilot_review_feedback.jsonl",
             decisions_path: Path = ROOT / "data/annotation/decisions_round1.jsonl") -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)
    token = secrets.token_urlsafe(24)

    def review_material():
        if not reviews_path.is_file() or not drafts.is_file():
            raise HTTPException(404, "尚未准备好本轮结果。")
        raw = drafts.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        reviews = [json.loads(line) for line in reviews_path.read_text().splitlines() if line.strip()]
        if any(r["source_sha256"] != digest for r in reviews):
            raise HTTPException(409, "建议对应的原稿已变化，请先重新核对材料。")
        cases = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        return reviews, cases, digest

    @app.get("/reviewed-pilot", response_class=HTMLResponse)
    def reviewed_pilot():
        reviews, cases, digest = review_material()
        feedback = {}
        if feedback_path.is_file():
            for line in feedback_path.read_text().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    if entry["source_sha256"] == digest:
                        feedback[entry["review_id"]] = entry
        decisions = {}
        if decisions_path.is_file():
            for line in decisions_path.read_text().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    decisions[entry["claim_id"]] = entry
        confirmed = [d for d in decisions.values() if d.get("author") == "user"
                     and d.get("label_source") == "human_adjudicated" and d.get("source_sha256") == digest
                     and d.get("verdict") in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED")]
        payload = {"reviews": reviews, "cases": [{k: c[k] for k in
                   ("id", "source", "context_passages", "generated_answer", "source_labels")} for c in cases],
                   "feedback": feedback, "confirmed": confirmed, "source_sha256": digest}
        template = Path(__file__).with_name("pilot_review.html").read_text()
        html = template.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))
        return HTMLResponse(html.replace("__NONCE__", token), headers={"Cache-Control": "no-store",
            "Content-Security-Policy": f"default-src 'self'; script-src 'nonce-{token}'; style-src 'nonce-{token}'; connect-src 'self'; frame-ancestors 'none'"})

    @app.post("/api/pilot-review-feedback")
    def save_review_feedback(body: ReviewFeedback, request: Request):
        if request.headers.get("x-form-token") != token:
            raise HTTPException(403, "请从本地结果页保存意见。")
        reviews, _, digest = review_material()
        review = next((r for r in reviews if r["review_id"] == body.review_id), None)
        if body.source_sha256 != digest or review is None:
            raise HTTPException(409, "材料或建议已变化，请重新打开结果页。")
        if body.outcome == "change" and not body.comment_zh.strip():
            raise HTTPException(422, "请写下这条需要修改的地方。")
        record = {**body.model_dump(), "id": str(uuid4()), "saved_at": datetime.now(timezone.utc).isoformat(),
                  "case_id": review["case_id"], "claim_id": review["claim_id"], "author": "user",
                  "scope": "human_review_feedback_not_materialized_gold", "first_judgment": None,
                  "first_judgment_status": "not_collected_before_showing_assistant_review"}
        feedback_path.parent.mkdir(parents=True, exist_ok=True)
        with feedback_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"saved_id": record["id"], "outcome": record["outcome"]}

    def find(claim_id):
        if not drafts.is_file() or not translations.is_file():
            raise HTTPException(404, "尚未准备好本地裁决材料。")
        raw = drafts.read_bytes()
        for line in raw.decode().splitlines():
            case = json.loads(line)
            for claim in case["claims"]:
                if claim["claim_id"] == claim_id:
                    zh = json.loads(translations.read_text())[case["id"]]
                    if zh["context_sha256"] != hashlib.sha256(json.dumps(case["context_passages"], ensure_ascii=False).encode()).hexdigest():
                        raise HTTPException(409, "英文材料已变化，请先更新中文对照。")
                    if (zh["claim_text"] != claim["claim_text"] or zh["answer_sha256"] != hashlib.sha256(case["generated_answer"].encode()).hexdigest()):
                        raise HTTPException(409, "主张或回答已变化，请先更新中文对照。")
                    return case, claim, zh, hashlib.sha256(raw).hexdigest()
        raise HTTPException(404, "找不到这条主张。")

    def history(claim_id, digest):
        if not notes_path.exists():
            return []
        return [r for line in notes_path.read_text().splitlines() if line.strip()
                if (r := json.loads(line))["claim_id"] == claim_id and r["source_sha256"] == digest]

    def upstream(case, claim, zh):
        return {"labels": claim["overlapping_source_labels"],
                "upstream_verdict": claim.get("upstream_verdict"), "note_zh": zh["upstream_note_zh"]}

    @app.get("/")
    def home():
        return RedirectResponse(f"/adjudicate/{DEFAULT_CLAIM}")

    @app.get("/adjudicate/{claim_id}", response_class=HTMLResponse)
    def page(claim_id: str):
        case, claim, zh, digest = find(claim_id)
        saved = history(claim_id, digest)
        first = next((r for r in saved if r["stage"] == "first_judgment"), None)
        latest = next((r for r in reversed(saved) if r["stage"] == "revision_notes"), None)
        payload = {"case_id": case["id"], "claim_id": claim_id, "source_sha256": digest,
                   "claim_text": claim["claim_text"], "claim_zh": zh["claim_zh"],
                   "passages": case["context_passages"], "passages_zh": zh["passages_zh"],
                   "passage_titles": zh["passage_titles"], "answer": case["generated_answer"],
                   "answer_zh": zh["answer_zh"], "first_judgment": first["first_judgment"] if first else None,
                   "latest": latest, "upstream": upstream(case, claim, zh) if first else None}
        template = Path(__file__).with_name("adjudication.html").read_text()
        html = template.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))
        html = html.replace("__NONCE__", token)
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "Content-Security-Policy":
            f"default-src 'self'; script-src 'nonce-{token}'; style-src 'nonce-{token}'; connect-src 'self'; frame-ancestors 'none'"})

    @app.post("/api/notes/{claim_id}")
    def save(claim_id: str, body: Notes, request: Request):
        if request.headers.get("x-form-token") != token:
            raise HTTPException(403, "请从本地裁决页面保存。")
        case, claim, zh, digest = find(claim_id)
        if body.source_sha256 != digest:
            raise HTTPException(409, "材料已更新，请重新打开页面，保留你的输入后再核对。")
        saved = history(claim_id, digest)
        first = next((r for r in saved if r["stage"] == "first_judgment"), None)
        if body.stage == "first_judgment":
            if body.first_judgment is None:
                raise HTTPException(422, "请先选择你的判断，拿不准也可以。")
            if first:
                return {"saved_id": first["id"], "first_judgment": first["first_judgment"],
                        "upstream": upstream(case, claim, zh)}
        else:
            if not first:
                raise HTTPException(409, "请先记录第一判断。")
            if body.action is None or not body.items or (body.action == "split" and len(body.items) < 2):
                raise HTTPException(422, "请选择处理方式，并填写主张；拆分至少需要两条。")
            if body.action == "keep" and len(body.items) != 1:
                raise HTTPException(422, "保留一条时只填写一条主张。")
            for item in body.items:
                if not item.text_zh.strip():
                    raise HTTPException(422, "主张内容不能为空白。")
                for evidence in item.evidence:
                    if (not 0 <= evidence.index < len(case["context_passages"])
                            or not 0 <= evidence.start < evidence.end <= len(case["context_passages"][evidence.index])
                            or case["context_passages"][evidence.index][evidence.start:evidence.end] != evidence.quote):
                        raise HTTPException(422, "引用必须是英文上下文中的精确原文，请重新划选。")
        record = {**body.model_dump(), "id": str(uuid4()), "case_id": case["id"], "claim_id": claim_id,
                  "saved_at": datetime.now(timezone.utc).isoformat(), "author": "user",
                  "first_judgment": first["first_judgment"] if first else body.first_judgment,
                  "prior_upstream_exposure": True,
                  "status": "pending_english_revision" if body.stage == "revision_notes" else "first_judgment_recorded",
                  "scope": "human_notes_only_not_gold"}
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        with notes_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"saved_id": record["id"], "first_judgment": record["first_judgment"],
                "upstream": upstream(case, claim, zh)}

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--notes", type=Path, default=ROOT / "data/annotation/adjudication_notes.jsonl")
    args = parser.parse_args()
    uvicorn.run(make_app(notes_path=args.notes), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
