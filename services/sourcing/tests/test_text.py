from ff_sourcing.domain.text import english_keywords, normalize, parse_query, stem


def test_normalize_arabic():
    assert normalize("أَلْـوَاحٌ") == "الواح"
    assert normalize("مكينة") == "مكينه"
    assert normalize("مصطفى") == "مصطفي"
    assert normalize("٣٠٠ طن") == "300 طن"
    assert normalize("خــط") == "خط"


def test_stem_article_and_plural():
    assert stem("الالواح") == "واح" and stem("الواح") == "واح"
    assert stem("chairs") == "chair" and stem("glass") == "glass"


def test_synonym_groups_bilingual():
    term = parse_query("خط انتاج")[0]
    assert ("production", "line") in term.alternatives
    assert english_keywords("ألواح شمسية") == ["solar panel"]
    assert parse_query("وكراسي")[0].alternatives[0] == ("chair",)


def test_stopwords_and_condition_words_dropped():
    assert [t.original for t in parse_query("new the pump")] == ["pump"]
