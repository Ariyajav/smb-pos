from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestOfferingNoEbarimt(TestPoSCommon):
    """Offering lines never go to eBarimt; an offering-only order gets no bill."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.open_new_session()
        self.reading = self.env['product.product'].create({
            'name': 'Цагаан шүхэрт', 'list_price': 0, 'taxes_id': [(5, 0, 0)],
            'available_in_pos': True, 'offering_kind': 'reading',
        })
        self.amount = self.env.ref('pos_offering.product_offering_amount')
        self.goods = self.env['product.product'].create({
            'name': 'Хүж', 'list_price': 3000, 'taxes_id': [(5, 0, 0)],
        })

    def _order(self, lines):
        total = sum(qty * price for _product, qty, price in lines)
        return self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'amount_total': total, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'offering_from': 'Бат', 'offering_family_size': 4, 'offering_day': 'Өдөр бүр',
            'lines': [(0, 0, {
                'product_id': product.id, 'qty': qty, 'price_unit': price,
                'price_subtotal': qty * price, 'price_subtotal_incl': qty * price,
                'tax_ids': [(5, 0, 0)],
            }) for product, qty, price in lines],
        })

    def test_amount_product_has_no_taxes(self):
        self.assertEqual(self.amount.offering_kind, 'amount')
        self.assertFalse(self.amount.taxes_id)
        self.assertTrue(self.amount.available_in_pos)

    def test_offering_order_is_not_queued(self):
        order = self._order([(self.reading, 1, 0), (self.amount, 1, 50000)])
        self.assertEqual(order._ebarimt_sold_lines(), [])
        self.assertFalse(order._ebarimt_should_queue())
        self.assertEqual(order.offering_family_size, 4)

    def test_goods_still_billed(self):
        order = self._order([(self.goods, 1, 3000), (self.amount, 1, 10000)])
        sold = order._ebarimt_sold_lines()
        self.assertEqual([line.product_id for line, _qty in sold], [self.goods])

    def test_offering_refund_has_no_return(self):
        order = self._order([(self.amount, 1, 50000)])
        refund = self._order([(self.amount, -1, 50000)])
        refund.lines.refunded_orderline_id = order.lines
        self.assertFalse(refund._ebarimt_returns_lines())
        self.assertFalse(refund._ebarimt_should_queue())

    def test_reading_days_loaded_in_pos(self):
        self.assertIn('pos.offering.day', self.env['pos.session']._load_pos_data_models(self.config))
        days = self.env['pos.offering.day']._load_pos_data_search_read({}, self.config)
        self.assertEqual(days[0]['name'], 'Өдөр бүр')
        self.assertIn('offering_kind', self.env['product.template']._load_pos_data_fields(self.config))
