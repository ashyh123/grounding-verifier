"""HTTP layer. Only maps requests/errors; all logic lives in the verifiers."""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .baseline import BaselineVerifier
from .config import describe
from .llm import UpstreamError, build_client
from .llm_verifiers import MinimalVerifier, OptimizedVerifier
from .schemas import VerifyRequest, VerifyResponse
from .validate import check_response_invariants

log = logging.getLogger("verifier")
app = FastAPI(title="Citation Grounding Verifier")
_verifiers: dict = {}


def get_verifier(method: str):
    if method not in _verifiers:
        if method == "baseline":
            _verifiers[method] = BaselineVerifier()
        elif method == "minimal":
            _verifiers[method] = MinimalVerifier(build_client())
        elif method == "optimized":
            _verifiers[method] = OptimizedVerifier(build_client())
        else:
            raise ValueError(method)
    return _verifiers[method]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(RequestValidationError)
async def _bad_request(_: Request, exc: RequestValidationError):
    return _error(422, "invalid_request", str(exc.errors()[:3]))


@app.get("/health")
async def health():
    """Also reports which provider/model/key the process actually loaded (no secrets)."""
    return {"status": "ok"} | describe()


@app.post("/verify", response_model=VerifyResponse, response_model_exclude_none=True)
async def verify(req: VerifyRequest,
                 method: str = Query(default=os.environ.get("VERIFIER_METHOD", "optimized"),
                                     pattern="^(baseline|minimal|optimized)$"),
                 include_meta: bool = False):
    try:
        result = await get_verifier(method).verify(req)
    except UpstreamError as e:
        log.warning("upstream failure: %s", e)
        return _error(504 if e.timeout else 502, "upstream_error", str(e))
    except KeyError as e:  # e.g. VERIFIER_MODEL / ANTHROPIC_API_KEY not set
        return _error(500, "misconfigured", f"missing setting {e}")

    violations = check_response_invariants(req.context_passages, result.claims)
    if violations:  # should be impossible; never return an invalid report
        log.error("invariant violations: %s", violations)
        return _error(500, "internal_invariant_violation", "; ".join(violations[:3]))
    if not include_meta:
        result.meta = None
    return result
