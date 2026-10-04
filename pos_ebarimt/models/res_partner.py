from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _load_pos_data_fields(self, config):
        # 19.0: the POS only receives the partner fields listed here. The
        # eBarimt popup reads ``vat_tin`` (falls back to ``vat``).
        fields = super()._load_pos_data_fields(config)
        if fields and 'vat_tin' not in fields:
            fields = fields + ['vat_tin']
        return fields
