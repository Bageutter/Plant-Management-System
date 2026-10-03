import unittest

from plant_groups import catalogue_view
from growing_details import parse_details
from werkzeug.datastructures import MultiDict


class PlantGroupTests(unittest.TestCase):
    def setUp(self):
        self.plants = [
            dict(slug='carrot', common_name='Carrot', scientific_name='Daucus carota', summary='Stored summary', plant_group='Carrot', variety_name=None, plant_category='Vegetables'),
            dict(slug='purple', common_name='Carrot - Cosmic Purple', scientific_name='Daucus carota', summary='Purple roots', plant_group='Carrot', variety_name='Cosmic Purple', plant_category='Vegetables'),
            dict(slug='other', common_name='Carrot flower', scientific_name='Different species', summary='Not grouped from name'),
        ]

    def test_generic_record_is_not_counted_as_named_variety(self):
        groups = catalogue_view(self.plants, {})['plant_groups']
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['variety_count'], 1)
        self.assertEqual(groups[0]['summary'], 'Stored summary')
        self.assertEqual(groups[1]['name'], 'Carrot flower')

    def test_search_does_not_invent_group_summary_when_generic_is_filtered_out(self):
        view = catalogue_view(self.plants, {'q':'COSMIC', 'category':'Vegetables'})
        self.assertEqual([p['slug'] for p in view['visible_plants']], ['purple'])
        self.assertIsNone(view['plant_groups'][0]['summary'])

    def test_legacy_record_and_empty_search_result(self):
        self.assertEqual(len(catalogue_view(self.plants, {'category':'Other'})['visible_plants']),1)
        self.assertFalse(catalogue_view(self.plants, {'q':'no-such-plant'})['visible_plants'])

    def test_grouping_edits_validate_lengths_and_category_and_preserve_omitted_fields(self):
        self.assertNotIn('plant_group', parse_details(MultiDict()))
        self.assertIsNone(parse_details(MultiDict({'plant_group':''}))['plant_group'])
        with self.assertRaises(ValueError):
            parse_details(MultiDict({'plant_group':'x'*121}))
        with self.assertRaises(ValueError):
            parse_details(MultiDict({'plant_category':'Unknown'}))


if __name__ == '__main__':
    unittest.main()
