from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = "sale.order"

    vat_tin = fields.Char("VAT Tin No", related="partner_id.vat_tin", readonly=True)

    # sale_order.py файлд нэмэх
    def _get_ebarimt_data(self):
        """Get eBarimt data from related invoice"""
        self.ensure_one()
        if self.invoice_ids:
            for invoice in self.invoice_ids:
                if invoice.vat_receipts:
                    receipt = invoice.vat_receipts[0]
                    return {
                        'bill_id': receipt.bill_id,
                        'date': receipt.sent_at,
                        'vat': receipt.vat,
                        'city_tax': receipt.city_tax,
                        'amount': receipt.amount,
                        'bill_type': receipt.bill_type,
                        'lottery': receipt.lottery or None,
                        'qr_data': receipt.qr_data or None
                    }
        return False
