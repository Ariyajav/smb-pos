from odoo import models, fields

class AccountTax(models.Model):
    _inherit = "account.tax"

    ebarimt_send_data = fields.Boolean("Will data be sent to eBarimt PosAPI?")

    ebarimt_tax_type = fields.Selection(
        [
            ("VAT_ABLE", "Normal VAT"),
            ("VAT_FREE", "VAT Free"),
            ("VAT_ZERO", "VAT Zero %"),
        ],
        "eBarimt Tax Type",
        default="VAT_ABLE",
    )

    city_tax = fields.Boolean("Is This City Tax?")
