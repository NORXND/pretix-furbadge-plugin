from pretix_furbadge.bot.commands import _parse_index


def test_parse_index_accepts_valid_range():
    assert _parse_index("1", 3) == 1
    assert _parse_index("3", 3) == 3


def test_parse_index_rejects_out_of_range_and_invalid_values():
    assert _parse_index("0", 3) is None
    assert _parse_index("4", 3) is None
    assert _parse_index("x", 3) is None
    assert _parse_index("-1", 3) is None
