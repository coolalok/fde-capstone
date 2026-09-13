"""Retrieval metric tests. Expected values are computed by hand, not by
calling the function under test — a metric that is subtly wrong gets quoted.
"""
from __future__ import annotations

import math

import pytest

from evaluation.retrieval_eval import (
    THIN_MARGIN,
    aggregate,
    article_overlap,
    best_score_per_doc,
    by_intent,
    hit_at_k,
    margin_by_intent,
    ndcg_at_k,
    reciprocal_rank,
    score_margin,
    score_ticket,
    top1_confusions,
)

A, B, C, D = "DOC-A-001", "DOC-B-001", "DOC-C-001", "DOC-D-001"


def test_hit_at_k():
    assert hit_at_k([B, A], {A}, 1) is False
    assert hit_at_k([B, A], {A}, 3) is True


@pytest.mark.parametrize("ranked, expected, want", [
    ([A, B], {A}, 1.0),
    ([B, A], {A}, 0.5),
    ([C, D, A], {A}, 1 / 3),
    ([C, D], {A}, 0.0),
    ([], {A}, 0.0),          # threshold cut everything: production returned nothing
])
def test_reciprocal_rank(ranked, expected, want):
    assert reciprocal_rank(ranked, expected) == pytest.approx(want)


def test_ndcg_perfect_single():
    assert ndcg_at_k([A, B], {A}, 5) == pytest.approx(1.0)


def test_ndcg_relevant_at_rank_two():
    # DCG = 1/log2(3); IDCG = 1/log2(2) = 1
    assert ndcg_at_k([B, A], {A}, 5) == pytest.approx(1 / math.log2(3))


def test_ndcg_duplicate_chunks_of_one_document_are_credited_once():
    """Every article here is 2-3 chunks. Crediting each chunk would put DCG
    above the ideal for a single expected document and NDCG above 1.
    """
    got = ndcg_at_k([B, A, A], {A}, 5)
    assert got == pytest.approx(1 / math.log2(3))
    assert got <= 1.0


def test_ndcg_multiple_expected_documents():
    # ranked A, C, B with {A, B}: DCG = 1 + 1/log2(4) = 1.5
    # IDCG = 1 + 1/log2(3)
    want = 1.5 / (1 + 1 / math.log2(3))
    assert ndcg_at_k([A, C, B], {A, B}, 5) == pytest.approx(want)


def test_ndcg_all_expected_at_top_is_one():
    assert ndcg_at_k([A, B, C], {A, B}, 5) == pytest.approx(1.0)


def test_ndcg_empty_and_irrelevant_are_zero():
    assert ndcg_at_k([], {A}, 5) == 0.0
    assert ndcg_at_k([C, D], {A}, 5) == 0.0


def test_ndcg_respects_the_cutoff():
    assert ndcg_at_k([B, C, D, A], {A}, 3) == 0.0


def test_score_ticket_and_aggregate():
    rows = [
        {"intent": "x", **score_ticket([A], [A])},     # rr 1
        {"intent": "x", **score_ticket([B, A], [A])},  # rr 0.5
        {"intent": "y", **score_ticket([C], [A])},     # rr 0
    ]
    agg = aggregate(rows)
    assert agg["n"] == 3
    assert agg["hit@1"] == pytest.approx(round(1 / 3, 4))
    assert agg["hit@3"] == pytest.approx(round(2 / 3, 4))
    assert agg["mrr"] == pytest.approx(0.5)


def test_by_intent_separates_categories():
    rows = [
        {"intent": "data_export", **score_ticket([A], [A])},
        {"intent": "data_residency", **score_ticket([A], [B])},
    ]
    got = by_intent(rows)
    assert got["data_export"]["mrr"] == 1.0
    assert got["data_residency"]["mrr"] == 0.0


