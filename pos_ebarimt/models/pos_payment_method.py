from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    ebarimt_payment_code = fields.Selection(
        [
            ("CASH", "Cash"),
            ("PAYMENT_CARD", "Payment card"),
            ("BANK_TRANSFER", "Bank transfer"),
        ],
        string="eBarimt Payment Code",
        help="Payment code sent to PosAPI. Leave empty to use Cash for cash "
             "methods and Bank transfer for the others.",
    )

    def _get_ebarimt_payment_code(self):
        self.ensure_one()
        if self.ebarimt_payment_code:
            return self.ebarimt_payment_code
        # Odoo 19 payment method types are only cash / bank / pay_later.
        return "CASH" if self.type == "cash" else "BANK_TRANSFER"
