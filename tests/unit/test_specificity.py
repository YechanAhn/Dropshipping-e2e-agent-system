"""Unit tests for keyword specificity / brand filters (pure functions)."""

from dropagent.core.discovery.specificity import (
    is_branded,
    is_head_term,
    is_specific,
    normalize,
    strip_brand_tokens,
    strip_html,
    titles_to_seeds,
)

SEEDS = ["무선 이어폰", "차량용 거치대"]


# --- normalize / is_head_term ------------------------------------------------


def test_normalize_despaces_and_lowercases():
    assert normalize(" 무선 이어폰 ") == "무선이어폰"
    assert normalize("Type-C") == "type-c"


def test_is_head_term_matches_seed_ignoring_spaces():
    assert is_head_term("무선이어폰", SEEDS) is True       # de-spaced seed
    assert is_head_term("무선 이어폰", SEEDS) is True       # exact seed
    assert is_head_term("차량용거치대", SEEDS) is True
    assert is_head_term("골전도 무선 이어폰", SEEDS) is False


# --- is_specific -------------------------------------------------------------


def test_is_specific_drops_bare_head_terms():
    assert is_specific("이어폰", SEEDS) is False        # 1 token, 3 chars
    assert is_specific("무선이어폰", SEEDS) is False     # 1 token, 5 chars (< 6)
    assert is_specific("무선 이어폰", SEEDS) is False     # exact seed
    assert is_specific("거치대", SEEDS) is False


def test_is_specific_keeps_multiword_longtail():
    assert is_specific("골전도 러닝 이어폰", SEEDS) is True   # 3 tokens
    assert is_specific("차량용 무선충전 거치대", SEEDS) is True


def test_is_specific_keeps_long_spaceless_compound():
    # 1 token but >= 6 de-spaced chars -> kept (e.g. compound noun)
    assert is_specific("골전도이어폰", SEEDS) is True       # 6 chars
    assert is_specific("유아용식판세트", SEEDS) is True


def test_is_specific_thresholds_are_tunable():
    # Require 3 tokens -> a 2-token keyword no longer passes on token count,
    # and a short de-spaced length fails the char fallback too.
    assert is_specific("러닝 이어폰", SEEDS, min_tokens=3, min_chars=6) is False


# --- is_branded --------------------------------------------------------------


def test_is_branded_detects_brand_substring():
    assert is_branded("에어팟 프로 케이스") is True
    assert is_branded("갤럭시 버즈 실리콘 커버") is True
    assert is_branded("apple 정품 충전기") is True


def test_is_branded_false_for_generic_keywords():
    assert is_branded("골전도 러닝 이어폰") is False
    assert is_branded("차량용 무선충전 거치대") is False


def test_is_branded_custom_list():
    assert is_branded("테팔 프라이팬", brands={"테팔"}) is True
    assert is_branded("일반 프라이팬", brands={"테팔"}) is False


# --- title cleaning -> seeds (category browsing) -----------------------------


def test_strip_html_removes_b_tags():
    assert strip_html("무선 <b>이어폰</b>").split() == ["무선", "이어폰"]


def test_strip_brand_tokens_drops_brand_words_keeps_generic():
    assert strip_brand_tokens("삼성 갤럭시 버즈4 무선 이어폰") == "버즈4 무선 이어폰"
    assert strip_brand_tokens("골전도 러닝 이어폰") == "골전도 러닝 이어폰"


def test_titles_to_seeds_cleans_dedupes_and_caps():
    titles = [
        "삼성 갤럭시 <b>무선이어폰</b>",
        "삼성 갤럭시 <b>무선이어폰</b>",  # duplicate after cleaning
        "QCY 블루투스 이어폰",
    ]
    assert titles_to_seeds(titles, max_seeds=10) == ["무선이어폰", "QCY 블루투스 이어폰"]
    assert titles_to_seeds(["aaa 1", "bbb 2", "ccc 3"], max_seeds=2) == ["aaa 1", "bbb 2"]
