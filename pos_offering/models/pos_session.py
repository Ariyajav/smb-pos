from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        return super()._load_pos_data_models(config) + ["pos.offering.day"]
