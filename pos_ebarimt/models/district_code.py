import requests
from odoo import fields, api, models, _
import logging

_logger = logging.getLogger(__name__)


class DistrictCode(models.Model):
    _name = 'disctric.code'
    _description = 'District code'
    _rec_name = 'combined_code'

    branch_code = fields.Char(string="Branch Code")
    branch_name = fields.Char(string="Branch Name")
    subbranch_code = fields.Char(string="Subbranch Code")
    subbranch_name = fields.Char(string="Subbranch Name")
    combined_code = fields.Char(string="Combined Code", compute="_compute_combined_code", store=True)

    @api.depends('branch_code', 'subbranch_code')
    def _compute_combined_code(self):
        for record in self:
            if record.branch_code and record.subbranch_code:
                record.combined_code = f"{record.branch_code}{record.subbranch_code}"
            else:
                record.combined_code = record.branch_code or record.subbranch_code or ""

    def request(self):
        url = "https://api.ebarimt.mn/api/info/check/getBranchInfo"
        headers = {'Accept': 'application/json'}

        try:
            _logger.info("District code request → %s", url)
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return {'success': True, 'data': response.json()}
        except requests.RequestException as e:
            _logger.error("District Code error: %s", e)
            return {'success': False, 'error': str(e)}

    def get_district_code_data(self):
        results = self.request()
        if results.get('success'):
            response_data = results.get('data')
            district_data = response_data.get('data', [])
            
            _logger.info("District code data retrieved successfully")
            
            # Update in place: deleting and recreating the codes emptied the
            # Branch Code of every POS that pointed at one.
            existing = {
                (rec.branch_code, rec.subbranch_code): rec for rec in self.search([])
            }
            for item in district_data:
                vals = {
                    'branch_code': item.get('branchCode'),
                    'branch_name': item.get('branchName'),
                    'subbranch_code': item.get('subBranchCode'),
                    'subbranch_name': item.get('subBranchName'),
                }
                rec = existing.get((vals['branch_code'], vals['subbranch_code']))
                if rec:
                    if rec.branch_name != vals['branch_name'] or rec.subbranch_name != vals['subbranch_name']:
                        rec.write(vals)
                else:
                    self.create(vals)

            _logger.info("Synced %d district code records", len(district_data))
            return True
        else:
            error = results.get('error')
            _logger.error("Failed to retrieve District Code data: %s", error)
            return False