def test_top1_confusions_records_what_displaced_the_expected_doc():
    rows = [
        {"expected_doc_ids": [B], "retrieved_doc_ids": [A, B]},  # miss -> (B, A)
        {"expected_doc_ids": [B], "retrieved_doc_ids": [A]},     # miss -> (B, A)
        {"expected_doc_ids": [A], "retrieved_doc_ids": [A]},     # hit, not counted
        {"expected_doc_ids": [A], "retrieved_doc_ids": []},      # empty, not a confusion
        {"expected_doc_ids": [C, D], "retrieved_doc_ids": [A]},  # one pair per expected
    ]
    got = top1_confusions(rows)
    assert got[(B, A)] == 2
    assert got[(C, A)] == 1 and got[(D, A)] == 1
    assert sum(got.values()) == 4


# ─── separation diagnostics ─────────────────────────────────────────
# Rank metrics say WHETHER the right article came first; the margin says by
# how much. sso_configuration scored 1.000 on every rank metric on 13 Sep while
# 9 of 15 tickets won by under 0.05.


def test_best_score_per_doc_keeps_each_articles_highest_chunk():
    got = best_score_per_doc([(A, 0.5), (A, 0.7), (B, 0.6), (B, -0.1)])
    assert got == {A: 0.7, B: 0.6}


def test_margin_positive_when_expected_article_leads():
    margin, rival = score_margin({A: 0.7, B: 0.6, C: 0.2}, {A})
    assert margin == pytest.approx(0.1)
    assert rival == B


def test_margin_negative_when_a_wrong_article_leads():
    margin, rival = score_margin({A: 0.7, B: 0.6}, {B})
    assert margin == pytest.approx(-0.1)
    assert rival == A


def test_margin_uses_the_best_expected_article_when_several_are_expected():
    margin, rival = score_margin({A: 0.4, B: 0.8, C: 0.5}, {A, B})
    assert margin == pytest.approx(0.3)
    assert rival == C


def test_margin_is_undefined_with_nothing_to_compare():
    assert score_margin({A: 0.7}, {A}) == (None, None)       # no wrong article
    assert score_margin({B: 0.7}, {A}) == (None, None)       # expected never scored


def test_margin_by_intent_summarises_and_sorts_narrowest_first():
    rows = [
        {"intent": "sso_configuration", "margin": 0.02, "nearest_wrong_doc": B},
        {"intent": "sso_configuration", "margin": 0.04, "nearest_wrong_doc": B},
        {"intent": "sso_configuration", "margin": 0.30, "nearest_wrong_doc": C},
        {"intent": "data_residency", "margin": 0.29, "nearest_wrong_doc": D},
        {"intent": "data_residency", "margin": -0.10, "nearest_wrong_doc": D},
        {"intent": "data_residency", "margin": None, "nearest_wrong_doc": None},
    ]
    got = margin_by_intent(rows)
    assert list(got) == ["sso_configuration", "data_residency"]   # 0.04 < 0.095
    sso = got["sso_configuration"]
    assert sso["n"] == 3
    assert sso["median_margin"] == pytest.approx(0.04)
    assert sso["thin_margin_n"] == 2
    assert sso["wrong_ranked_first_n"] == 0
    assert (sso["nearest_wrong_doc"], sso["nearest_wrong_doc_n"]) == (B, 2)
    res = got["data_residency"]
    assert res["n"] == 2                                # the None row is excluded
    assert res["min_margin"] == pytest.approx(-0.10)
    assert res["wrong_ranked_first_n"] == 1
    assert res["thin_margin_n"] == 1                    # a negative margin is thin too


def test_thin_margin_threshold_is_the_documented_value():
    assert THIN_MARGIN == 0.05


def test_article_overlap_takes_the_closest_chunk_pair():
    chunks = {
        A: [[1.0, 0.0], [0.0, 1.0]],
        B: [[0.0, 1.0]],               # identical to A's second chunk
        C: [[-1.0, 0.0]],              # opposite A's first chunk, orthogonal to B
    }
    got = article_overlap(chunks)
    assert len(got) == 3                                 # 3 choose 2
    assert got[0] == (1.0, A, B)                         # most similar first
    scores = {(a, b): s for s, a, b in got}
    assert scores[(B, C)] == pytest.approx(0.0)
    assert scores[(A, C)] == pytest.approx(0.0)          # max of -1 and 0
