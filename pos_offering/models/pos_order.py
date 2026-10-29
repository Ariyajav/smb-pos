from odoo import fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    offering_from = fields.Char("Offering From")
    offering_family_size = fields.Integer("Family Members")
    offering_day = fields.Char("Reading Day")

    # Offerings are not sales: their lines never go to eBarimt. An order that
    # has only offering lines therefore gets no bill at all.

    def _ebarimt_sold_lines(self):
        return [(line, qty) for line, qty in super()._ebarimt_sold_lines()
                if not line.product_id.offering_kind]

    def _ebarimt_returns_lines(self):
        return any(line.refunded_orderline_id and line.qty < 0 and not line.product_id.offering_kind
                   for line in self.lines)
