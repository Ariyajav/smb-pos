from odoo import models, fields

class PosConfig(models.Model):
    _inherit = "pos.config"

    send_ebarimt = fields.Boolean(
        string="Send eBarimt",
        default=True,
        help="Automatically send eBarimt receipts when orders are paid"
    )

    branch_code_id = fields.Many2one(
        comodel_name="disctric.code",
        string="Branch Code",
        help="Select the branch code for eBarimt reporting"
    )

    ebarimt_branch_no = fields.Char(
        string="eBarimt Branch No",
        help="branchNo sent to PosAPI for this POS. Empty: the POS's internal "
             "number, padded to 4 digits (what was always sent before)."
    )

    receipt_paper_width = fields.Selection(
        selection=[("80", "80 mm"), ("58", "58 mm")],
        string="Receipt Paper Width",
        default="80",
        required=True,
        help="Paper width of this POS's receipt printer. 58 mm prints a "
             "narrower receipt with a larger eBarimt QR code."
    )


class ResCompany(models.Model):
    _inherit = "res.company"

    service_url = fields.Char(
        string="POS API Request URL",
        help="URL for eBarimt POS API service"
    )

    parent_merchant_tin = fields.Char(
        string="Parent Merchant TIN",
        help="Tax Identification Number for Parent Merchant in eBarimt")

    ebarimt_pos_number = fields.Char(string="Ebarimt pos number")

    vat_tin = fields.Char(
        string="Company TIN",
        help="Tax Identification Number for eBarimt"
    )
    branch_no = fields.Char(
        string="Branch No",
        readonly=True, 
        default="12",
        help="Branch number for eBarimt reporting"
    )