from collections import Counter

from eval.dataset import load

REQUIRED_TAGS = {
    "supported", "paraphrase", "number_off", "unit_change", "negation_flip", "condition_swap",
    "quantifier_shift", "comparison_flip", "entity_swap", "temporal_version", "extrinsic",
    "extrinsic_true_world", "multi_passage", "empty_context", "no_claims", "mixed",
}


def test_dataset_is_valid_and_big_enough():
    cases = load("data/eval.jsonl")
    assert len(cases) >= 30
    splits = Counter(c.split for c in cases)
    assert splits["dev"] >= 15 and splits["test"] >= 15  # test is held out, not smaller


def test_dataset_covers_every_failure_bucket():
    cases = load("data/eval.jsonl")
    tags = {t for c in cases for t in c.tags} | {t for c in cases for g in c.gold_claims for t in g.tags}
    assert REQUIRED_TAGS <= tags, REQUIRED_TAGS - tags


def test_every_verdict_is_represented_in_both_splits():
    cases = load("data/eval.jsonl")
    for split in ("dev", "test"):
        verdicts = Counter(g.verdict.value for c in cases if c.split == split for g in c.gold_claims)
        assert all(verdicts[v] > 0 for v in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED")), (split, verdicts)
