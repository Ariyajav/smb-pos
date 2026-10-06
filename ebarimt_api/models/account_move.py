import json
import datetime
import requests
import logging
from odoo import api, models, fields, _
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    vat_sent = fields.Boolean('eBarimt Sent?', default=False)
    vat_invoice_sent = fields.Boolean('eBarimt Invoice Sent?', default=False)
    vat_receipts = fields.One2many("vat.receipt", "account_move_id", "eBarimt Receipts")
    vat_bill_state = fields.Selection([
        ('done', 'Bill Sent'),
        ('old', 'Needs to be Refunded'),
        ('refund', 'Refunded'),
        ('invoice', 'Invoice')
    ], "VAT Bill State", compute="_compute_vat_bill_state", search="_search_vat_bill_state")

    def get_district_code_from_api(self):
        """eBarimt API-аас district code татаж авах"""
        try:
            url = "https://api.ebarimt.mn/api/info/check/getBranchInfo"
            headers = {"Accept": "application/javascript"}
            
            # Timeout болон SSL verification нэмэх
            response = requests.get(url, headers=headers, timeout=10, verify=True)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200 and 'data' in data:
                    branch_code = data['data'].get('branchCode', '01')
                    sub_branch_code = data['data'].get('subBranchCode', '01')
                    district_code = f"{branch_code}{sub_branch_code}"
                    
                    _logger.info(f"Successfully retrieved district code: {district_code}")
                    return district_code
                else:
                    _logger.warning(f"API returned error: {data.get('msg', 'Unknown error')}")
                    return self.get_default_district_code()
            else:
                _logger.warning(f"API request failed with status: {response.status_code}")
                return self.get_default_district_code()
                
        except requests.exceptions.Timeout:
            _logger.error("API request timeout - using default district code")
            return self.get_default_district_code()
        except requests.exceptions.ConnectionError:
            _logger.error("API connection error - using default district code")
            return self.get_default_district_code()
        except requests.exceptions.RequestException as e:
            _logger.error(f"API request error: {e} - using default district code")
            return self.get_default_district_code()
        except Exception as e:
            _logger.error(f"Unexpected error getting district code: {e}")
            return self.get_default_district_code()

    def get_default_district_code(self):
        """Default district code буцаах"""
        # Company partner дээрх district_code шалгах
        if hasattr(self.company_id.partner_id, 'district_code') and self.company_id.partner_id.district_code:
            return self.company_id.partner_id.district_code
        
        # System parameter-аас авах
        default_code = self.env['ir.config_parameter'].sudo().get_param('ebarimt.default_district_code', '0101')
        return default_code

    def get_district_code(self):
        """Компанийн дүүргийн кодыг олж авах - нэгтгэсэн method"""
        # Эхлээд API-аас татаж үзэх
        api_code = self.get_district_code_from_api()
        
        # Хэрэв API ажиллахгүй бол cache эсвэл default ашиглах
        if api_code == self.get_default_district_code():
            # Cache-аас шалгах (1 цагийн cache)
            cache_key = 'ebarimt_district_code'
            cache_time_key = 'ebarimt_district_code_time'
            
            cached_code = self.env['ir.config_parameter'].sudo().get_param(cache_key)
            cached_time = self.env['ir.config_parameter'].sudo().get_param(cache_time_key)
            
            if cached_code and cached_time:
                try:
                    cache_datetime = datetime.datetime.fromisoformat(cached_time)
                    if datetime.datetime.now() - cache_datetime < datetime.timedelta(hours=1):
                        _logger.info(f"Using cached district code: {cached_code}")
                        return cached_code
                except:
                    pass
        else:
            # API-аас амжилттай авсан бол cache-д хадгалах
            self.env['ir.config_parameter'].sudo().set_param('ebarimt_district_code', api_code)
            self.env['ir.config_parameter'].sudo().set_param('ebarimt_district_code_time', datetime.datetime.now().isoformat())
            return api_code
        
        return self.get_default_district_code()

    @api.depends('vat_receipts', 'vat_receipts.bill_state')
    def _compute_vat_bill_state(self):
        for rec in self:
            invoice_vat_receipt = self.env['vat.receipt'].search([
                ('account_move_id', '=', rec.id)
            ], order="create_date desc", limit=1)
            if invoice_vat_receipt:
                rec.vat_bill_state = invoice_vat_receipt.bill_state
            else:
                rec.vat_bill_state = False

    def _search_vat_bill_state(self, operator, value):
        """vat_bill_state is not stored. Odoo 16 silently ignored domains on it
        (it logged "Non-stored field ... cannot be searched" and dropped the
        leaf); Odoo 19 raises instead, so implement the intended semantics:
        the bill_state of the latest vat.receipt of each move."""
        if operator not in ('in', 'not in'):
            return NotImplemented
        receipts = self.env['vat.receipt'].search_fetch(
            [('account_move_id', '!=', False)],
            ['account_move_id', 'bill_state'],
            order='create_date desc, id desc',
        )
        latest = {}
        for receipt in receipts:
            latest.setdefault(receipt.account_move_id.id, receipt.bill_state)
        values = set(value)
        matching = [move_id for move_id, state in latest.items() if state in values]
        if False in values:
            # moves without any receipt have vat_bill_state = False
            domain = ['|', ('id', 'in', matching), ('vat_receipts', '=', False)]
        else:
            domain = [('id', 'in', matching)]
        if operator == 'not in':
            domain = ['!', *domain]
        return domain

    def action_post(self):
        """Override: Prevent Expected singleton error during batch posting"""
        res = super(AccountMove, self).action_post()

        for move in self:
            # Refund төрөлтэй, sale order-той холбоотой баримтуудыг шалгах
            if move.move_type == 'out_refund' and move.sale_order_count > 0:
                quantity = 0
                sol_ids = []

                # Баримтын мөрүүдийг шалгах
                for line in move.line_ids:
                    for sale_line in line.sale_line_ids:
                        quantity += sale_line.product_uom_qty
                        sol_ids.append(sale_line.id)

                # Холбоотой invoice-уудыг хайна
                invoices = self.env["account.move"].search([
                    ('line_ids.sale_line_ids.id', 'in', sol_ids),
                    ('vat_bill_state', 'in', ('done', 'invoice'))
                ])

                _logger.info(f"[eBarimt Refund] Found related invoices for move {move.id}: {invoices.ids}")

                # Хэрэв буцаалтын тоо хэмжээ 0 бол eBarimt илгээсэн гэж тэмдэглэнэ
                if quantity == 0:
                    move.vat_sent = True
                    move.vat_invoice_sent = True

                # Холбогдсон invoice бүр дээр eBarimt буцаах логикийг ажиллуулна
                for invoice in invoices:
                    if invoice.id != move.id:
                        try:
                            invoice._ebarimt_return_bill()
                            _logger.info(f"[eBarimt Refund] Returned eBarimt for invoice {invoice.id}")
                        except Exception as e:
                            _logger.error(f"[eBarimt Refund] Error returning eBarimt for invoice {invoice.id}: {e}")

        return res


    def _get_classification_code(self, product_item):
        """Бүтээгдэхүүний classification code авах"""
        try:
            # 1. БҮНА classification ашиглах
            if (hasattr(product_item.product_tmpl_id, 'buna_classification_id') 
                and product_item.product_tmpl_id.buna_classification_id 
                and product_item.product_tmpl_id.buna_classification_id.p6):
                
                buna_code = product_item.product_tmpl_id.buna_classification_id.p6
                return buna_code.zfill(7)
            
            # 2. Хуучин classification ашиглах
            if (hasattr(product_item.product_tmpl_id, 'vat_classification_id') 
                and product_item.product_tmpl_id.vat_classification_id):
                return product_item.product_tmpl_id.vat_classification_id.name
            
            return "8640500"
            
        except Exception as e:
            _logger.warning(f"Classification code авахад алдаа: {e}")
            return "8640500"

    def generate_receipt_values(self, company_tin, type, invoice_line_ids=[], previous_inactive_id=[]):
        def create_items(tax_type, line_id, invoice_qty=None):
            item = self.env['account.move.line'].search([('id', '=', line_id)])
            product_item = item.product_id
            item_unit_price = item.price_unit * (1 - (item.discount / 100.0)) if item.discount else item.price_unit
            
            total_amounts = item.tax_ids.compute_all(
                item_unit_price,
                item.currency_id,
                (invoice_qty or item.quantity),
                product=product_item,
                partner=item.move_id.partner_id,
            )
            
            total_vat = total_amounts['total_included'] - total_amounts['total_excluded']
            has_city_tax = item.tax_ids.filtered(lambda x: hasattr(x, 'city_tax') and x.city_tax)
            total_city_tax = 0.0
            
            if has_city_tax:
                for tax in total_amounts['taxes']:
                    if tax['id'] == has_city_tax.id:
                        total_city_tax += tax['amount']
                total_vat -= total_city_tax
            
            return {
                'name': product_item.product_tmpl_id.name,
                'barCode': product_item.barcode or product_item.default_code or "",
                'barCodeType': 'GS1' if product_item.barcode and len(product_item.barcode) == 13 else 'UNDEFINED',
                'classificationCode': self._get_classification_code(product_item),
                'taxProductCode': (
                    product_item.product_tmpl_id.vat_code_id.name 
                    if hasattr(product_item.product_tmpl_id, 'vat_code_id') and product_item.product_tmpl_id.vat_code_id and tax_type != 'VAT_ABLE'
                    else ''
                ),
                'measureUnit': product_item.product_tmpl_id.uom_id.name or "ширхэг",
                'qty': round(invoice_qty or item.quantity, 2),
                'unitPrice': item.price_unit,
                'totalVAT': round(total_vat, 2),
                'totalCityTax': round(total_city_tax, 2),
                'totalAmount': round(total_amounts['total_included'], 2),
            }

        receipts_per_tax_type = {}
        
        if invoice_line_ids:
            for invoice_line in invoice_line_ids:
                line = self.env['account.move.line'].search([('id', '=', invoice_line['invoice_line_id'])])
                if line.tax_ids:
                    tax_type = getattr(line.tax_ids[0], 'ebarimt_tax_type', 'VAT_FREE')
                else:
                    tax_type = "VAT_FREE"

                if tax_type in receipts_per_tax_type.keys():
                    receipts_per_tax_type[tax_type].append(create_items(tax_type, line.id, invoice_line['quantity']))
                else:
                    receipts_per_tax_type[tax_type] = [create_items(tax_type, line.id, invoice_line['quantity'])]
        else:
            for line in self.invoice_line_ids:
                if line.tax_ids:
                    tax_type = getattr(line.tax_ids[0], 'ebarimt_tax_type', 'VAT_FREE')
                else:
                    tax_type = "VAT_FREE"

                if tax_type in receipts_per_tax_type.keys():
                    receipts_per_tax_type[tax_type].append(create_items(tax_type, line.id))
                else:
                    receipts_per_tax_type[tax_type] = [create_items(tax_type, line.id)]

        sub_receipts = []
        for type_tax, items in receipts_per_tax_type.items():
            def generate_receipts(item_list):
                total_amount = 0.0
                total_vat = 0.0
                total_city_tax = 0.0
                items = []
                for item in item_list:
                    total_amount += item['totalAmount']
                    total_vat += item['totalVAT']
                    total_city_tax += item['totalCityTax']
                    items.append(item)
                return {
                    'total_amount': total_amount,
                    'total_vat': total_vat,
                    'total_city_tax': total_city_tax,
                    'items': items,
                }

            receipt_values = generate_receipts(items)
            values = {
                'totalAmount': round(receipt_values['total_amount'], 2),
                'totalVAT': round(receipt_values['total_vat'], 2),
                'totalCityTax': round(receipt_values['total_city_tax'], 2),
                'taxType': type_tax,
                'merchantTin': str(company_tin or ''),
                'items': receipt_values['items'],
            }
            sub_receipts.append(values)

        today = datetime.datetime.now()
        total_tax = sum([item['totalVAT'] for item in sub_receipts])
        total_city_tax = sum([item['totalCityTax'] for item in sub_receipts])
        total_amount = sum([item['totalAmount'] for item in sub_receipts])
        
        invoice_vat_receipt = self.env['vat.receipt'].search([
            ('account_move_id', '=', self.id)
        ], order="create_date desc", limit=1)
        
        inactive_bill_id = ''
        if invoice_vat_receipt and invoice_vat_receipt.bill_state == 'refund':
            inactive_bill_id = invoice_vat_receipt.bill_id
        elif previous_inactive_id:
            inactive_bill_id = previous_inactive_id[0]

        sub_payments = []
        if self.amount_residual == 0:
            payment_line = {
                'code': 'BANK_TRANSFER',
                'status': 'PAID',
                'paidAmount': round(total_amount, 2),
            }
            sub_payments.append(payment_line)

        com_no = self.company_id.id

        # District code-г динамикаар авах
        district_code = self.get_district_code()

        json_body = {
            'totalAmount': round(total_amount, 2),
            'totalVat': round(total_tax, 2),
            'totalCityTax': round(total_city_tax, 2),
            'districtCode': district_code,
            'merchantTin': str(company_tin or ''),
            'branchNo': "{0:04d}".format(com_no),
            'posNo': "{0:04d}".format(com_no),
            'customerTin': str(self.partner_id.vat_tin or self.partner_id.vat or '') if "B2B" in type else '',
            'consumerNo': '',
            'type': type,
            'invoiceId': invoice_vat_receipt.bill_id if invoice_vat_receipt and invoice_vat_receipt.bill_state == 'invoice' else '',
            'inactiveId': inactive_bill_id,
            'reportMonth': (
                self.date.strftime("%Y-%m-%d") 
                if self.date.month < today.month or self.date.year < today.year 
                else None
            ),
            'receipts': sub_receipts,
            'payments': sub_payments,
        }

        return json_body

    def _ebarimt_check_invoice_access(self):
        if not self.env.su and not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(_("Only invoicing users can send or return eBarimt bills of invoices."))

    def vat_invoice_commit(self, bill_type="B2C_INVOICE"):
        self._ebarimt_check_invoice_access()
        merchant_no = str(self.company_id.partner_id.vat_tin or self.company_id.vat or '')
        
        if not merchant_no:
            raise ValidationError("Company TIN is not configured")
        
        if self.move_type == 'out_refund' and self.sale_order_count > 0:
            sol_invoice_ids = []
            inactive_vat_bill_id = []
            
            for line in self.line_ids:
                for sale_line in line.sale_line_ids:
                    if (sale_line.product_uom_qty > 0):
                        sol_invoice_ids.append({
                            'invoice_line_id': line.id,
                            'quantity': sale_line.product_uom_qty,
                        })
                    for invoice_line in sale_line.invoice_lines:
                        if invoice_line != line and invoice_line.move_id.vat_bill_state == 'refund':
                            inactive_vat_bill_id = [
                                v_receipt.bill_id 
                                for v_receipt in invoice_line.move_id.vat_receipts 
                                if v_receipt.refunded
                            ]

            request_body = self.generate_receipt_values(merchant_no, bill_type, sol_invoice_ids, inactive_vat_bill_id)
        else:
            request_body = self.generate_receipt_values(merchant_no, bill_type)

        posapi_services = self.env['account.ebarimt.posapi'].search([
            ('company_id', '=', self.company_id.id)
        ])
        
        if not posapi_services:
            raise ValidationError("eBarimt POS API service is not configured")
        
        posapi = posapi_services[0]
        _logger.debug("Request body: %s", json.dumps(self.env["account.ebarimt.posapi"]._mask_for_log(request_body)))
        
        res = posapi._request_receipt(request_body)

        if 'message' in res:
            raise ValidationError(res["message"])

        if 'result' in res:
            response = res["result"]
            if "INVOICE" in response["type"]:
                self.vat_invoice_sent = True
            else:
                self.vat_invoice_sent = True
                self.vat_sent = True

            newEbarimtBill = self.env['vat.receipt'].sudo()
            has_invoice_id = response.get('invoice_id')
            has_inactive_id = response.get('inactiveId')
            
            newEbarimtBill.create({
                "account_move_id": self.id,
                "company_id": self.company_id.id,
                "bill_id": response["id"],
                "amount": round(response["totalAmount"], 2),
                "vat": round(response["totalVAT"], 2),
                "city_tax": response.get("totalCityTax", 0),
                "bill_type": response["type"],
                "pos_id": response["posId"],
                "sent_at": response["date"],
                "merchant_tin": response["merchantTin"],
                "invoice_id": '' if not has_invoice_id else response["invoiceId"],
                "inactive_id": '' if not has_inactive_id else response["inactiveId"],
                "lottery": response.get("lottery") or "",
                "qr_data": response.get("qrData") or "",
                "bill_state": "invoice" if "INVOICE" in response["type"] else "done"
            })
            
            if has_inactive_id:
                inactive_bill = self.env['vat.receipt'].sudo().search([
                    ('bill_id', '=', response["inactiveId"])
                ])
                if inactive_bill:
                    inactive_bill.refunded = True
                    inactive_bill.bill_state = "refund"

    def action_vat_send(self):
        to_send_invoice = self.filtered(
            lambda invoice: invoice.state == "posted"
        )
        if to_send_invoice:
            action_data = self.env["ir.actions.act_window"]._for_xml_id(
                "ebarimt_api.action_account_ebarimt_confirmation"
            )
            # Odoo 17+ no longer injects active_model/active_ids into the
            # context of an action returned by a type="object" button.
            action_data["context"] = {
                "active_model": self._name,
                "active_id": to_send_invoice[:1].id,
                "active_ids": to_send_invoice.ids,
            }
            return action_data
        return False

    def return_ebarimt(self):
        """Return eBarimt button."""
        self._ebarimt_check_invoice_access()
        return self._ebarimt_return_bill()

    def _ebarimt_return_bill(self):
        invoice_vat_receipt = self.env['vat.receipt'].search([
            ('account_move_id', '=', self.id)
        ], order="create_date desc", limit=1)
        
        posapi_services = self.env['account.ebarimt.posapi'].search([
            ('company_id', '=', self.company_id.id)
        ])
        
        posapi = posapi_services[0] if posapi_services else False
        
        if posapi and invoice_vat_receipt:
            res = posapi._return_receipt({
                'id': invoice_vat_receipt.bill_id,
                'date': invoice_vat_receipt.sent_at.strftime("%Y-%m-%d %H:%M:%S"),
            })
        else:
            if not invoice_vat_receipt:
                message = "Invoice origin does not have eBarimt to return"
            else:
                message = "POS API is not connected"
            res = {
                "message": message
            }
        
        _logger.debug('Return receipt result: %s', res)

        if 'message' in res and invoice_vat_receipt:
            invoice_vat_receipt.sudo().bill_state = "old"

        if 'result' in res and invoice_vat_receipt:
            response = res["result"]
            if response.get("status") == "SUCCESS":
                invoice_vat_receipt.sudo().write({"refunded": True, "bill_state": "refund"})
                
        return res

    @api.model
    def refresh_district_code_cache(self):
        """Cron job-оор cache-г шинэчлэх"""
        try:
            self.get_district_code_from_api()
            _logger.info("District code cache refreshed successfully")
        except Exception as e:
            _logger.error(f"Failed to refresh district code cache: {e}")

    def action_refresh_district_code(self):
        """Manual refresh товчлуур"""
        try:
            district_code = self.get_district_code_from_api()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('District code refreshed: %s') % district_code,
                    'type': 'success'
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Failed to refresh district code: %s') % str(e),
                    'type': 'danger'
                }
            }