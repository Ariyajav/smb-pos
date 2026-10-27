from odoo.service.model import call_kw
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestReceiptData(TestPoSCommon):
    """The POS asks the server for the bill of the order it just printed.
    Each order must get its own bill back, whatever the POS config id."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.open_new_session()
        self.company_partner = self.env['res.partner'].create({
            'name': 'Test Buyer LLC', 'is_company': True, 'vat_tin': '61200064714',
        })

    def _receipt_data(self, identifier):
        # Through call_kw, as the POS's RPC does: a plain Python call would
        # not notice the method losing @api.model.
        return call_kw(self.env['pos.order'], 'get_ebarimt_receipt_data', [identifier, self.config.id], {})

    def _order_with_bill(self, bill_id, bill_type='B2C_RECEIPT', partner=False, customer_tin=''):
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'partner_id': partner and partner.id,
            'pos_reference': 'Order %s' % bill_id,
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
        })
        self.env['vat.receipt'].create({
            'pos_order_id': order.id,
            'bill_id': bill_id,
            'bill_type': bill_type,
            'customer_tin': customer_tin,
            'lottery': '' if bill_type == 'B2B_RECEIPT' else 'AA 00000001',
            'bill_state': 'done',
        })
        return order

    def test_each_order_gets_its_own_bill(self):
        first = self._order_with_bill('BILL-FIRST')
        second = self._order_with_bill('BILL-SECOND')
        for order, bill_id in ((first, 'BILL-FIRST'), (second, 'BILL-SECOND')):
            data = self._receipt_data(order.id)
            self.assertEqual(data.get('bill_id'), bill_id)
            data = self._receipt_data(order.pos_reference)
            self.assertEqual(data.get('bill_id'), bill_id)

    def test_company_bill_names_the_buyer(self):
        b2b = self._order_with_bill('BILL-B2B', 'B2B_RECEIPT', self.company_partner, '61200064714')
        b2c = self._order_with_bill('BILL-B2C', partner=self.company_partner)
        data = self._receipt_data(b2b.id)
        self.assertEqual(data['customer_tin'], '61200064714')
        self.assertEqual(data['customer_name'], 'Test Buyer LLC')
        self.assertFalse(self._receipt_data(b2c.id)['customer_name'])

    def test_company_bill_prints_registry_number(self):
        """The receipt shows the buyer's registry number (РД), not its TIN."""
        self.company_partner.vat = '6235972'
        from_partner = self._order_with_bill('BILL-REG', 'B2B_RECEIPT', self.company_partner, '61200064714')
        self.assertEqual(self._receipt_data(from_partner.id)['customer_reg_no'], '6235972')
        # Typed in the popup: what the cashier typed is the buyer.
        typed = self._order_with_bill('BILL-TYPED', 'B2B_RECEIPT', customer_tin='61101326127')
        typed.ebarimt_manual_customer_tin = '5317878'
        self.assertEqual(self._receipt_data(typed.id)['customer_reg_no'], '5317878')
        # A TIN typed directly: no registry number known, the TIN is printed.
        typed.ebarimt_manual_customer_tin = '61101326127'
        self.assertFalse(self._receipt_data(typed.id)['customer_reg_no'])
        # The customer on the order is not the buyer the bill was issued to.
        other = self._order_with_bill('BILL-OTHER', 'B2B_RECEIPT', self.company_partner, '61101326127')
        self.assertFalse(self._receipt_data(other.id)['customer_reg_no'])
