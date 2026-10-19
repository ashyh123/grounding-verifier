"""T5 — the local review page. Human decisions only; this app never judges a label itself.

    uv run python -m annotation.review_app --round 1     # http://127.0.0.1:8100
    uv run python -m annotation.review_app --round 2     # the round-2 queue

Round 1 walks every claim of every draft case. Round 2 loads only the queue produced by
`annotation.round2_queue` and shows the round-1 decision next to the draft.

Every action appends one line to `data/annotation/decisions_round<N>.jsonl` (append-only: the file
is opened in "a" mode and never rewritten). The last line for a claim wins. Evidence selected in
the left pane is validated against the passage text server-side; a quote that is not verbatim is
rejected with a 422 rather than accepted and normalised.

Bound to 127.0.0.1, no auth, no network exposure.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import sources as S

DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"
ROUND2_QUEUE = S.ANNOTATION_DIR / "round2_queue.jsonl"
ZH_CACHE = S.ANNOTATION_DIR / "zh_cache.json"
PREREVIEW = S.ANNOTATION_DIR / "prereview.json"
TRIAGE = S.ANNOTATION_DIR / "triage.json"
VERDICTS = S.VERDICTS  # SUPPORTED | CONTRADICTED | UNSUPPORTED
ACTIONS = ("agree", "set_verdict", "delete", "split", "merge_previous")


def decisions_path(round_no: int) -> Path:
    return S.ANNOTATION_DIR / f"decisions_round{round_no}.jsonl"


# --------------------------------------------------------------------------- state

class Store:
    """Drafts + round-1 decisions + this round's decisions, read fresh on every request."""

    def __init__(self, round_no: int, needs_review: bool = False):
        self.round_no = round_no
        self.needs_review = needs_review
        self.drafts = [json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
                       if line.strip()] if DRAFTS.is_file() else []
        self.by_id = {c["id"]: c for c in self.drafts}
        self.round1 = _latest(decisions_path(1))
        self.current = _latest(self.path)

    @property
    def path(self) -> Path:
        """Resolved per access so tests (and a moved data dir) never pin a stale location."""
        return decisions_path(self.round_no)

    def queue(self) -> list[dict[str, Any]]:
        """The cases this round shows, in order."""
        if self.round_no == 1:
            return self.drafts
        if not ROUND2_QUEUE.is_file():
            return []
        queued = [json.loads(line) for line in ROUND2_QUEUE.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        cases = []
        seen: set[str] = set()
        for item in queued:
            case_id = item["case_id"]
            if case_id not in seen and case_id in self.by_id:
                seen.add(case_id)
                cases.append(self.by_id[case_id])
        return cases

    def claims(self, case: dict[str, Any]) -> list[dict[str, Any]]:
        """Claims of a case with the decisions applied (deleted ones dropped).

        In round 2 only the queued claims are shown; round 1 shows every claim.
        """
        wanted = self.queued_claim_ids() if self.round_no == 2 else None
        if self.needs_review:
            from .triage import by_case, load as load_triage
            triage = load_triage(TRIAGE, {})
            wanted = set(by_case(triage).get(case["id"], [])) if triage else set()
        out = []
        for claim in case.get("claims") or []:
            if wanted is not None and claim["claim_id"] not in wanted:
                continue
            decision = self.current.get(claim["claim_id"])
            if decision and decision["action"] == "delete":
                continue
            merged = dict(claim)
            if decision:
                merged["decision"] = decision
                merged["claim_text"] = decision.get("claim_text") or claim["claim_text"]
                merged["final_verdict"] = decision.get("verdict")
                merged["final_evidence"] = decision.get("evidence", claim.get("evidence") or [])
            else:
                merged["final_verdict"] = None
                merged["final_evidence"] = claim.get("evidence") or []
            if self.round_no == 2:
                merged["round1"] = self.round1.get(claim["claim_id"])
            out.append(merged)
        return out

    def queued_claim_ids(self) -> set[str]:
        """Claim ids of the round-2 queue; empty when there is no queue file."""
        if not ROUND2_QUEUE.is_file():
            return set()
        return {json.loads(line)["claim_id"]
                for line in ROUND2_QUEUE.read_text(encoding="utf-8").splitlines() if line.strip()}

    def progress(self, only_flagged: bool = False) -> dict[str, int]:
        total = done = 0
        for case in self.queue():
            for claim in self.claims(case):
                if only_flagged and not (claim.get("flags") or case.get("flags")):
                    continue
                total += 1
                if claim["claim_id"] in self.current:
                    done += 1
        return {"done": done, "total": total}


def _read_json(path: Path) -> dict[str, Any]:
    """Side file (translation cache, pre-review) or {} when it does not exist yet."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _latest(path: Path) -> dict[str, dict[str, Any]]:
    """claim_id -> last decision, for an append-only decisions file."""
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            out[record["claim_id"]] = record
    return out


# --------------------------------------------------------------------------- request bodies

class EvidenceIn(BaseModel):
    index: int
    start_char: int
    end_char: int


class DecisionIn(BaseModel):
    claim_id: str
    action: str
    claim_text: str | None = None
    verdict: str | None = None
    evidence: list[EvidenceIn] | None = None
    note: str = ""
    extra_claims: list[str] = Field(default_factory=list)


def validate_decision(store: Store, decision: DecisionIn) -> dict[str, Any]:
    """Check the decision against the draft and the passage text. Returns the record to append."""
    case = next((c for c in store.queue() if any(cl["claim_id"] == decision.claim_id
                                                 for cl in c.get("claims") or [])), None)
    if case is None:
        raise HTTPException(404, f"unknown claim_id {decision.claim_id!r}")
    if decision.action not in ACTIONS:
        raise HTTPException(422, f"unknown action {decision.action!r}; expected one of {ACTIONS}")
    if decision.verdict is not None and decision.verdict not in VERDICTS:
        raise HTTPException(422, f"unknown verdict {decision.verdict!r}; expected one of {VERDICTS}")

    claim = next(cl for cl in case["claims"] if cl["claim_id"] == decision.claim_id)
    passages = case["context_passages"]

    # "agree" and "split"/"merge" keep the draft as it stands: when the request carries no
    # evidence, the claim's own evidence is what is being accepted. Anything explicitly sent is
    # validated below, so a client cannot sneak a non-verbatim quote in by omitting the field.
    requested_evidence = decision.evidence
    if requested_evidence is None and decision.action in ("agree", "split", "merge_previous"):
        requested_evidence = [
            EvidenceIn(index=e["index"], start_char=e["start_char"], end_char=e["end_char"])
            for e in claim.get("evidence") or []
            if isinstance(e.get("start_char"), int) and isinstance(e.get("end_char"), int)
            and isinstance(e.get("index"), int)]
    evidence: list[dict[str, Any]] = []
    for item in requested_evidence or []:
        if not 0 <= item.index < len(passages):
            raise HTTPException(422, f"passage index {item.index} out of range")
        passage = passages[item.index]
        if not 0 <= item.start_char < item.end_char <= len(passage):
            raise HTTPException(422, f"character range {item.start_char}:{item.end_char} out of "
                                     f"bounds for passage {item.index}")
        quote = passage[item.start_char:item.end_char]
        if not quote.strip():
            raise HTTPException(422, "selected evidence is blank")
        evidence.append({"index": item.index, "start_char": item.start_char,
                         "end_char": item.end_char, "quote": quote})

    verdict = decision.verdict
    if decision.action == "agree":
        verdict = claim.get("draft_verdict")
    if decision.action in ("split", "merge_previous"):
        verdict = decision.verdict or claim.get("draft_verdict")
    if verdict is not None:
        verdict = S.normalize_verdict(verdict)  # SUPPORTED_CANDIDATE -> SUPPORTED, once, here
        if verdict not in VERDICTS:
            raise HTTPException(422, f"cannot record verdict {verdict!r}")
    if verdict == "UNSUPPORTED":
        evidence = []  # the invariant every downstream consumer relies on
    elif verdict in ("SUPPORTED", "CONTRADICTED") and not evidence:
        raise HTTPException(422, f"{verdict} needs at least one piece of verbatim evidence")

    record = {
        "claim_id": decision.claim_id,
        "case_id": case["id"],
        "action": decision.action,
        "claim_text": decision.claim_text if decision.claim_text is not None else claim["claim_text"],
        "verdict": verdict,
        "evidence": evidence,
        "note": decision.note,
        "extra_claims": decision.extra_claims,
        "round": store.round_no,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if decision.action == "delete":
        record["verdict"] = None
        record["evidence"] = []
    return record


def append_decision(store: Store, record: dict[str, Any]) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    with store.path.open("a", encoding="utf-8") as fh:  # append-only, never rewritten
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- page

def _e(text: str) -> str:
    return html.escape(text, quote=True)


def render_case(store: Store, case: dict[str, Any], index: int, total: int,
                only_flagged: bool) -> str:
    claims = store.claims(case)
    if only_flagged:
        claims = [c for c in claims if c.get("flags") or case.get("flags")]
    progress = store.progress(only_flagged)
    pct = 0 if not progress["total"] else round(100 * progress["done"] / progress["total"])
    claims_json = json.dumps(claims, ensure_ascii=False).replace("</", "<\\/")
    case_view = {
        "id": case["id"], "source": case["source"], "split": case["split"],
        "context_passages": case["context_passages"], "generated_answer": case["generated_answer"],
        "source_labels": case.get("source_labels") or {}, "truncated": case.get("truncated", False),
        "provenance": case.get("provenance") or {}, "flags": case.get("flags") or [],
    }
    case_json = json.dumps(case_view, ensure_ascii=False).replace("</", "<\\/")

    # Chinese and pre-review are display aids: shipped alongside the English, never merged into it.
    from .zh import text_key
    zh = _read_json(ZH_CACHE)
    texts = [case["generated_answer"], *(case["context_passages"] or [])]
    zh_view = {text_key(t): zh.get(text_key(t), {}).get("zh", "") for t in texts}
    suggestions = _read_json(PREREVIEW)
    triage = _read_json(TRIAGE)
    buckets = {c["claim_id"]: c for c in triage.get("claims", [])}
    claim_view = []
    for claim in claims:
        entry = dict(claim)
        entry["suggestion"] = suggestions.get(claim["claim_id"])
        entry["bucket"] = (buckets.get(claim["claim_id"]) or {}).get("bucket")
        entry["bucket_reasons"] = (buckets.get(claim["claim_id"]) or {}).get("reasons", [])
        entry["zh_claim"] = zh.get(text_key(claim["claim_text"]), {}).get("zh", "")
        claim_view.append(entry)
    claims_json = json.dumps(claim_view, ensure_ascii=False).replace("</", "<\\/")
    zh_json = json.dumps(zh_view, ensure_ascii=False).replace("</", "<\\/")

    return PAGE.replace("__CASE_JSON__", case_json) \
        .replace("__CLAIMS_JSON__", claims_json) \
        .replace("__ZH_JSON__", zh_json) \
        .replace("__CASE_ID__", _e(case["id"])) \
        .replace("__POSITION__", f"{index + 1}/{total}") \
        .replace("__PROGRESS__", f"{progress['done']}/{progress['total']} ({pct}%)") \
        .replace("__ROUND__", str(store.round_no)) \
        .replace("__ONLY_FLAGGED__", "checked" if only_flagged else "")


def render_index(store: Store) -> str:
    cases = store.queue()
    if not cases:
        message = ("no round-2 queue yet — run annotation.round2_queue first"
                   if store.round_no == 2 else "no drafts yet — run annotation.draft_claims first")
        return f"<!doctype html><meta charset=utf-8><p>{_e(message)}</p>"
    return render_case(store, cases[0], 0, len(cases), False)


def make_app(round_no: int, needs_review: bool = False) -> FastAPI:
    app = FastAPI(title=f"Annotation review, round {round_no}", docs_url=None, redoc_url=None)
    store = Store(round_no, needs_review=needs_review)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return render_index(store)

    @app.get("/case/{case_id}", response_class=HTMLResponse)
    def case_page(case_id: str, flagged: int = 0) -> str:
        queue = store.queue()
        ids = [c["id"] for c in queue]
        if case_id not in ids:
            raise HTTPException(404, f"unknown case {case_id!r}")
        return render_case(store, store.by_id[case_id], ids.index(case_id), len(queue),
                           bool(flagged))

    @app.get("/api/progress")
    def progress(flagged: int = 0) -> dict[str, Any]:
        return {**store.progress(bool(flagged)), "round": round_no}

    @app.post("/api/decision")
    def decide(decision: DecisionIn) -> dict[str, Any]:
        fresh = Store(round_no)  # a second tab may have appended since startup
        record = validate_decision(fresh, decision)
        append_decision(fresh, record)
        store.current[record["claim_id"]] = record
        return {"saved": True, "record": record,
                "progress": store.progress(False)}

    return app


# --------------------------------------------------------------------------- page template

PAGE = r"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Annotation review __ROUND__ — __CASE_ID__</title>
<style>
:root { --bg:#fbfbfa; --panel:#fff; --line:#d9d9d6; --ink:#222; --muted:#6b6b68;
        --hl:#ffe066; --blue:#cfe3ff; --red:#ffb3b3; --warn:#fff3bf; }
* { box-sizing:border-box; }
body { margin:0; font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       background:var(--bg); color:var(--ink); }
header { display:flex; gap:16px; align-items:center; padding:8px 14px; border-bottom:1px solid var(--line);
         background:var(--panel); position:sticky; top:0; z-index:5; flex-wrap:wrap; }
header .id { font-weight:600; }
header .meta { color:var(--muted); }
header .grow { flex:1; }
button { font:inherit; padding:4px 10px; border:1px solid var(--line); background:#fff; border-radius:5px;
         cursor:pointer; }
button:hover { background:#f0f0ee; }
button.primary { background:#1f6feb; border-color:#1f6feb; color:#fff; }
button.primary:hover { background:#1a5fd0; }
button:disabled { opacity:.45; cursor:default; }
main { display:grid; grid-template-columns:1fr 1fr 460px; gap:0; height:calc(100vh - 49px); }
section { overflow:auto; padding:12px 14px; border-right:1px solid var(--line); }
section:last-child { border-right:none; }
h3 { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
     margin:0 0 8px; }
.passage { margin:0 0 12px; white-space:pre-wrap; }
.passage .num { color:var(--muted); font-size:11px; display:block; }
mark.ev { background:var(--hl); }
mark.span { background:var(--blue); }
.ans { white-space:pre-wrap; }
.lab { background:transparent; border-bottom:2px solid var(--red); }
.lab .kind { font-size:10px; color:#a11; vertical-align:super; }
.card { border:1px solid var(--line); border-radius:8px; background:var(--panel); padding:12px; margin-bottom:12px; }
.card .claim { font-size:15px; margin-bottom:8px; white-space:pre-wrap; }
textarea { width:100%; min-height:56px; font:inherit; padding:6px; border:1px solid var(--line);
           border-radius:5px; }
.row { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }
.pill { font-size:11px; padding:1px 7px; border-radius:10px; background:#eee; color:#333; }
.pill.red { background:#ffd9d9; } .pill.yellow { background:#fff0b3; }
.pill.draft { background:#dbeafe; } .pill.model { background:#ede9fe; }
.pill.final { background:#dcfce7; }
.ev { font-size:12px; border-left:3px solid var(--hl); padding:2px 8px; margin:6px 0; color:#333; }
.ev button { padding:0 6px; font-size:11px; }
.flags { margin:8px 0; font-size:12px; }
.flag { padding:3px 6px; border-radius:4px; margin:3px 0; }
.flag.red { background:#ffe3e3; } .flag.yellow { background:#fff6cc; }
.note { color:var(--muted); font-size:12px; margin-top:6px; white-space:pre-wrap; }
.hint { color:var(--muted); font-size:12px; }
kbd { border:1px solid var(--line); border-bottom-width:2px; border-radius:3px; padding:0 4px; font-size:11px; }
#status { color:var(--muted); font-size:12px; }
.zh { margin-top:6px; padding:6px 8px; border-left:3px solid #b9d4ff; background:#f4f8ff;
      color:#1d3b66; font-size:13px; line-height:1.7; white-space:pre-wrap;
      font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; }
.zh-answer { margin-top:12px; }
.claim-zh { font-size:15px; }
.suggest { border:1px dashed #c9c9c4; border-radius:6px; padding:8px 10px; margin:10px 0;
           background:#fcfcfb; }
.pill.ok { background:#dcfce7; } .pill.bad { background:#ffd9d9; } .pill.warn { background:#fff0b3; }
.ev.small { font-size:12px; }
body.zh-hidden .zh { display:none; }
</style>
<header>
  <span class="id" id="case-id">__CASE_ID__</span>
  <span class="meta" id="case-meta"></span>
  <span class="grow"></span>
  <label class="hint"><input type="checkbox" id="zh-toggle" checked> 中文</label>
  <label class="hint"><input type="checkbox" id="only-flagged" __ONLY_FLAGGED__> 只看有问题的</label>
  <span id="progress">__PROGRESS__</span>
  <button id="prev" title="K">↑ 上一条</button>
  <button id="next" title="J">↓ 下一条</button>
  <span id="status"></span>
</header>
<main>
  <section id="context"><h3>上下文原文</h3><div id="context-body"></div></section>
  <section id="answer"><h3>模型回答</h3><div id="answer-body" class="ans"></div></section>
  <section id="claim"><h3>待判断的主张</h3><div id="card"></div>
    <div class="hint" style="margin-top:14px">
      <kbd>A</kbd> 同意 · <kbd>S</kbd> 有依据 · <kbd>C</kbd> 矛盾 · <kbd>U</kbd> 没说 ·
      <kbd>J</kbd>/<kbd>K</kbd> 下一条/上一条 · 在左栏划选文字即可加为证据
    </div>
  </section>
</main>
<script>
const CASE = __CASE_JSON__;
const CLAIMS = __CLAIMS_JSON__;
const ZH = __ZH_JSON__;          // sha256(english) -> 中文; display only
const zh = (t) => ZH[sha(t)] || '';
const ROUND = __ROUND__;
let currentId = null;   // the claim on screen, tracked by id: the visible list can change
let state = {};  // claim_id -> working copy

for (const c of CLAIMS) {
  state[c.claim_id] = {
    claim_text: c.claim_text,
    verdict: c.final_verdict || null,
    evidence: JSON.parse(JSON.stringify(c.final_evidence || [])),
    note: (c.decision && c.decision.note) || "",
    splitText: c.decision && c.decision.extra_claims ? c.decision.extra_claims : [],
    merged: !!(c.decision && c.decision.action === "merge_previous"),
  };
}

// --- sha256, sync: the keys are produced by annotation.zh.text_key (Python hashlib) ----------
const sha = (() => {
  const K = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  return (str) => {
    const bytes = new TextEncoder().encode(str);
    const len = bytes.length;
    const padded = new Uint8Array((((len + 9) >> 6) + 1) << 6);
    padded.set(bytes); padded[len] = 0x80;
    const view = new DataView(padded.buffer);
    view.setUint32(padded.length - 4, (len << 3) >>> 0);
    view.setUint32(padded.length - 8, Math.floor(len / 536870912));
    let H = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                             0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
    const W = new Uint32Array(64);
    for (let off = 0; off < padded.length; off += 64) {
      for (let i = 0; i < 16; i++) W[i] = view.getUint32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(W[i-15],7) ^ rotr(W[i-15],18) ^ (W[i-15] >>> 3);
        const s1 = rotr(W[i-2],17) ^ rotr(W[i-2],19) ^ (W[i-2] >>> 10);
        W[i] = (W[i-16] + s0 + W[i-7] + s1) >>> 0;
      }
      let [a,b,c,d,e,f,g,h] = H;
      for (let i = 0; i < 64; i++) {
        const S1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + S1 + ch + K[i] + W[i]) >>> 0;
        const S0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (S0 + maj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0;
        d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0]=(H[0]+a)>>>0; H[1]=(H[1]+b)>>>0; H[2]=(H[2]+c)>>>0; H[3]=(H[3]+d)>>>0;
      H[4]=(H[4]+e)>>>0; H[5]=(H[5]+f)>>>0; H[6]=(H[6]+g)>>>0; H[7]=(H[7]+h)>>>0;
    }
    return Array.from(H, (x) => x.toString(16).padStart(8, '0')).join('');
  };
})();

const el = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const VERDICT_ZH = {SUPPORTED: '有依据', CONTRADICTED: '与原文矛盾', UNSUPPORTED: '原文没说',
                    SUPPORTED_CANDIDATE: '候选有依据', NOT_SUPPORTED: '原文未支持'};
const verdictZh = (v) => VERDICT_ZH[v] || v || '—';
const ACTION_ZH = {agree: '同意', set_verdict: '改标签', delete: '删除（非事实主张）',
                   split: '拆成两条', merge_previous: '并入上一条'};
const actionZh = (a) => ACTION_ZH[a] || a;
const FLAG_ZH = {
  evidence_not_verbatim: '证据不是原文逐字',
  source_label_uncovered: '原数据集标的错误片段没落到任何主张上（拆漏了）',
  answer_not_covered: '回答里有一段没被任何主张覆盖',
  supported_without_evidence: '判了有依据，但找不到逐字证据',
  model_disagrees: '起草模型的判断与脚本不一致',
  evidence_truncated: '上下文被截断，支持证据可能被截掉',
  fragment_claim: '这条没有可核验的内容（残片）',
  duplicate_claim: '与同案例的另一条主张重复',
  no_pre_review: '还没有模型预审',
  random_audit_sample: '随机抽检样本',
};
const flagZh = (f) => FLAG_ZH[f] || f;
const reasonZh = (r) => {
  const base = r.split('(')[0];
  const inner = (r.match(/\(([^)]*)\)/) || [])[1] || '';
  const map = {models_disagree: '两个模型判断不一致', low_confidence: '模型置信度低',
               suggestion_evidence_not_verbatim: '模型给的证据不是逐字原文',
               suggestion_not_usable: '模型的建议不能直接采纳',
               claim_flagged: '这条主张有问题标记', case_flagged: '该案例有问题标记'};
  return (map[base] || base) + (inner ? `（${inner.replace('->', ' → ')}）` : '');
};
const SOURCE_ZH = {
  ragtruth_summary: 'RAGTruth 摘要', ragtruth_qa: 'RAGTruth 问答',
  ragtruth_data2txt: 'RAGTruth 数据转文本', factscore_instructgpt: 'FActScore (InstructGPT)',
  factscore_chatgpt: 'FActScore (ChatGPT)', factscore_perplexityai: 'FActScore (PerplexityAI)',
  halueval_summary: 'HaluEval 摘要',
};
const sourceZh = (s) => SOURCE_ZH[s] || s;
const flagged = () => el('only-flagged').checked;
const visible = () => CLAIMS.filter((c) => !flagged() || (c.flags && c.flags.length) || (CASE.flags && CASE.flags.length));

function meta() {
  const bits = [sourceZh(CASE.source), CASE.split === 'dev' ? '开发集' : '测试集',
                `第 ${ROUND} 轮`];
  if (CASE.provenance && CASE.provenance.generator_model) bits.push(CASE.provenance.generator_model);
  if (CASE.truncated) bits.push('上下文已截断');
  el('case-meta').textContent = bits.join(' · ');
}

function overlaps(a, b) { return a && b && a.start_char < b.end_char && b.start_char < a.end_char; }

function renderContext(claim) {
  let html = '';
  CASE.context_passages.forEach((p, i) => {
    const marks = [];
    for (const e of (claim ? state[claim.claim_id].evidence : [])) {
      if (e.index === i) marks.push([e.start_char, e.end_char, 'ev']);
    }
    const labels = (CASE.source_labels && CASE.source_labels.labels) || [];
    if (CASE.source === 'ragtruth_summary' || CASE.source === 'ragtruth_qa' || CASE.source === 'ragtruth_data2txt') {
      // upstream hallucination spans are on the answer, not the context
    }
    const zhText = zh(p);
    html += `<div class="passage" data-passage="${i}"><span class="num">passage ${i}</span>`
         + highlight(p, marks)
         + (zhText ? `<div class="zh" lang="zh-CN">${esc(zhText)}</div>` : '')
         + `</div>`;
  });
  el('context-body').innerHTML = html;
  const first = document.querySelector('mark.ev');
  if (first) first.scrollIntoView({block:'center'});
}

function highlight(text, marks) {
  const sorted = marks.slice().sort((a, b) => a[0] - b[0]);
  let out = '', cursor = 0;
  for (const [s, e, cls] of sorted) {
    if (s < cursor) continue;
    out += esc(text.slice(cursor, s)) + `<mark class="${cls}">` + esc(text.slice(s, e)) + `</mark>`;
    cursor = e;
  }
  return out + esc(text.slice(cursor));
}

function renderAnswer(claim) {
  const spans = [];
  if (claim && claim.answer_span) spans.push([claim.answer_span.start, claim.answer_span.end, 'span']);
  const labels = (CASE.source_labels && CASE.source_labels.labels) || [];
  const labelHtml = [];
  let cursor = 0, out = '';
  // Draw upstream hallucination spans and the current claim span over the answer text.
  const all = [];
  for (const l of labels) all.push([l.start, l.end, 'lab', l.label_type]);
  for (const s of spans) all.push(s);
  all.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  for (const [s, e, cls, kind] of all) {
    if (s < cursor) continue;
    out += esc(CASE.generated_answer.slice(cursor, s));
    out += cls === 'lab'
      ? `<span class="lab" title="${esc(kind)}">${esc(CASE.generated_answer.slice(s, e))}<span class="kind">${esc(kind)}</span></span>`
      : `<mark class="span">${esc(CASE.generated_answer.slice(s, e))}</mark>`;
    cursor = e;
  }
  out += esc(CASE.generated_answer.slice(cursor));
  const zhAnswer = zh(CASE.generated_answer);
  el('answer-body').innerHTML = out
    + (zhAnswer ? `<div class="zh zh-answer" lang="zh-CN">${esc(zhAnswer)}</div>` : '');
  const mark = document.querySelector('mark.span');
  if (mark) mark.scrollIntoView({block:'center'});
}

function flagsHtml(claim) {
  let out = '';
  for (const f of (CASE.flags || [])) {
    out += `<div class="flag ${f.level}">${f.level === 'red' ? '⛔' : '⚠️'} ${esc(flagZh(f.flag))}`
         + `<span class="hint"> — ${esc(f.detail)}</span></div>`;
  }
  for (const f of (claim.flags || [])) {
    out += `<div class="flag ${f.level}">${f.level === 'red' ? '⛔' : '⚠️'} ${esc(flagZh(f.flag))}`
         + `<span class="hint"> — ${esc(f.detail)}</span></div>`;
  }
  return out;
}

function renderCard(claim) {
  if (!claim) { el('card').innerHTML = '<p class="hint">当前筛选下没有主张。</p>'; return; }
  const st = state[claim.claim_id];
  const ev = st.evidence.map((e, n) =>
    `<div class="ev">p${e.index} [${e.start_char}:${e.end_char}] ${esc(e.quote)} ` +
    `<button data-rm="${n}" title="remove">✕</button></div>`).join('') || '<div class="hint">暂无证据</div>';
  const pills = [
    `<span class="pill draft">草稿：${esc(verdictZh(claim.draft_verdict))}</span>`,
    claim.model_verdict ? `<span class="pill model">起草模型：${esc(verdictZh(claim.model_verdict))}</span>` : '',
    st.verdict ? `<span class="pill final">你的决定：${esc(verdictZh(st.verdict))}</span>` : '',
    claim.needs_full_review ? '<span class="pill red">必须逐条人工判断</span>' : '',
    claim.tampered ? '<span class="pill yellow">起草模型认为被篡改</span>' : '',
    claim.upstream_label ? `<span class="pill">原数据集标注：${esc(claim.upstream_label)}</span>` : '',
  ].join(' ');
  const r1 = claim.round1 ? `<div class="note">第一轮：${esc(actionZh(claim.round1.action))}` +
    (claim.round1.verdict ? ` → ${esc(verdictZh(claim.round1.verdict))}` : '') +
    (claim.round1.note ? ` — ${esc(claim.round1.note)}` : '') + `</div>` : '';
  const sug = claim.suggestion;
  const sugHtml = sug ? `
    <div class="suggest">
      <div class="row"><strong>🤖 模型预审</strong>
        <span class="pill ${sug.verdict === 'SUPPORTED' ? 'ok' : sug.verdict === 'CONTRADICTED' ? 'bad' : 'warn'}">${esc(verdictZh(sug.verdict))}</span>
        <span class="pill">置信度 ${(sug.confidence * 100).toFixed(0)}%</span>
        <span class="pill ${sug.agrees_with_draft ? '' : 'warn'}">${sug.agrees_with_draft ? '与草稿一致' : '与草稿不一致'}</span>
      </div>
      ${sug.reasoning_zh ? `<div class="note" lang="zh-CN">${esc(sug.reasoning_zh)}</div>` : ''}
      ${(claim.bucket_reasons || []).length ? `<div class="note" lang="zh-CN">需要你判断的原因：` +
          esc(claim.bucket_reasons.map(reasonZh).join('、')) + `</div>` : ''}
      ${sug.evidence.length ? `<div class="ev small">建议证据：` + sug.evidence.map(e =>
          `p${e.index} ${esc(e.quote)}`).join(' · ') + `</div>` : ''}
      <div class="row">
        <button class="primary" id="accept-sug" ${sug.acceptable ? '' : 'disabled title="证据无法定位，不能直接采纳"'}>
          采纳建议（${esc(verdictZh(sug.verdict))}）</button>
        <span class="hint">采纳后仍会写一条人工决定</span>
      </div>
    </div>` : `<div class="hint">（该主张还没有模型预审建议：uv run python -m annotation.prereview --build）</div>`;
  const zhClaim = claim.zh_claim || zh(st.claim_text);
  el('card').innerHTML = `
    <div class="row">${pills}</div>
    <div class="card">
      <div class="claim">${esc(st.claim_text)}</div>
      ${zhClaim ? `<div class="zh claim-zh" lang="zh-CN">${esc(zhClaim)}</div>` : ''}
      ${sugHtml}
      <div class="flags">${flagsHtml(claim)}</div>
      ${claim.reasoning ? `<div class="note">起草说明：${esc(claim.reasoning)}</div>` : ''}
      ${r1}
      <h3 style="margin-top:10px">证据</h3>
      <div id="ev-list">${ev}</div>
      <div class="row">
        <button class="primary" data-act="agree">同意草稿 (A)</button>
        <button data-act="SUPPORTED">有依据 (S)</button>
        <button data-act="CONTRADICTED">与原文矛盾 (C)</button>
        <button data-act="UNSUPPORTED">原文没说 (U)</button>
      </div>
      <div class="row">
        <button data-act="delete">不是事实主张（删除）</button>
        <button data-act="split">拆成两条</button>
        <button data-act="merge_previous">并入上一条</button>
      </div>
      <textarea id="claim-text" placeholder="主张文字（可编辑）">${esc(st.claim_text)}</textarea>
      ${st.splitText.map((t, n) => `<textarea class="split-part" data-n="${n}">${esc(t)}</textarea>`).join('')}
      <textarea id="note" placeholder="备注（为什么改）">${esc(st.note)}</textarea>
      <div class="row"><button class="primary" id="save">保存决定</button>
        <span class="hint">保存后追加一行到 decisions_round${ROUND}.jsonl</span></div>
      <div id="err" class="flag red" style="display:none"></div>
    </div>`;
  el('claim-text').addEventListener('input', (e) => { st.claim_text = e.target.value; });
  el('note').addEventListener('input', (e) => { st.note = e.target.value; });
  el('ev-list').querySelectorAll('button[data-rm]').forEach((b) => {
    b.onclick = () => { st.evidence.splice(Number(b.dataset.rm), 1); render(); };
  });
  el('card').querySelectorAll('button[data-act]').forEach((b) => {
    b.onclick = () => act(b.dataset.act);
  });
  el('save').onclick = save;
  const acceptBtn = el('accept-sug');
  if (acceptBtn) acceptBtn.onclick = acceptSuggestion;
}

async function acceptSuggestion() {
  const claim = currentClaim();
  if (!claim || !claim.suggestion) return;
  const sug = claim.suggestion;
  const st = state[claim.claim_id];
  st.verdict = sug.verdict;
  st.evidence = sug.evidence.map((e) => ({...e}));
  if (sug.verdict === 'UNSUPPORTED') st.evidence = [];
  const note = (st.note ? st.note + ' | ' : '') + `采纳模型预审（${sug.model}，置信度 ${sug.confidence}）`;
  st.note = note;
  renderCard(claim);
  const ok = await save({action: 'set_verdict', verdict: sug.verdict, evidence: st.evidence, note});
  if (ok) next();
}

function currentIndex() {
  const list = visible();
  const found = list.findIndex((c) => c.claim_id === currentId);
  return { list, index: found >= 0 ? found : (list.length ? 0 : -1) };
}

function render() {
  const { list, index } = currentIndex();
  if (!list.length) { el('card').innerHTML = '<p class="hint">没有符合筛选条件的主张。</p>'; return; }
  const claim = list[index];
  currentId = claim.claim_id;
  el('case-id').textContent = CASE.id + ' · 第 ' + (index + 1) + '/' + list.length + ' 条';
  el('context-body').dataset.claim = claim.claim_id;
  renderContext(claim);
  renderAnswer(claim);
  renderCard(claim);
  el('progress').textContent = `${index + 1}/${list.length}`;
}

function currentClaim() {
  const { list, index } = currentIndex();
  return index >= 0 ? list[index] : null;
}

async function save(extra) {
  const claim = currentClaim();
  if (!claim) return false;
  const st = state[claim.claim_id];
  const payload = Object.assign({
    claim_id: claim.claim_id,
    action: 'set_verdict',
    claim_text: st.claim_text,
    verdict: st.verdict,
    evidence: st.evidence,
    note: st.note,
    extra_claims: st.splitText,
  }, extra || {});
  const res = await fetch('/api/decision', {method:'POST', headers:{'content-type':'application/json'},
                                            body: JSON.stringify(payload)});
  const body = await res.json();
  if (!res.ok) {
    const err = el('err');
    err.style.display = 'block';
    err.textContent = 'Rejected: ' + (body.detail || res.status);
    return false;
  }
  el('status').textContent = '已保存 ' + claim.claim_id;
  setTimeout(() => { el('status').textContent = ''; }, 1500);
  return true;
}

async function act(action) {
  const claim = currentClaim();
  if (!claim) return;
  const st = state[claim.claim_id];
  if (action === 'agree') {
    if (await save({action:'agree', verdict: null})) next();
    return;
  }
  if (['SUPPORTED','CONTRADICTED','UNSUPPORTED'].includes(action)) {
    st.verdict = action;
    if (action === 'UNSUPPORTED') st.evidence = [];
    renderCard(claim);
    if (await save({action:'set_verdict', verdict: action})) next();
    return;
  }
  if (action === 'delete') {
    if (await save({action:'delete'})) next();
    return;
  }
  if (action === 'split') {
    const text = st.claim_text;
    const mid = text.indexOf('. ');
    st.splitText = mid > 0 ? [text.slice(0, mid + 1), text.slice(mid + 2)] : [text, ''];
    renderCard(claim);
    el('status').textContent = '修改下面两段，然后点“保存决定”';
    return;
  }
  if (action === 'merge_previous') {
    st.merged = true;
    el('status').textContent = '保存后这条会并入上一条';
    if (await save({action:'merge_previous'})) next();
    return;
  }
}

function next() {
  const { list, index } = currentIndex();
  if (index + 1 < list.length) { currentId = list[index + 1].claim_id; render(); }
  else el('status').textContent = '已经是当前筛选的最后一条';
}
function prev() {
  const { list, index } = currentIndex();
  if (index > 0) { currentId = list[index - 1].claim_id; render(); }
  else el('status').textContent = '已经是当前筛选的第一条';
}

// Selecting text in the context pane adds it as evidence (validated by the server).
document.addEventListener('mouseup', () => {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return;
  const anchor = sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
  const pane = anchor && anchor.closest('#context-body');
  if (!pane) return;
  const block = anchor.closest('.passage');
  if (!block) return;
  const passageIndex = Number(block.dataset.passage);
  const text = CASE.context_passages[passageIndex];
  // Offsets are relative to the passage text itself, so the "passage N" label is skipped.
  const label = block.querySelector('.num');
  const offsetIn = (node, off) => {
    let total = 0;
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if (label && label.contains(n)) continue;
      if (n === node) return total + off;
      total += n.nodeValue.length;
    }
    return null;
  };
  const anchorNode = sel.anchorNode.nodeType === 3 ? sel.anchorNode : sel.anchorNode.firstChild;
  const focusNode = sel.focusNode.nodeType === 3 ? sel.focusNode : sel.focusNode.firstChild;
  if (!anchorNode || !focusNode) return;
  const start = offsetIn(anchorNode, sel.anchorOffset);
  const end = offsetIn(focusNode, sel.focusOffset);
  if (start === null || end === null) return;
  const [a, b] = start < end ? [start, end] : [end, start];
  let s = a, e = b;
  // Snap to non-space characters, then verify the quote is what the user selected.
  while (s < e && /\s/.test(text[s])) s += 1;
  while (e > s && /\s/.test(text[e - 1])) e -= 1;
  if (e - s < 2) return;
  const quote = text.slice(s, e);
  const claim = currentClaim();
  if (!claim) return;
  const st = state[claim.claim_id];
  if (!st.evidence.some((x) => x.index === passageIndex && x.start_char === s && x.end_char === e)) {
    st.evidence.push({index: passageIndex, start_char: s, end_char: e, quote});
    el('status').textContent = '已加入证据，正在保存…';
    save({action: 'set_verdict', verdict: claim.draft_verdict}).then((ok) => { if (ok) render(); });
  }
  sel.removeAllRanges();
});

el('next').onclick = next;
el('prev').onclick = prev;
el('only-flagged').onchange = () => { currentId = null; render(); };
el('zh-toggle').onchange = (e) => {
  document.body.classList.toggle('zh-hidden', !e.target.checked);
  try { localStorage.setItem('review-zh', e.target.checked ? '1' : '0'); } catch (_) {}
};
try {
  const saved = localStorage.getItem('review-zh');
  if (saved === '0') { el('zh-toggle').checked = false; document.body.classList.add('zh-hidden'); }
} catch (_) {}
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  const k = e.key.toLowerCase();
  if (k === 'j') next();
  else if (k === 'k') prev();
  else if (k === 'a') act('agree');
  else if (k === 's') act('SUPPORTED');
  else if (k === 'c') act('CONTRADICTED');
  else if (k === 'u') act('UNSUPPORTED');
});
meta();
render();
</script>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="T5: the local annotation review page")
    ap.add_argument("--round", type=int, choices=(1, 2), default=1)
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--needs-review", action="store_true",
                    help="show only the claims triage flagged for a human (+ the audit sample)")
    args = ap.parse_args()

    import uvicorn
    if not DRAFTS.is_file():
        raise SystemExit(f"STOP: {S.rel(DRAFTS)} not found; "
                         f"run annotation.draft_claims first.")
    if args.round == 2 and not ROUND2_QUEUE.is_file():
        raise SystemExit(f"STOP: {S.rel(ROUND2_QUEUE)} not found; "
                         f"run annotation.round2_queue first.")
    if args.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("STOP: the review page is local-only by design (spec T5); "
                         "use 127.0.0.1.")
    if args.needs_review and not TRIAGE.is_file():
        raise SystemExit(f"STOP: {S.rel(TRIAGE)} not found; run python -m annotation.triage first.")

    # Serving the review page never calls a model. Translation is an explicit CLI action.
    scope = " (only claims that need a human)" if args.needs_review else ""
    print(f"review round {args.round}: http://{args.host}:{args.port}{scope}  "
          f"(decisions -> {S.rel(decisions_path(args.round))})")
    uvicorn.run(make_app(args.round, needs_review=args.needs_review),
                host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
