from evaluate import mean, metrics


def test_duplicate_hits_do_not_inflate_precision_or_recall():
    result = metrics(['a', 'a', 'b'], ['a', 'c'])
    assert result['precision_at_5'] == .2
    assert result['recall_at_5'] == .5


def test_rank_and_fixed_five_denominator():
    result = metrics(['x', 'a'], ['a'])
    assert result == {'precision_at_5': .2, 'recall_at_5': 1., 'reciprocal_rank': .5}


def test_negative_cases_are_not_assigned_misleading_recall():
    assert all(value is None for value in metrics(['x'], []).values())


def test_mean_is_null_for_empty_source_groups():
    assert mean([]) is None
    assert mean([.25, .75]) == .5
