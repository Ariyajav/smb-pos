from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon

POS_ORDER = 'odoo.addons.pos_ebarimt.models.pos_order.PosOrder'
POSAPI = 'odoo.addons.ebarimt_api.models.ebarimt.eBarimtPosAPI'


def _no_posapi(*args, **kwargs):
    raise AssertionError("PosAPI must not be called for an order whose bill belongs to its shop")


@tagged('post_install', '-at_install')
class TestIssuedAtShop(TestPoSCommon):
    """Orders copied in from a shop's own Odoo (multi-shop sync) got their
    eBarimt bill at the shop. This database must never send, resend or
    return a bill for them, whatever state they arrive in."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.open_new_session()
        self.env['account.ebarimt.posapi'].create({
            'name': 'Test PosAPI', 'service_url': 'http://127.0.0.1:1', 'company_id': self.env.company.id,
        })
        self.product = self.env['product.product'].create({
            'name': 'Synced item', 'list_price': 5000, 'taxes_id': [(5, 0, 0)],
        })
        patcher = patch.multiple(POSAPI, _request_connection=_no_posapi,
                                 _request_receipt=_no_posapi, _return_receipt=_no_posapi)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _order(self, qty=1, refunded_line=False, **vals):
        line = {
            'product_id': self.product.id, 'qty': qty, 'price_unit': 5000,
            'price_subtotal': 5000 * qty, 'price_subtotal_incl': 5000 * qty, 'tax_ids': [(5, 0, 0)],
        }
        if refunded_line:
            line['refunded_orderline_id'] = refunded_line.id
        # The hub imports as superuser: the create guard drops these fields
        # for anyone else.
        return self.env['pos.order'].sudo().create(dict({
            'session_id': self.pos_session.id,
            'amount_total': 5000 * qty, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'lines': [(0, 0, line)],
        }, **vals))

    def _synced(self, **vals):
        # Bill still pending at the shop (it was offline): vat_sent is False,
        # which on its own would make this database send one.
        return self._order(ebarimt_issued_at_shop=True, vat_sent=False, ebarimt_state='pending', **vals)

    def test_synced_paid_order_is_not_queued(self):
        order = self._synced()
        self.assertTrue(order.ebarimt_issued_at_shop)
        with patch(POS_ORDER + '._vat_pos_order_commit', _no_posapi):
            order.sudo().write({'state': 'paid'})
        self.assertFalse(order._ebarimt_should_queue())
        self.assertEqual(order.ebarimt_state, 'pending')
        self.assertFalse(order.ebarimt_next_try)

    def test_normal_paid_order_still_queued(self):
        order = self._order()
        order.write({'state': 'paid'})
        self.assertEqual(order.ebarimt_state, 'pending')

    def test_cron_skips_synced_orders(self):
        synced = self._synced()
        processed = []
        with patch(POS_ORDER + '._ebarimt_process', lambda self, ids: processed.extend(ids) or 0):
            self.env['pos.order']._cron_send_pending_ebarimt()
        self.assertNotIn(synced.id, processed)

    def test_no_manual_send_or_return(self):
        order = self._synced(state='paid')
        self.env['vat.receipt'].create({'pos_order_id': order.id, 'bill_id': 'SHOP-1', 'bill_state': 'done'})
        with self.assertRaises(UserError):
            order._ebarimt_send_manual('B2C_RECEIPT')
        with self.assertRaises(UserError):
            order.return_ebarimt()
        with self.assertRaises(UserError):
            order._ebarimt_take_back()

    def test_refund_on_hub_leaves_shop_bill_alone(self):
        original = self._synced(state='paid')
        refund = self._order(qty=-1, refunded_line=original.lines)
        state, note = refund._ebarimt_send_one()
        self.assertEqual(state, 'manual')
        self.assertIn(original.name, note)

    def test_cashier_cannot_mark_order_as_shop_issued(self):
        cashier = self.env['res.users'].create({
            'name': 'Cashier', 'login': 'ebarimt_shop_cashier',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('point_of_sale.group_pos_user').id])],
        })
        order = self.env['pos.order'].with_user(cashier).create({
            'session_id': self.pos_session.id,
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'ebarimt_issued_at_shop': True,
        })
        self.assertFalse(order.ebarimt_issued_at_shop)
