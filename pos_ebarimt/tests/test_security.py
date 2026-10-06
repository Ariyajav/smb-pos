from odoo.exceptions import AccessError
from odoo.service.model import call_kw
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestEbarimtSecurity(TestPoSCommon):
    """A cashier can read the PosAPI record and every order, so nothing
    reachable over RPC may send the gateway key, issue or void a bill, or
    reset the sending status."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.open_new_session()
        self.posapi = self.env['account.ebarimt.posapi'].create({
            'name': 'Test PosAPI', 'service_url': 'http://127.0.0.1:1', 'company_id': self.env.company.id,
        })
        self.order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
        })
        self.bill = self.env['vat.receipt'].create({
            'pos_order_id': self.order.id, 'bill_id': 'BILL-1', 'bill_state': 'done',
        })
        groups = lambda *xmlids: [(6, 0, [self.env.ref(x).id for x in xmlids])]
        self.cashier = self.env['res.users'].create({
            'name': 'Cashier', 'login': 'ebarimt_cashier',
            'group_ids': groups('base.group_user', 'point_of_sale.group_pos_user'),
        })
        self.accountant = self.env['res.users'].create({
            'name': 'Accountant', 'login': 'ebarimt_accountant',
            'group_ids': groups('base.group_user', 'account.group_account_manager'),
        })

    def _rpc(self, user, model, method, *args):
        return call_kw(self.env(user=user)[model], method, list(args), {})

    def test_cashier_cannot_call_posapi(self):
        for method in ('_request_connection', '_request_receipt', '_return_receipt'):
            with self.assertRaises(AccessError):
                self._rpc(self.cashier, 'account.ebarimt.posapi', method, [self.posapi.id], {})

    def test_cashier_cannot_issue_or_void_bills(self):
        with self.assertRaises(AccessError):
            self._rpc(self.cashier, 'pos.order', 'return_ebarimt', [self.order.id])
        with self.assertRaises(AccessError):
            self._rpc(self.cashier, 'pos.order', '_ebarimt_send_manual', [self.order.id], 'B2C_RECEIPT')
        with self.assertRaises(AccessError):
            self._rpc(self.cashier, 'pos.order', 'write', [self.order.id], {'vat_sent': True})
        # The POS sync writes the same value back: that stays allowed.
        self._rpc(self.cashier, 'pos.order', 'write', [self.order.id], {'vat_sent': self.order.vat_sent})

    def test_only_admin_changes_service_url(self):
        posapi = self.posapi.with_user(self.accountant)
        with self.assertRaises(AccessError):
            posapi.write({'service_url': 'http://elsewhere'})
        with self.assertRaises(AccessError):
            posapi.create({'name': 'Other', 'service_url': 'http://elsewhere'})
        posapi.write({'send_interval_unit': 'daily'})

    def test_bills_are_read_only(self):
        bill = self.bill.with_user(self.accountant)
        self.assertEqual(bill.bill_id, 'BILL-1')
        with self.assertRaises(AccessError):
            bill.write({'bill_state': 'old'})
        with self.assertRaises(AccessError):
            bill.unlink()
