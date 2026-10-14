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


def test_normalization_variants():
    assert normalize("كُرْسِيّ") == normalize("كرسي")
    assert normalize("مكينة") == normalize("مكينه") == "مكينه"
    assert normalize("مستشفى") == "مستشفي"
    assert normalize("Café  PUMP") == "cafe pump"
    assert normalize("塑料机器") == "塑 料 机 器"
    assert stem("للقناني") == "قناني" and stem("بالساعة") == stem("الساعة")
    assert stem("batteries") == "battery" and stem("boxes") == "box" and stem("gas") == "gas"


def _first(q):
    return {" ".join(a) for a in parse_query(q)[0].alternatives}


def test_iraqi_dialect_and_chinese_synonyms():
    assert {"machine", "مكينه"} <= _first("ماكنة") and "machine" in _first("مكينة")
    assert "chair" in _first("كرسي") and "chair" in _first("椅子")
    assert "cigarette" in _first("جكاير")
    assert "plastic" in _first("塑料")
    assert "machine" in _first("机器")
    # two Chinese terms in one query are segmented into two terms
    assert [t.original for t in parse_query("塑料机器")] == ["塑 料", "机 器"]
    assert english_keywords("塑料机器") == ["plastic", "machine"]


def test_typo_distance_rules():
    from ff_sourcing.domain.text import typo_distance

    assert typo_distance("bottel", "bottle") == 1  # transposition
    assert typo_distance("injecton", "injection") == 1
    assert typo_distance("pmup", "pump") == 1
    assert typo_distance("tile", "tire") is None  # 4-letter substitution rejected
    assert typo_distance("pipe", "pine") is None
    assert typo_distance("cat", "car") is None  # too short
    assert typo_distance("table", "cable") is None  # first letter must match
    assert typo_distance("model25", "model26") is None  # digits never fuzzy
    assert typo_distance("polypropylene", "polyethylene") is None


def test_typo_query_term_is_corrected_to_group():
    term = parse_query("injecton")[0]
    assert term.fuzzy == "injecton"  # unknown word: doc-side fuzzy
    assert ("machine",) in parse_query("machin")[0].alternatives  # corrected to known group
