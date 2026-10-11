from odoo import api, models, fields, _
from odoo.exceptions import ValidationError

# A product's eBarimt classification code: a 7-digit BUNA code.
BUNA_CODE_DOMAIN = [('code', '=like', '_' * 7)]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    buna_classification_id = fields.Many2one(
        "product.classification.buna", 
        "БҮНА Classification",
        domain=BUNA_CODE_DOMAIN,
        help="БҮНА classification code for eBarimt"
    )

    @api.constrains('buna_classification_id', 'vat_classification_id')
    def _check_ebarimt_classification(self):
        """Only codes loaded into the BUNA list may be used on products."""
        Buna = self.env['product.classification.buna'].sudo()
        for template in self:
            buna = template.buna_classification_id
            if buna and not buna.filtered_domain(BUNA_CODE_DOMAIN):
                raise ValidationError(_(
                    "%(product)s: BUNA %(code)s is a category, not a 7-digit product code.",
                    product=template.display_name, code=buna.code))
            code = template.vat_classification_id.name
            if code and not Buna.search_count([('code', '=', code)] + BUNA_CODE_DOMAIN):
                raise ValidationError(_(
                    "%(product)s: classification code %(code)s is not in the BUNA list. "
                    "Load it under Accounting > Configuration > БҮНА Classifications first.",
                    product=template.display_name, code=code))

    def action_select_buna_classification(self):
        """БҮНА ангилал сонгох wizard нээх"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'БҮНА Ангилал сонгох',
            'res_model': 'product.classification.buna',
            'view_mode': 'list',
            'domain': BUNA_CODE_DOMAIN,
            'target': 'new',
            'context': {
                'create': False,
                'edit': False,
            }
        }
