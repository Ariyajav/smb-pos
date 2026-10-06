from odoo import fields, models, _
from odoo.exceptions import UserError

class eBarimtConfirmation(models.TransientModel):
    _name = "account.ebarimt.confirmation"
    _description = "Ask Confirmation when sending eBarimt"

    bill_type_individual = fields.Boolean('Sales for Individual', default=True)


    def _bill_type_prefix(self):
        return 'B2C_' if self.bill_type_individual else 'B2B_'

    def action_send(self):
        """Send every selected record. The bill type is worked out per record
        (it used to grow across records, e.g. B2C_RECEIPTB2C_RECEIPT), and
        POS orders that already have a bill are refused instead of billed
        twice. (An invoice may be sent again: its receipt replaces the earlier
        invoice bill through inactiveId.)"""
        self.ensure_one()
        res_model = self.env.context.get('active_model')
        records = self.env[res_model].browse(self.env.context.get('active_ids') or []) if res_model else []
        bill_ids = []
        if res_model == "account.move":
            for invoice in records:
                bill_type = self._bill_type_prefix() + ('RECEIPT' if invoice.amount_residual == 0 else 'INVOICE')
                invoice.vat_invoice_commit(bill_type=bill_type)
                bill_ids += invoice.vat_receipts.sorted('create_date', reverse=True)[:1].mapped('bill_id')
        elif res_model == "pos.order":
            for order in records:
                bill_type = self._bill_type_prefix() + ('RECEIPT' if order.payment_ids else 'INVOICE')
                if not hasattr(order, '_ebarimt_send_manual'):
                    raise UserError(_("Install pos_ebarimt to send eBarimt bills of POS orders."))
                order._ebarimt_send_manual(bill_type)
                bill_ids += order.vat_receipts.sorted('create_date', reverse=True)[:1].mapped('bill_id')
        if bill_ids:
            return {
                'effect': {
                    'fadeout': 'slow',
                    'message': _("Data has been sent to the eBarimt.mn system. Bill id: %s", ", ".join(bill_ids)),
                    'type': 'rainbow_man',
                }
            }
        return True
