from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestNoVatMerchant(TestPoSCommon):
    """A merchant that is not a VAT payer sends every item as NO_VAT."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.open_new_session()
        self.product = self.env['product.product'].create({
            'name': 'Untaxed item', 'list_price': 5000, 'taxes_id': [(5, 0, 0)],
        })
        self.order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'amount_total': 5000, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'lines': [(0, 0, {
                'product_id': self.product.id, 'qty': 1, 'price_unit': 5000,
                'price_subtotal': 5000, 'price_subtotal_incl': 5000, 'tax_ids': [(5, 0, 0)],
            })],
        })

    def test_untaxed_item_is_no_vat(self):
        self.order.company_id.ebarimt_no_vat = True
        line = self.order.lines
        values = self.order._ebarimt_line_values(line, 1)
        self.assertEqual(values['tax_type'], 'NO_VAT')
        self.assertEqual(values['vat'], 0)
        self.assertFalse(values['taxProductCode'])

    def test_vat_payer_keeps_vat_free(self):
        values = self.order._ebarimt_line_values(self.order.lines, 1)
        self.assertEqual(values['tax_type'], 'VAT_FREE')
