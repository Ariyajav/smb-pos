import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

class ProductTemplate(models.Model):
    _inherit = "product.template"

    vat_classification_id = fields.Many2one("product.classification.code", "Classification Code")
    vat_code_id = fields.Many2one("product.vat.code", "VAT Code")


class ClassificationCode(models.Model):
    _name = "product.classification.code"
    _description = "Seven digits of Classification Code of products and services"

    name = fields.Char("Classification Code", required=True, size=7)
    label = fields.Char("Classification Name")


class VatCode(models.Model):
    _name = "product.vat.code"
    _description = "3-10 digit tax product code for VAT_FREE, VAT_ZERO and NOT_VAT items"

    name = fields.Char("VAT code", required=True, size=10)
    label = fields.Text("Label")
    tax_type = fields.Selection(
        [
            ("VAT_FREE", "VAT Free"),
            ("VAT_ZERO", "VAT Zero %"),
            ("NOT_VAT", "Not a VAT payer"),
        ],
        'Vat Type',
        default="VAT_FREE",
    )

    @api.constrains('name')
    def _check_name_digits(self):
        # PosAPI rejects a taxProductCode that is not a 3-10 digit number.
        for code in self:
            if not re.fullmatch(r'\d{3,10}', (code.name or '').strip()):
                raise ValidationError(_("VAT code must be a number of 3 to 10 digits, e.g. 305 (got %s).", code.name))
