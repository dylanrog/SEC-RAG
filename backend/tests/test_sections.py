from pipeline.sections import SectionTracker


def test_10k_items_ignore_part_headings():
    t = SectionTracker("10-K")
    assert t.update("Cover page text") == "other"
    assert t.update("PART I") == "other"          # part heading itself precedes any item
    assert t.update("Item 1. Business") == "item1"
    assert t.update("The Company designs products.") == "item1"
    assert t.update("Item 1A. Risk Factors") == "item1a"
    assert t.update("ITEM 7A. Quantitative and Qualitative Disclosures") == "item7a"


def test_10q_items_get_part_prefix():
    t = SectionTracker("10-Q")
    t.update("PART I — FINANCIAL INFORMATION")
    assert t.update("Item 2. Management's Discussion and Analysis") == "part1.item2"
    t.update("PART II — OTHER INFORMATION")
    assert t.update("Item 1. Legal Proceedings") == "part2.item1"


def test_long_blocks_never_change_section():
    t = SectionTracker("10-K")
    t.update("Item 7. Management's Discussion and Analysis")
    long_sentence = "Item 1A described risks that " + "very " * 40 + "materially affect us."
    assert t.update(long_sentence) == "item7"
