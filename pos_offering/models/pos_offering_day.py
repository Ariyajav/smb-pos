from odoo import api, fields, models


class PosOfferingDay(models.Model):
    """Days a reading can be ordered for, offered in a list at the till."""
    _name = "pos.offering.day"
    _description = "Offering Reading Day"
    _inherit = ["pos.load.mixin"]
    _order = "sequence, id"

    name = fields.Char("Reading Day", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [("active", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["name", "sequence"]
