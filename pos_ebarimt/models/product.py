from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = "product.template"

    buna_classification_id = fields.Many2one(
        "product.classification.buna", 
        "БҮНА Classification",
        domain=[('level', '=', 'buna_code')],
        help="БҮНА classification code for eBarimt"
    )
    
    def action_select_buna_classification(self):
        """БҮНА ангилал сонгох wizard нээх"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'БҮНА Ангилал сонгох',
            'res_model': 'product.classification.buna',
            'view_mode': 'list',
            'domain': [],  # Зөвхөн БҮНА код харуулах
            'target': 'new',
            'context': {
                'create': False,
                'edit': False,
            }
        }