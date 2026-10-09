from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.addons.pos_ebarimt.models.pos_order import EbarimtDataError

GET = 'odoo.addons.pos_ebarimt.models.pos_order.requests.get'


def _tin_info(data, status=200, msg=''):
    response = MagicMock()
    response.json.return_value = {'status': status, 'msg': msg, 'data': data}
    return response


@tagged('post_install', '-at_install')
class TestCustomerTin(TestPoSCommon):
    """A B2B bill needs the buyer's 11-14 digit TIN; cashiers often type
    the company's registry number instead."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.open_new_session()
        self.order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
        })

    def test_tin_is_used_as_is(self):
        with patch(GET) as get:
            self.assertEqual(self.order._ebarimt_resolve_customer_tin(' 61200064714 '), '61200064714')
        get.assert_not_called()

    def test_registry_number_is_looked_up(self):
        with patch(GET, return_value=_tin_info(61200064714)) as get:
            self.assertEqual(self.order._ebarimt_resolve_customer_tin('5520584'), '61200064714')
        self.assertEqual(get.call_args.kwargs['params'], {'regNo': '5520584'})
        self.assertEqual(self.order.ebarimt_customer_tin, '61200064714')

    def test_consumer_number_is_refused(self):
        with patch(GET) as get, self.assertRaises(EbarimtDataError):
            self.order._ebarimt_resolve_customer_tin('99119911')
        get.assert_not_called()

    def test_unknown_registry_number_needs_a_person(self):
        with patch(GET, return_value=_tin_info(None, 500, 'not found')), self.assertRaises(EbarimtDataError):
            self.order._ebarimt_resolve_customer_tin('1234567')

    def test_lookup_outage_is_retried(self):
        with patch(GET, side_effect=requests.ConnectionError('down')), self.assertRaises(UserError) as caught:
            self.order._ebarimt_resolve_customer_tin('5520584')
        self.assertNotIsInstance(caught.exception, EbarimtDataError)
