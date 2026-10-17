from fastapi.testclient import TestClient

from verifier import api
from verifier.llm import UpstreamError

from .test_core import P

client = TestClient(api.app)


def test_baseline_endpoint():
    r = client.post("/verify?method=baseline&include_meta=true",
                    json={"context_passages": P, "generated_answer": "Automatic checkpointing occurs "
                          "by default when the WAL passes approximately 1000 pages."})
    assert r.status_code == 200
    body = r.json()
    assert body["claims"][0]["verdict"] == "SUPPORTED"
    assert body["meta"]["method"] == "baseline"


def test_meta_hidden_by_default():
    r = client.post("/verify?method=baseline", json={"context_passages": P, "generated_answer": "Hi."})
    assert "meta" not in r.json()


def test_validation_errors():
    assert client.post("/verify", json={"context_passages": P}).status_code == 422
    assert client.post("/verify", json={"context_passages": "x", "generated_answer": "y"}).status_code == 422
    assert client.post("/verify?method=bogus",
                       json={"context_passages": [], "generated_answer": "y"}).status_code == 422


def test_upstream_error_maps_to_502(monkeypatch):
    class Boom:
        async def verify(self, req):
            raise UpstreamError("down")
    monkeypatch.setitem(api._verifiers, "optimized", Boom())
    r = client.post("/verify?method=optimized", json={"context_passages": P, "generated_answer": "x"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error"
