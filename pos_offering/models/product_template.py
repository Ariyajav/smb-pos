from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    offering_kind = fields.Selection(
        [("reading", "Reading"), ("amount", "Offering amount")],
        string="Offering",
        help="Reading: a prayer reading with no fixed price; the cashier enters "
             "one offering amount for the whole order on Payment.\n"
             "Offering amount: the product that carries that amount on the order.\n"
             "Orders with offerings get no eBarimt bill.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["offering_kind"]
