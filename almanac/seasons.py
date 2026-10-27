"""Display recorded planting months as southern-hemisphere seasons."""
from calendar import month_name


def planting_seasons(months):
    groups = [('Summer', {12, 1, 2}, '#fff0b8'), ('Autumn', {3, 4, 5}, '#ffe0bd'),
              ('Winter', {6, 7, 8}, '#dcecfb'), ('Spring', {9, 10, 11}, '#e0efcf')]
    numbers = {i for i, name in enumerate(month_name) if i and any(
        str(value).casefold() in (name.casefold(), name[:3].casefold()) for value in months)}
    selected = [(name, colour) for name, values, colour in groups if numbers & values]
    label = 'Year-round' if len(numbers) == 12 else ' + '.join(name for name, _ in selected)
    colors = [colour for _, colour in selected] or ['#edf1e6']
    return {'label': label or 'Not recorded', 'names': [name for name, _ in selected],
            'background': 'linear-gradient(120deg, ' + ', '.join(colors if len(colors)>1 else colors*2) + ')'}
