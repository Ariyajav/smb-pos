from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

# A small copy of eBarimt's BUNA tree: path (p1..p6) -> children.
TREE = {
    (): [['6', 'Distributive trade'], ['9', 'Community services']],
    ('6',): [['61', 'Wholesale trade']],
    ('6', '61'): [['611', 'Wholesale, not on a fee basis']],
    ('6', '61', '611'): [['6118', 'Machinery']],
    ('6', '61', '611', '6118'): [['61184', 'Computers and packaged software']],
    ('6', '61', '611', '6118', '61184'): [['6118410', 'Computers'], ['6118420', 'Software']],
    ('9',): [['95', 'Membership organizations']],
    ('9', '95'): [['959', 'Other membership organizations']],
    ('9', '95', '959'): [['9591', 'Religious organizations']],
    ('9', '95', '959', '9591'): [['95910', 'Religious services']],
    ('9', '95', '959', '9591', '95910'): [['9591000', 'Religious services']],
}


def fake_fetch(self, *path):
    path = tuple(p for p in path if p)
    if path not in TREE:
        return {'success': False, 'error': 'not found %s' % (path,)}
    return {'success': True, 'data': TREE[path]}


@tagged('post_install', '-at_install')
class TestBunaCodes(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Buna = self.env['product.classification.buna']
        patcher = patch.object(type(self.Buna), '_fetch_from_api', fake_fetch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_subclass_and_class(self):
        self.assertEqual(self.Buna.load_code_subtree('61184'), 2)
        self.assertEqual(self.Buna.load_code_subtree('9591'), 1)
        software = self.Buna.search([('code', '=', '6118420')])
        self.assertEqual(software.parent_id.code, '61184')
        self.assertEqual(software.parent_id.parent_id.parent_id.parent_id.parent_id.code, '6')
        self.assertEqual(software.p5, '61184')
        self.assertEqual(software.p6, '6118420')
        # Loading again updates, never duplicates.
        self.Buna.load_code_subtree('61184')
        self.assertEqual(self.Buna.search_count([('code', '=', '6118420')]), 1)

    def test_unknown_code_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Buna.load_code_subtree('61185')

    def test_product_takes_only_loaded_codes(self):
        self.Buna.load_code_subtree('61184')
        product = self.env['product.template'].create({'name': 'Laptop'})
        product.buna_classification_id = self.Buna.search([('code', '=', '6118410')])
        category = self.Buna.search([('code', '=', '61184')])
        with self.assertRaises(ValidationError):
            product.buna_classification_id = category
        with self.assertRaises(ValidationError):
            product.vat_classification_id = self.env['product.classification.code'].create({'name': '1234567'})
        product.vat_classification_id = self.env['product.classification.code'].create({'name': '6118420'})
