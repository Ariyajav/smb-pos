from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestDistrictAddressSync(TransactionCase):
    """Tax agency branches become the Mongolian states / sub-states."""

    def test_sync_builds_matching_address(self):
        data = [
            {'branchCode': '98', 'branchName': 'Test aimag', 'subBranchCode': '01', 'subBranchName': 'Test sum'},
            {'branchCode': '98', 'branchName': 'Test aimag', 'subBranchCode': '02', 'subBranchName': 'Other sum'},
        ]
        self.env['disctric.code']._sync_mn_address(data)
        mn = self.env.ref('base.mn')
        state = self.env['res.country.state'].search([('country_id', '=', mn.id), ('code', '=', '98')])
        self.assertEqual(state.name, 'Test aimag')
        sub = state.sub_state_ids.filtered(lambda s: s.code == '01')
        self.assertEqual(sub.name, 'Test sum')

        partner = self.env['res.partner'].create({
            'name': 'Shop', 'country_id': mn.id, 'state_id': state.id, 'sub_state_id': sub.id,
        })
        self.assertEqual(partner.district_code, '9801')

        # A sub-branch the tax agency dropped is archived.
        self.env['disctric.code']._sync_mn_address(data[:1])
        other = self.env['res.country.sub.state'].with_context(active_test=False).search(
            [('state_id', '=', state.id), ('code', '=', '02')])
        self.assertFalse(other.active)
