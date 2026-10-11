import datetime

from freezegun import freeze_time

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestBillDate(TransactionCase):
    """sent_at is the server's clock; PosAPI's date is kept unchanged for returns."""

    def test_sent_at_is_server_time(self):
        with freeze_time('2026-10-11 11:17:00'):
            vals = self.env['vat.receipt']._posapi_sent_vals('2026-10-11 19:17:00')
        self.assertEqual(vals['sent_at'], datetime.datetime(2026, 10, 11, 11, 17, 0))
        self.assertEqual(vals['posapi_date'], '2026-10-11 19:17:00')

    def test_missing_date_uses_now(self):
        vals = self.env['vat.receipt']._posapi_sent_vals(None)
        self.assertTrue(vals['sent_at'])
        self.assertFalse(vals['posapi_date'])

    def test_return_date_is_raw_posapi_date(self):
        receipt = self.env['vat.receipt'].new({
            'sent_at': datetime.datetime(2026, 10, 11, 11, 17, 0),
            'posapi_date': '2026-10-11 19:17:00',
        })
        self.assertEqual(receipt._posapi_return_date(), '2026-10-11 19:17:00')
