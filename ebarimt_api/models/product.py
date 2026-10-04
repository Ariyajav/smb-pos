from odoo import models, fields

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
    _description = "Three digits of code when tax type is either VAT_FREE or VAT_ZERO"

    name = fields.Char("VAT code", required=True, size=3)
    label = fields.Text("Label")
    tax_type = fields.Selection(
        [
            ("VAT_FREE", "VAT Free"),
            ("VAT_ZERO", "VAT Zero %"),
        ],
        'Vat Type',
        default="VAT_FREE",
    )
