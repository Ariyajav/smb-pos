from odoo import fields, models, _


class ProductClassificationBunaLoad(models.TransientModel):
    _name = 'product.classification.buna.load'
    _description = 'Load BUNA codes from eBarimt'

    codes = fields.Char(
        'BUNA codes', required=True,
        help="Codes to load with everything under them, separated by commas. "
             "Example: 61184, 9591",
    )

    def action_load(self):
        self.ensure_one()
        Buna = self.env['product.classification.buna']
        loaded = []
        for code in filter(None, (c.strip() for c in self.codes.split(','))):
            loaded.append('%s: %d' % (code, Buna.load_code_subtree(code)))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('BUNA codes loaded'),
                'message': _('7-digit codes loaded: %s', ', '.join(loaded)),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
