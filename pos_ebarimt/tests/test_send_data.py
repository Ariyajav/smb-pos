from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

POSAPI = 'odoo.addons.ebarimt_api.models.ebarimt.eBarimtPosAPI'


@tagged('post_install', '-at_install')
class TestPosSendData(TransactionCase):
    """The POS "eBarimt илгээх" button calls PosAPI sendData."""

    def setUp(self):
        super().setUp()
        self.posapi = self.env['account.ebarimt.posapi'].create({
            'name': 'Test PosAPI', 'service_url': 'http://posapi.test:9080',
            'company_id': self.env.company.id,
        })

    def _call(self, responses):
        calls = []

        def fake(rec, url, headers, params, request_type='GET', timeout=None):
            calls.append(url)
            return responses[url.rsplit('/', 1)[1]]
        with patch(POSAPI + '._request_connection', fake):
            result = self.env['account.ebarimt.posapi'].pos_send_data(self.env.company.id)
        return result, calls

    def test_success_reports_last_sent(self):
        result, calls = self._call({
            'sendData': (200, {}), 'info': (200, {'lastSentDate': '2026-10-11 07:30:00'}),
        })
        self.assertTrue(result['ok'])
        self.assertIn('2026-10-11 07:30:00', result['message'])
        self.assertEqual(calls[0], 'http://posapi.test:9080/rest/sendData')
        self.assertTrue(self.posapi.last_send_date)

    def test_failure_is_reported(self):
        result, _calls = self._call({'sendData': (500, {'message': 'down'})})
        self.assertFalse(result['ok'])
        self.assertIn('500', result['message'])
