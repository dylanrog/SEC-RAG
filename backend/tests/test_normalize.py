from api.normalize import normalize


def test_casefolds_and_collapses_whitespace():
    text, _ = normalize("Total  Net\n\tSales")
    assert text == "total net sales"


def test_straightens_curly_quotes_and_dashes():
    text, _ = normalize("“Apple’s” year—over–year")
    assert text == '"apple\'s" year-over-year'


def test_offset_map_has_one_entry_per_normalized_char():
    original = "The  “Quick” Brown"
    text, offsets = normalize(original)
    assert len(offsets) == len(text)


def test_offset_map_points_at_the_producing_character():
    original = "Net   sales"
    text, offsets = normalize(original)
    assert text == "net sales"
    assert offsets[text.index("sales")] == original.index("sales")


def test_collapsed_whitespace_run_maps_to_its_first_character():
    original = "a \n b"
    text, offsets = normalize(original)
    assert text == "a b"
    assert offsets[1] == 1


def test_multi_character_expansion_maps_every_char_to_one_source_index():
    # NFKC expands the ligature; casefold expands the eszett.
    text, offsets = normalize("ﬁnß")
    assert text == "finss"
    assert offsets == [0, 0, 1, 2, 2]


def test_empty_text_is_stable():
    assert normalize("") == ("", [])
