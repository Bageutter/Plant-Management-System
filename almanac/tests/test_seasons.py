from seasons import planting_seasons


def test_sydney_pea_months_are_autumn_and_winter():
    value = planting_seasons(['March','April','May','June','July','August'])
    assert value['label'] == 'Autumn + Winter'
    assert len(value['names']) == 2


def test_summer_crosses_calendar_year():
    assert planting_seasons(['Dec','Jan','Feb'])['label'] == 'Summer'


def test_empty_months_do_not_invent_a_season():
    assert planting_seasons([])['label'] == 'Not recorded'


def test_all_months_are_year_round():
    from calendar import month_name
    assert planting_seasons(list(month_name)[1:])['label'] == 'Year-round'


def test_four_seasons_use_one_solid_year_round_card():
    value = planting_seasons(['January', 'April', 'July', 'October'])
    assert value['label'] == 'Year-round'
    assert value['names'] == []
    assert value['background'] == '#eaf1dc'
