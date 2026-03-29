from app.services.tokenize import normalized_terms, term_frequencies


def test_normalized_terms_drops_stop_words() -> None:
    assert normalized_terms("The quick brown fox") == ["quick", "brown", "fox"]


def test_term_frequencies_counts_terms() -> None:
    freqs = term_frequencies("alpha beta alpha")
    assert freqs["alpha"] == 2
    assert freqs["beta"] == 1
