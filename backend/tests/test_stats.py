from app.models import File
from app.stats import DIGITS, calculate_stats, count_digits


def test_count_digits_basic():
    counts = count_digits("11223344550099887766")
    assert counts == {d: 2 for d in DIGITS}


def test_count_digits_ignores_non_digits():
    counts = count_digits("123\n45abc ")
    assert counts["1"] == 1
    assert counts["5"] == 1
    assert counts["9"] == 0
    assert sum(counts.values()) == 5


def test_count_digits_empty():
    assert count_digits("") == {d: 0 for d in DIGITS}


def test_calculate_stats():
    files = [
        File(id=1, name="a.txt", content="111"),
        File(id=2, name="b.txt", content="129"),
    ]
    total, per_file = calculate_stats(files)

    assert total["1"] == 4
    assert total["2"] == 1
    assert total["9"] == 1
    assert sum(total.values()) == 6

    assert [f.name for f, _ in per_file] == ["a.txt", "b.txt"]
    assert per_file[0][1]["1"] == 3
    assert per_file[1][1]["2"] == 1
