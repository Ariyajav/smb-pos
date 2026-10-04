from odoo import api, models, fields, _
from odoo.fields import Domain
from odoo.exceptions import ValidationError
import requests
import logging

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    # Аймаг/Муж
    state_id = fields.Many2one(
        'res.country.state', 
        string='State/Province',
        domain="[('country_id', '=?', country_id)]"
    )
    
    # Сум/Дүүрэг (state_id-аас хамаарах)
    sub_state_id = fields.Many2one(
        'res.country.sub.state',
        string='District/Sub-state', 
        domain="[('state_id', '=?', state_id)]"
    )
    
    # Дүүргийн код (автомат тооцоолох)
    district_code = fields.Char(
        string="District Code", 
        readonly=True, 
        compute="_compute_district_code", 
        store=True,
        help="Auto-computed from State and Sub-state codes"
    )

    vat_tin = fields.Char("VAT Tin No", help="Tax Identification Number from eBarimt")
    vat_payer = fields.Boolean("VAT Payer", default=True)
    vat_send_payment = fields.Boolean("VAT Send Payment", default=True)
    
    # eBarimt мэдээлэл
    ebarimt_verified = fields.Boolean("eBarimt Verified", default=False, readonly=True)
    ebarimt_verification_date = fields.Datetime("Last Verified", readonly=True)
    ebarimt_company_name = fields.Char("Company Name (from eBarimt)", readonly=True)
    ebarimt_status = fields.Char("eBarimt Status", readonly=True)

    @api.depends('state_id', 'sub_state_id')
    def _compute_district_code(self):
        for partner in self:
            if partner.state_id and partner.sub_state_id:
                # state_id болон sub_state_id-н код-г нэгтгэх
                state_code = partner.state_id.code if partner.state_id.code else ''
                sub_state_code = partner.sub_state_id.code if partner.sub_state_id.code else ''
                partner.district_code = state_code + sub_state_code
            else:
                partner.district_code = ""

    @api.onchange('country_id')
    def _onchange_country_id(self):
        """Улс солигдоход state болон sub_state цэвэрлэх"""
        if self.country_id:
            self.state_id = False
            self.sub_state_id = False

    @api.onchange('state_id')
    def _onchange_state_id(self):
        """State солигдоход sub_state цэвэрлэх"""
        if self.state_id:
            self.sub_state_id = False

    @api.onchange('vat')
    def _onchange_partner_vat(self):
        """VAT дугаар солигдоход eBarimt-аас мэдээлэл татах"""
        if self.vat and len(self.vat.strip()) >= 7:  # Монголын регистрийн дугаар 7+ тэмдэгт
            self._fetch_ebarimt_info()

    def _fetch_ebarimt_info(self):
        """eBarimt API-аас мэдээлэл татах"""
        if not self.vat:
            return
            
        try:
            # VAT дугаараас цэвэр тоонуудыг авах
            clean_vat = ''.join(filter(str.isdigit, self.vat))
            if len(clean_vat) < 7:
                return
                
            _logger.info(f"Fetching eBarimt info for VAT: {clean_vat}")
            
            # eBarimt API дуудах
            url = f"https://api.ebarimt.mn/api/info/check/getTinInfo?regNo={clean_vat}"
            headers = {"Accept": "application/json"}
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("status") == 200 and result.get("data"):
                    data = result.get("data")
                    
                    # Мэдээллийг шинэчлэх
                    self.vat_tin = data.get("tin", "")
                    self.ebarimt_company_name = data.get("name", "")
                    self.ebarimt_status = data.get("status", "")
                    self.ebarimt_verified = True
                    self.ebarimt_verification_date = fields.Datetime.now()
                    
                    # Хэрэв компанийн нэр олдсон бол partner-ийн нэрийг шинэчлэх (сонголт)
                    if not self.name and self.ebarimt_company_name:
                        self.name = self.ebarimt_company_name
                    
                    _logger.info(f"Successfully fetched eBarimt info for {clean_vat}")
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Success'),
                            'message': _('eBarimt information updated successfully'),
                            'type': 'success'
                        }
                    }
                else:
                    # API-аас алдаа ирсэн
                    error_msg = result.get("msg", "Unknown error")
                    _logger.warning(f"eBarimt API error for {clean_vat}: {error_msg}")
                    
                    self.ebarimt_verified = False
                    self.ebarimt_verification_date = fields.Datetime.now()
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Warning'),
                            'message': _('Could not verify VAT: %s') % error_msg,
                            'type': 'warning'
                        }
                    }
            else:
                _logger.error(f"eBarimt API HTTP error: {response.status_code}")
                
        except requests.exceptions.Timeout:
            _logger.error(f"eBarimt API timeout for VAT: {self.vat}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Connection timeout - please try again later'),
                    'type': 'danger'
                }
            }
        except Exception as ex:
            _logger.error(f"Error fetching eBarimt info for {self.vat}: {str(ex)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Could not fetch eBarimt info: %s') % str(ex),
                    'type': 'danger'
                }
            }

    def action_verify_ebarimt(self):
        """Manual verification товчлуур"""
        if not self.vat:
            raise ValidationError(_("VAT number is required for verification"))
        
        result = self._fetch_ebarimt_info()
        if result:
            return result
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Info'),
                'message': _('Verification completed'),
                'type': 'info'
            }
        }

    def action_clear_ebarimt_info(self):
        """eBarimt мэдээллийг цэвэрлэх"""
        self.write({
            'vat_tin': False,
            'ebarimt_verified': False,
            'ebarimt_verification_date': False,
            'ebarimt_company_name': False,
            'ebarimt_status': False,
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('eBarimt information cleared'),
                'type': 'success'
            }
        }

    @api.model
    def get_district_code_for_company(self, company_id=None):
        """Компанийн district code авах helper method"""
        if not company_id:
            company_id = self.env.company.id
        
        company = self.env['res.company'].browse(company_id)
        partner = company.partner_id
        
        if partner.district_code:
            return partner.district_code
        
        # Fallback: API-аас авах
        try:
            url = "https://api.ebarimt.mn/api/info/check/getBranchInfo"
            headers = {"Accept": "application/javascript"}
            response = requests.get(url, headers=headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200 and 'data' in data:
                    branch_code = data['data'].get('branchCode', '01')
                    sub_branch_code = data['data'].get('subBranchCode', '01')
                    return f"{branch_code}{sub_branch_code}"
        except:
            pass
        
        # Final fallback
        return "0101"  # Улаанбаатар default


# Сум/Дүүргийн модель
class ResCountrySubState(models.Model):
    _name = "res.country.sub.state"
    _description = "Sub-states (Districts)"
    _order = 'name'

    name = fields.Char('Sub-state Name', required=True, translate=True)
    code = fields.Char('Sub-state Code', required=True, size=10)
    state_id = fields.Many2one('res.country.state', 'State', required=True, ondelete='cascade')
    country_id = fields.Many2one('res.country', related='state_id.country_id', store=True, readonly=True)
    active = fields.Boolean('Active', default=True)

    _name_code_uniq = models.Constraint(
        'unique(state_id, code)',
        'The code of the sub-state must be unique by state!',
    )
    _code_length = models.Constraint(
        'check(length(code) >= 2)',
        'Sub-state code must be at least 2 characters!',
    )

    @api.depends('code', 'name', 'state_id.name')
    def _compute_display_name(self):
        """Display format: [Code] Name, State"""
        for record in self:
            name = f"[{record.code}] {record.name}"
            if record.state_id:
                name += f", {record.state_id.name}"
            record.display_name = name

    @api.model
    def _search_display_name(self, operator, value):
        """Search by name or code (replaces the 16.0 ``_name_search`` override)."""
        if operator in ('ilike', 'like', '=ilike', '=like', '=') and value and isinstance(value, str):
            words = value.split()
            return Domain.OR([
                [('name', operator, value)],
                [('code', operator, value)],
                [('name', 'ilike', words[0] if words else value)],
            ])
        return super()._search_display_name(operator, value)


class ResCountryState(models.Model):
    _inherit = "res.country.state"
    
    sub_state_ids = fields.One2many('res.country.sub.state', 'state_id', 'Sub-states')
    sub_state_count = fields.Integer('Sub-states Count', compute='_compute_sub_state_count')

    @api.depends('sub_state_ids')
    def _compute_sub_state_count(self):
        for state in self:
            state.sub_state_count = len(state.sub_state_ids)