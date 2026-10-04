import datetime
import json
import requests
from functools import partial
from decimal import Decimal, ROUND_HALF_UP
from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

EBARIMT_MAX_ATTEMPTS = 20
EBARIMT_SENDING_STALE_MINUTES = 15



class EbarimtDataError(ValidationError):
    """The order itself cannot be turned into a bill (missing VAT code, no
    customer TIN, ...). Sending again will not help until someone fixes the
    data, so such orders are parked for a person instead of retried."""


bill_types = {
    "1": "B2C_RECEIPT",
    "3": "B2B_RECEIPT"
}

class PosOrder(models.Model):
    _inherit = "pos.order"

    # ШИНЭ: eBarimt тохиргооны талбарууд нэмэх
    ebarimt_receipt_type = fields.Char('eBarimt Receipt Type', help="individual or organization")
    ebarimt_bill_type = fields.Char('eBarimt Bill Type', help="B2C_RECEIPT or B2B_RECEIPT")
    ebarimt_customer_tin = fields.Char('eBarimt Customer TIN', help="Final customer TIN used for eBarimt")
    ebarimt_manual_customer_tin = fields.Char('eBarimt Manual Customer TIN', help="Manually entered customer TIN")
    ebarimt_config_json = fields.Text('eBarimt Config JSON', help="Full eBarimt configuration from POS")

    # copy=False: a refund made from the backend copies the original order,
    # and must not look as if its own bill was already sent.
    vat_sent = fields.Boolean('eBarimt Sent?', default=False, copy=False)
    vat_receipts = fields.One2many("vat.receipt", "pos_order_id", "eBarimt Bills")
    vat_bill_state = fields.Selection([
        ('done', 'Bill Sent'),
        ('old', 'Needs to be Refunded'),
        ('refund', 'Refunded'),
        ('invoice', 'Invoice')
    ], "VAT Bill State", compute="_compute_vat_bill_state", store=True)

    # Sending status (set when the order is paid; empty on orders from before
    # this was added, which are never retried automatically).
    ebarimt_state = fields.Selection([
        ('pending', 'Waiting to send'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('failed', 'Failed, will retry'),
        ('manual', 'Needs attention'),
    ], "eBarimt Status", copy=False, index=True, readonly=True)
    ebarimt_error = fields.Text("eBarimt Error", copy=False, readonly=True)
    ebarimt_attempts = fields.Integer("eBarimt Attempts", copy=False, readonly=True)
    ebarimt_next_try = fields.Datetime("eBarimt Next Try", copy=False, readonly=True)
    ebarimt_return_done = fields.Boolean("eBarimt Return Done", copy=False, readonly=True,
                                         help="The original order's bill was already returned or replaced")

    def get_district_code_from_api(self):
        """eBarimt API-аас district code татаж авах"""
        try:
            url = "https://st-api.ebarimt.mn/api/info/check/getBranchInfo"
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
        """Компанийн дүүргийн кодыг олж авах - POS config эхэнд"""
        
        # 1. POS config дээрх branch_code_id-аас авах (шинэ логик)
        if (self.session_id and 
            self.session_id.config_id and 
            self.session_id.config_id.branch_code_id and
            self.session_id.config_id.branch_code_id.combined_code):
            
            district_code = self.session_id.config_id.branch_code_id.combined_code
            _logger.info(f"Using district code from POS config: {district_code}")
            return district_code
        
        # 2. Fallback: Default district code
        _logger.info("No POS config branch found, using default district code")
        return self.get_default_district_code()

    # State 'paid' болох үед ebarimt илгээх. 19.0: sync_from_ui ->
    # _process_order -> _process_saved_order -> action_pos_order_paid()
    # writes {'state': 'paid'} after lines and payments are saved.
    #
    # The bill is NOT sent from inside that transaction any more: if the
    # transaction rolled back (or Odoo retried it after a serialization
    # failure) PosAPI had already issued a bill, and the retry issued a
    # second one. Instead the order is queued here and sent right after the
    # commit (still before the POS gets its answer, so the receipt shows the
    # lottery and QR as before). Failures are kept on the order and retried
    # by the "eBarimt: send pending bills" cron.

    def write(self, vals):
        res = super(PosOrder, self).write(vals)
        if vals.get('state') == 'paid':
            to_queue = self.filtered(lambda o: o._ebarimt_should_queue())
            if to_queue:
                super(PosOrder, to_queue).write({
                    'ebarimt_state': 'pending',
                    'ebarimt_error': False,
                    'ebarimt_attempts': 0,
                    'ebarimt_next_try': fields.Datetime.now(),
                })
                self.env.cr.postcommit.add(
                    partial(self._ebarimt_send_after_commit, self.env.uid, dict(self.env.context), self.env.su, to_queue.ids)
                )
        return res

    def _ebarimt_should_queue(self):
        self.ensure_one()
        config = self.session_id.config_id
        send_ebarimt = config.send_ebarimt if 'send_ebarimt' in config._fields else True
        if not send_ebarimt or self.vat_sent:
            return False
        # Something to report: items sold, or items taken back from an
        # earlier order (an even exchange can total zero).
        if not self._ebarimt_sold_lines() and not self._ebarimt_returns_lines():
            return False
        # Already queued, in flight, done or parked for a person.
        return self.ebarimt_state not in ('pending', 'sending', 'sent', 'manual')

    @api.model
    def _ebarimt_send_after_commit(self, uid, context, su, order_ids):
        """Runs after the POS transaction committed, in a cursor of its own.
        Never raises: the order is saved whatever happens here."""
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, uid, context, su=su)
                env['pos.order']._ebarimt_process(order_ids)
        except Exception:
            _logger.exception("eBarimt: sending after commit failed for orders %s; the cron will retry", order_ids)

    @api.model
    def _ebarimt_process(self, order_ids):
        """Claim, send and record each order, committing after each one.
        Returns the number of orders that failed."""
        failed = 0
        for order_id in order_ids:
            # Claim the order: only one process may send it.
            self.env.cr.execute(
                """UPDATE pos_order
                      SET ebarimt_state = 'sending', write_date = (now() at time zone 'UTC')
                    WHERE id = %s AND ebarimt_state IN ('pending', 'failed')
                RETURNING id""",
                (order_id,),
            )
            if not self.env.cr.fetchone():
                self.env.cr.rollback()
                continue
            self.env.cr.commit()
            self.env.invalidate_all()
            order = self.browse(order_id)
            try:
                state, note = order._ebarimt_send_one()
            except EbarimtDataError as e:
                self.env.cr.rollback()
                self.env.invalidate_all()
                _logger.warning("eBarimt: %s cannot be sent until its data is fixed: %s", order.name, e)
                super(PosOrder, order).write({'ebarimt_state': 'manual', 'ebarimt_error': str(e)})
                self.env.cr.commit()
                failed += 1
                continue
            except Exception as e:
                self.env.cr.rollback()
                self.env.invalidate_all()
                _logger.warning("eBarimt: sending %s failed: %s", order.name, e)
                order._ebarimt_set_state('failed', str(e))
                self.env.cr.commit()
                failed += 1
                continue
            try:
                order._ebarimt_set_state(state, note)
                self.env.cr.commit()
            except Exception:
                # PosAPI answered but the result could not be saved: the bill
                # may exist, so never retry this one automatically.
                self.env.cr.rollback()
                self.env.invalidate_all()
                _logger.exception("eBarimt: could not save the result for %s", order.name)
                super(PosOrder, order).write({
                    'ebarimt_state': 'manual',
                    'ebarimt_error': _("PosAPI answered but the result could not be saved; check eBarimt before resending."),
                })
                self.env.cr.commit()
            if state == 'failed':
                failed += 1
        return failed

    def _ebarimt_send_one(self):
        """Send one claimed order. Returns (state, note); raises on a PosAPI error.

        An order can take items back (refund), sell items, or both (an
        exchange). Taking back is done on the original order's bill first:
        the bill is cancelled when nothing of that order is left, otherwise
        it is replaced by a bill for the items the customer kept. Then the
        items sold on this order get their own bill.
        """
        self.ensure_one()
        if self._ebarimt_returns_lines() and not self.ebarimt_return_done:
            original = self.find_original_order_for_refund(self)
            if not original:
                return 'manual', _("Refund is not linked to exactly one original order; return its eBarimt bill by hand.")
            if original.ebarimt_state in ('pending', 'sending', 'failed'):
                return 'failed', _("Original order %s has no eBarimt bill yet; waiting for it.", original.name)
            if not original.vat_sent:
                if not self._ebarimt_sold_lines():
                    return 'manual', _("Original order %s has no eBarimt bill; nothing was returned.", original.name)
            else:
                original._ebarimt_take_back()
            # Never redo the return when the sale part below fails and is retried.
            super(PosOrder, self).write({'ebarimt_return_done': True})
            self.env.cr.commit()

        if self._ebarimt_sold_lines() and not (self.vat_sent or self.vat_receipts.filtered(lambda r: r.bill_state == 'done')):
            self.vat_pos_order_commit(self.get_ebarimt_bill_type())
        return 'sent', False

    def _ebarimt_take_back(self):
        """After a refund of (part of) this order: cancel its bill when
        nothing is left, else replace it with a bill for what is left
        (PosAPI voids the bill named in inactiveId and issues the new one)."""
        self.ensure_one()
        current = self.env['vat.receipt'].sudo().search([
            ('pos_order_id', '=', self.id), ('bill_id', '!=', False),
        ], order="create_date desc", limit=1)
        if not current or current.bill_state == 'refund':
            _logger.info("eBarimt bill of %s is already returned", self.name)
            return True
        if self._ebarimt_sold_lines():
            _logger.info("Partial return of %s: replacing bill %s", self.name, current.bill_id)
            self.vat_pos_order_commit(self.get_ebarimt_bill_type())
            return True
        res = self.return_ebarimt()
        if not (res and res.get('success')):
            raise UserError(_("eBarimt return of %(order)s failed: %(error)s",
                              order=self.name, error=(res or {}).get('message') or _("no response")))
        return True

    def _ebarimt_set_state(self, state, note=False):
        self.ensure_one()
        vals = {'ebarimt_state': state, 'ebarimt_error': note or False}
        if state == 'failed':
            attempts = self.ebarimt_attempts + 1
            vals['ebarimt_attempts'] = attempts
            if attempts >= EBARIMT_MAX_ATTEMPTS:
                vals['ebarimt_state'] = 'manual'
                vals['ebarimt_error'] = _("Gave up after %(n)s attempts. Last error: %(error)s",
                                          n=attempts, error=note or '')
            else:
                delay = min(5 * 2 ** (attempts - 1), 120)
                vals['ebarimt_next_try'] = fields.Datetime.now() + datetime.timedelta(minutes=delay)
        super(PosOrder, self).write(vals)

    @api.model
    def _cron_send_pending_ebarimt(self, limit=50):
        """Retry bills that failed or were never sent, and flag sends that
        were cut off (e.g. Odoo restarted mid-request): PosAPI may or may not
        have issued those bills, so a person has to check before resending."""
        stale = fields.Datetime.now() - datetime.timedelta(minutes=EBARIMT_SENDING_STALE_MINUTES)
        stuck = self.search([('ebarimt_state', '=', 'sending'), ('write_date', '<', stale)])
        if stuck:
            _logger.warning("eBarimt: orders %s were interrupted while sending", stuck.mapped('name'))
            super(PosOrder, stuck).write({
                'ebarimt_state': 'manual',
                'ebarimt_error': _("Interrupted while sending; check eBarimt before resending."),
            })
            self.env.cr.commit()

        due = self.search([
            ('ebarimt_state', 'in', ('pending', 'failed')),
            '|', ('ebarimt_next_try', '=', False), ('ebarimt_next_try', '<=', fields.Datetime.now()),
        ], order='id', limit=limit)
        failed_in_a_row = 0
        for order_id in due.ids:
            if self._ebarimt_process([order_id]):
                failed_in_a_row += 1
                if failed_in_a_row >= 3:
                    _logger.warning("eBarimt: 3 failures in a row, stopping this run")
                    break
            else:
                failed_in_a_row = 0

    def _ebarimt_send_manual(self, bill_type):
        """Resend from the confirmation wizard (one order). Locks the order so
        the cron cannot send it at the same time."""
        self.ensure_one()
        if not self._ebarimt_sold_lines():
            raise UserError(_("%s is a refund; use Return eBarimt on the original order.", self.name))
        self.env.cr.execute("SELECT id FROM pos_order WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset(['ebarimt_state', 'vat_sent'])
        if self.ebarimt_state == 'sending':
            raise UserError(_("%s is being sent to eBarimt right now; wait a minute and reload.", self.name))
        if self.vat_sent or self.vat_receipts.filtered('bill_id'):
            raise UserError(_("%s already has an eBarimt bill.", self.name))
        self.vat_pos_order_commit(bill_type)
        super(PosOrder, self).write({'ebarimt_state': 'sent', 'ebarimt_error': False})
        return True

    def find_original_order_for_refund(self, refund_order):
        """The order a refund belongs to, from the link the POS keeps
        (refund lines -> refunded_orderline_id -> its order).

        Never guess: a refund without that link used to void the latest sale
        on the same POS, i.e. some other customer's bill. Without a link it
        returns None and the bill has to be returned by hand.
        """
        originals = refund_order.refunded_order_id or refund_order.lines.refunded_orderline_id.order_id
        if len(originals) == 1:
            _logger.info("Refund %s linked to original order %s", refund_order.name, originals.name)
            return originals
        if len(originals) > 1:
            _logger.warning(
                "Refund %s covers several orders (%s); return their eBarimt bills by hand",
                refund_order.name, ", ".join(originals.mapped("name")),
            )
        else:
            _logger.warning(
                "Refund %s is not linked to an original order; return its eBarimt bill by hand",
                refund_order.name,
            )
        return None

    @api.depends('vat_receipts', 'vat_receipts.bill_state')
    def _compute_vat_bill_state(self):
        for rec in self:
            order_vat_receipt = self.env['vat.receipt'].search([
                ('pos_order_id', '=', rec.id)
            ], order="create_date desc", limit=1)
            if order_vat_receipt:
                rec.vat_bill_state = order_vat_receipt.bill_state
            else:
                rec.vat_bill_state = False

    def get_ebarimt_bill_type(self):
        """eBarimt bill type тодорхойлох - FRONTEND-ЭЭС ИРСЭН МЭДЭЭЛЭЛ ЭХЭНД"""
        try:
            # 1. Frontend-ээс ирсэн bill type шууд ашиглах
            if self.ebarimt_bill_type:
                _logger.info(f"📋 Using stored bill type: {self.ebarimt_bill_type}")
                return self.ebarimt_bill_type
            
            # 2. eBarimt config JSON-аас авах
            if self.ebarimt_config_json:
                try:
                    config = json.loads(self.ebarimt_config_json)
                    if config.get('billType'):
                        _logger.info(f"📋 Using bill type from config: {config['billType']}")
                        return config['billType']
                except:
                    pass
            
            # 3. Receipt type-аас тодорхойлох
            if self.ebarimt_receipt_type == 'organization':
                _logger.info(f"📋 Organization receipt type -> B2B_RECEIPT")
                return 'B2B_RECEIPT'
            elif self.ebarimt_receipt_type == 'individual':
                _logger.info(f"📋 Individual receipt type -> B2C_RECEIPT")
                return 'B2C_RECEIPT'
            
            # 4. Fallback: Customer TIN байгаа эсэхээр шийдэх
            customer_tin = self.get_ebarimt_customer_tin()
            if customer_tin:
                _logger.debug(f"📋 Customer TIN found -> B2B_RECEIPT")
                return 'B2B_RECEIPT'
            else:
                _logger.debug(f"📋 No customer TIN -> B2C_RECEIPT")
                return 'B2C_RECEIPT'
                
        except Exception as e:
            _logger.error(f"❌ Error determining bill type: {e}")
            return 'B2C_RECEIPT'  # Default

    def get_ebarimt_customer_tin(self):
        """eBarimt customer TIN авах - FRONTEND-ЭЭС ИРСЭН МЭДЭЭЛЭЛ ЭХЭНД"""
        try:
            _logger.debug(f"🔍 Getting customer TIN for order {self.name}")
            
            # 1. Frontend-ээс ирсэн customer TIN шууд ашиглах
            if self.ebarimt_customer_tin:
                _logger.debug(f"📋 Using stored customer TIN: {self.ebarimt_customer_tin}")
                return self.ebarimt_customer_tin
            
            # 2. eBarimt config JSON-аас авах
            if self.ebarimt_config_json:
                try:
                    config = json.loads(self.ebarimt_config_json)
                    if config.get('customerTin'):
                        _logger.debug(f"📋 Using customer TIN from config: {config['customerTin']}")
                        return config['customerTin']
                except Exception as e:
                    _logger.warning(f"⚠️ Error parsing config JSON: {e}")
            
            # 3. Manual customer TIN шалгах
            if self.ebarimt_manual_customer_tin:
                _logger.debug(f"✍️ Using manual customer TIN: {self.ebarimt_manual_customer_tin}")
                return self.ebarimt_manual_customer_tin
            
            # 4. Receipt type байгууллага бол manualCustomerTin эсвэл partner-аас авах
            if self.ebarimt_receipt_type == 'organization':
                # Эхлээд manualCustomerTin шалгах
                if self.ebarimt_manual_customer_tin:
                    _logger.debug(f"✍️ Using manual customer TIN for organization: {self.ebarimt_manual_customer_tin}")
                    return self.ebarimt_manual_customer_tin
                
                # Дараа нь partner_id.vat_tin шалгах
                if self.partner_id and hasattr(self.partner_id, 'vat_tin'):
                    partner_tin = self.partner_id.vat_tin or ''
                    if partner_tin:
                        _logger.debug(f"👥 Using partner TIN for organization: {partner_tin}")
                        return partner_tin
                
                # Хэрвээ хоёулаа байхгүй бол алдаа өгчих
                _logger.error("❌ Organization receipt requires a customer TIN, but none provided")
                raise EbarimtDataError("Байгууллагын баримтанд ТТД заавал оруулна уу.")
            
            # 5. Individual receipt бол ТТД хоосон
            if self.ebarimt_receipt_type == 'individual':
                _logger.debug(f"👤 Individual receipt -> empty customer TIN")
                return ''
            
            # 6. Fallback: Хуучин логик ашиглах
            _logger.info(f"🔄 Fallback to legacy logic")
            if self.partner_id and hasattr(self.partner_id, 'vat_tin'):
                legacy_tin = self.partner_id.vat_tin or ''
                _logger.debug(f"🔄 Legacy partner TIN: {legacy_tin}")
                return legacy_tin
            
            _logger.debug(f"🔄 No customer TIN found")
            return ''
            
        except Exception as e:
            _logger.error(f"❌ Error getting customer TIN: {e}")
            return ''

    def _get_classification_code(self, product_item):
        """Бүтээгдэхүүний classification code авах"""
        try:
            # 1. БҮНА classification ашиглах
            if (hasattr(product_item.product_tmpl_id, 'buna_classification_id') 
                and product_item.product_tmpl_id.buna_classification_id):
                
                buna_classification = product_item.product_tmpl_id.buna_classification_id
                
                # Хамгийн тохирох параметрыг сонгож хойноос 0-ээр дүүргэх
                classification_code = ""
                
                if buna_classification.p6:
                    classification_code = str(buna_classification.p6)
                elif buna_classification.p5:  
                    classification_code = str(buna_classification.p5)
                elif buna_classification.p4:
                    classification_code = str(buna_classification.p4)
                elif buna_classification.p3:
                    classification_code = str(buna_classification.p3)
                elif buna_classification.code:
                    classification_code = str(buna_classification.code)
                
                # 7 орон болгохын тулд хойноос 0-ээр дүүргэх
                if classification_code:
                    return classification_code.ljust(7, '0')
                
            # 2. Хуучин classification ашиглах
            if (hasattr(product_item.product_tmpl_id, 'vat_classification_id') 
                and product_item.product_tmpl_id.vat_classification_id):
                return str(product_item.product_tmpl_id.vat_classification_id.name).ljust(7, '0')
            
            # 3. Default
            return "8640500"
            
        except Exception as e:
            _logger.warning(f"Classification code авахад алдаа: {e}")
            return "8640500"

    def round_decimal(self, value, places=2):
        """Decimal ашиглан зөв бөөрөөцөө хийх - НӨАТ АЛДАА ЗАСВАРЛАХ"""
        try:
            decimal_value = Decimal(str(value))
            return float(decimal_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        except:
            return round(float(value), places)

    def get_city_tax_rate(self, tax_line):
        """City tax rate-ийг зөв тодорхойлох - ЗАСВАРЛАСАН ХЭСЭГ"""
        try:
            # 1. Tax дээрх city_tax field шалгах
            if hasattr(tax_line, 'city_tax') and tax_line.city_tax:
                # City tax rate-ийг tax amount-аас авах
                if hasattr(tax_line, 'amount'):
                    return tax_line.amount / 100.0  # 2% -> 0.02
                elif hasattr(tax_line, 'city_tax_rate'):
                    return tax_line.city_tax_rate / 100.0
                else:
                    # Монголын стандарт city tax rate
                    return 0.02  # 2%
            
            return 0.0
            
        except Exception as e:
            _logger.error(f"❌ Error getting city tax rate: {e}")
            return 0.02  # Default 2%

    def _ebarimt_line_taxes(self, line):
        """Taxes Odoo applies to the line (after fiscal position)."""
        if 'tax_ids_after_fiscal_position' in line._fields:
            return line.tax_ids_after_fiscal_position
        return line.tax_ids

    @api.model
    def _ebarimt_tax_type(self, taxes):
        """eBarimt tax type of a line, from its VAT tax (city tax ignored).
        No VAT tax at all means VAT_FREE."""
        vat_taxes = taxes.filtered(lambda t: not getattr(t, 'city_tax', False))
        if not vat_taxes:
            return 'VAT_FREE'
        return getattr(vat_taxes[0], 'ebarimt_tax_type', False) or 'VAT_ABLE'

    def _ebarimt_line_values(self, line, qty):
        """One receipt item for `qty` units of `line`.

        Amounts come from Odoo's own tax computation (the same one that
        produced the order totals), so VAT and city tax follow the rates
        configured on the taxes instead of an assumed 10% / 2%.
        """
        taxes = self._ebarimt_line_taxes(line)
        tax_type = self._ebarimt_tax_type(taxes)
        price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
        res = taxes.compute_all(
            price, line.order_id.currency_id, qty,
            product=line.product_id, partner=line.order_id.partner_id,
        )
        total = Decimal(str(res['total_included']))
        vat = Decimal('0')
        city = Decimal('0')
        for tax_res in res['taxes']:
            tax = self.env['account.tax'].browse(tax_res['id'])
            amount = Decimal(str(tax_res['amount']))
            if getattr(tax, 'city_tax', False):
                city += amount
            elif tax_type == 'VAT_ABLE':
                vat += amount
        tmpl = line.product_id.product_tmpl_id
        tax_product_code = ''
        if tax_type != 'VAT_ABLE' and 'vat_code_id' in tmpl._fields and tmpl.vat_code_id:
            tax_product_code = tmpl.vat_code_id.name or ''
        return {
            'tax_type': tax_type,
            'has_tax': bool(taxes),
            'name': tmpl.name,
            'barCode': line.product_id.barcode or line.product_id.default_code or "",
            'barCodeType': 'GS1' if (line.product_id.barcode and len(line.product_id.barcode) == 13) else 'UNDEFINED',
            'classificationCode': self._get_classification_code(line.product_id),
            'taxProductCode': tax_product_code,
            'measureUnit': tmpl.uom_id.name or "ширхэг",
            'qty': Decimal(str(qty)),
            'total': total,
            'vat': vat,
            'city': city,
        }

    def _ebarimt_sold_lines(self):
        """(line, qty) still sold on this order: positive quantities minus
        what later refunds took back. Returned lines of an exchange (negative
        quantities) are not part of the sale."""
        result = []
        for line in self.lines:
            qty = line.qty - (getattr(line, 'refunded_qty', 0) or 0)
            if qty <= 0:
                continue
            if line.order_id.currency_id.is_zero(line.price_subtotal_incl):
                continue
            result.append((line, qty))
        return result

    def _ebarimt_returns_lines(self):
        """True when this order takes back items of an earlier order."""
        return any(line.refunded_orderline_id and line.qty < 0 for line in self.lines)

    def generate_receipt_values(self, company_tin, parent_merchant_tin, ebarimt_pos_number, type):
        def q2(x):
            return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        items = [self._ebarimt_line_values(line, qty) for line, qty in self._ebarimt_sold_lines()]

        # Discount and reward lines (negative amounts) are spread over the
        # sold items in proportion to their amounts: PosAPI does not accept
        # negative items, and the receipt total must equal what was paid.
        positives = [it for it in items if it['total'] > 0]
        negatives = [it for it in items if it['total'] < 0]
        if negatives:
            discount = -sum(it['total'] for it in negatives)
            base = sum(it['total'] for it in positives)
            if discount >= base:
                raise EbarimtDataError(_("Order %s: the discounts are larger than the items they apply to; "
                                  "eBarimt cannot be issued for it.", self.name))
            factor = (base - discount) / base
            for it in positives:
                for key in ('total', 'vat', 'city'):
                    it[key] = it[key] * factor
            items = positives

        no_tax = [it['name'] for it in items if not it['has_tax'] and not it['taxProductCode']]
        if no_tax:
            raise EbarimtDataError(_("These products have no sales tax. Add VAT 10%%, or, if they are "
                                     "VAT free, an eBarimt VAT code (product form, eBarimt tab): %s",
                                     ", ".join(no_tax)))
        missing_code = [it['name'] for it in items if it['tax_type'] != 'VAT_ABLE' and not it['taxProductCode']]
        if missing_code:
            raise EbarimtDataError(_("These products are VAT free or VAT 0%% but have no eBarimt VAT code "
                                     "(product form, eBarimt tab): %s", ", ".join(missing_code)))

        sub_receipts = []
        receipts_per_tax_type = {}
        for it in items:
            receipts_per_tax_type.setdefault(it['tax_type'], []).append(it)
        for type_tax, group in receipts_per_tax_type.items():
            processed_items = []
            for it in group:
                total = q2(it['total'])
                processed_items.append({
                    'name': it['name'],
                    'barCode': it['barCode'],
                    'barCodeType': it['barCodeType'],
                    'classificationCode': it['classificationCode'],
                    'taxProductCode': it['taxProductCode'],
                    'measureUnit': it['measureUnit'],
                    'qty': float(q2(it['qty'])),
                    # unitPrice is tax included and after discounts, so that
                    # qty x unitPrice = totalAmount.
                    'unitPrice': float(q2(it['total'] / it['qty'])),
                    'totalVAT': float(q2(it['vat'])),
                    'totalCityTax': float(q2(it['city'])),
                    'totalAmount': float(total),
                })
            sub_receipts.append({
                'totalAmount': float(sum(q2(it['total']) for it in group)),
                'totalVAT': float(sum(q2(it['vat']) for it in group)),
                'totalCityTax': float(sum(q2(it['city']) for it in group)),
                'taxType': type_tax,
                'merchantTin': company_tin,
                'items': processed_items,
            })

        today = datetime.datetime.now()
        total_amount_all = sum(Decimal(str(r['totalAmount'])) for r in sub_receipts)
        total_vat_all = sum(Decimal(str(r['totalVAT'])) for r in sub_receipts)
        total_city_all = sum(Decimal(str(r['totalCityTax'])) for r in sub_receipts)

        # The bill this one replaces (after a partial return), if any.
        order_vat_receipt = self.env['vat.receipt'].sudo().search([
            ('pos_order_id', '=', self.id),
            ('bill_state', '=', 'done'),
        ], order="create_date desc", limit=1)

        # One entry per payment method, netted: the POS stores the change
        # given back as a separate negative payment (is_change) on the cash
        # method, e.g. 20000 paid + (-5000) change -> 15000 cash.
        paid_per_method = {}
        for payment in self.payment_ids:
            method = payment.payment_method_id
            paid_per_method[method] = paid_per_method.get(method, Decimal('0')) + Decimal(str(payment.amount))
        paid = [(method, amount) for method, amount in paid_per_method.items() if amount > 0]
        # Payments must add up to the receipt total. They differ after cash
        # rounding, after a partial return (the original payments stay on the
        # order) and on an exchange: scale them to the total.
        paid_total = sum(amount for _method, amount in paid)
        sub_payments = []
        if paid_total > 0:
            remaining = total_amount_all
            for i, (method, amount) in enumerate(paid):
                share = remaining if i == len(paid) - 1 else q2(amount * total_amount_all / paid_total)
                remaining -= share
                if share <= 0:
                    continue
                code = method._get_ebarimt_payment_code() if method else 'CASH'
                sub_payments.append({
                    'code': code,
                    'status': 'PAID',
                    'paidAmount': float(q2(share)),
                    'easy': code in ['CASH', 'PAYMENT_CARD'],
                })
        if not sub_payments:
            sub_payments = [{
                'code': 'CASH',
                'status': 'PAID',
                'paidAmount': float(q2(total_amount_all)),
                'easy': True,
            }]

        config = self.session_id.config_id
        default_no = "{0:04d}".format(config.id)
        branch_no = (getattr(config, 'ebarimt_branch_no', False) or '').strip() or default_no
        pos_no = (ebarimt_pos_number or '').strip()
        if pos_no.isdigit():
            pos_no = "{0:04d}".format(int(pos_no))
        pos_no = pos_no or default_no
        district_code = self.get_district_code()
        customer_tin = self.get_ebarimt_customer_tin()
        # consumerNo is the buyer's 8-digit eBarimt consumer number. Odoo
        # returns False for an empty vat, which PosAPI rejects (it expects a
        # string), and a registry number is not a consumer number.
        partner_vat = (self.partner_id.vat or '').strip()
        consumer_no = partner_vat if partner_vat.isdigit() and len(partner_vat) == 8 else ''

        json_body = {
            'totalAmount': float(q2(total_amount_all)),
            'totalVAT': float(q2(total_vat_all)),
            'totalCityTax': float(q2(total_city_all)),
            'districtCode': district_code,
            'merchantTin': parent_merchant_tin or company_tin,
            'branchNo': branch_no,
            'posNo': pos_no,
            'customerTin': customer_tin,
            'consumerNo': consumer_no,
            'type': type,
            'inactiveId': order_vat_receipt.bill_id or '',
            'reportMonth': (
                self.date_order.strftime("%Y-%m-%d")
                if self.date_order.month < today.month or self.date_order.year < today.year
                else None
            ),
            'receipts': sub_receipts,
            'payments': sub_payments,
        }

        return json_body



    def vat_pos_order_commit(self, bill_type="B2C_INVOICE"):
        """POS захиалгын eBarimt илгээх - буцаалтын захиалгыг блоклох"""
        
        # Nothing sold on this order (a plain refund): no receipt to POST.
        if not self._ebarimt_sold_lines():
            _logger.info("No sold items on %s; no eBarimt receipt to send", self.name)
            return False
        
        try:
            # 1. Company TIN шалгах
            parent_merchant_tin = ''
            ebarimt_pos_number = ''
            if hasattr(self.company_id, 'parent_merchant_tin') and hasattr(self.company_id, 'ebarimt_pos_number'):
                parent_merchant_tin = self.company_id.parent_merchant_tin or ''
                ebarimt_pos_number = self.company_id.ebarimt_pos_number or ''
            else:
                raise ValidationError("Company partner does not have 'parent_merchant_tin' field or 'ebarimt_pos_number'.")
            merchant_no = ''
            if hasattr(self.company_id.partner_id, 'vat_tin'):
                merchant_no = self.company_id.partner_id.vat_tin or ''
            
            if not merchant_no:
                merchant_no = self.company_id.vat or ''
                
            if not merchant_no:
                raise ValidationError("Company TIN is not configured. Please set TIN in Company settings.")
            
            _logger.debug(f"🔵 Starting eBarimt send for order {self.name} with TIN: {merchant_no}")
            
            # eBarimt тохиргоо debug
            _logger.info(f"📋 eBarimt Debug Info:")
            _logger.info(f"   - Order: {self.name}")
            _logger.info(f"   - Receipt Type: {self.ebarimt_receipt_type}")
            _logger.info(f"   - Bill Type: {bill_type}")
            _logger.debug(f"   - Stored Customer TIN: '{self.ebarimt_customer_tin}'")
            _logger.debug(f"   - Manual Customer TIN: '{self.ebarimt_manual_customer_tin}'")
            _logger.debug(f"   - Config JSON: {self.ebarimt_config_json}")
            
            # 2. Request body бэлдэх
            request_body = self.generate_receipt_values(merchant_no, parent_merchant_tin, ebarimt_pos_number, bill_type)
            
            # 3. POS API service олох
            posapi_services = self.env['account.ebarimt.posapi'].search([
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            
            if not posapi_services:
                raise ValidationError(
                    "eBarimt POS API service is not configured. "
                    "Please configure it in Settings > Technical > eBarimt PosAPI"
                )
            
            posapi = posapi_services[0]
            
            # 4. Request илгээх
            _logger.info(f"📤 Sending eBarimt request for {self.name}")
            
            res = posapi.request_receipt(request_body)
            
            # 5. Response боловсруулах
            _logger.debug(f"📥 Received response: {res}")
            
            # Error check
            if not res.get('success'):
                error_msg = res.get('message', 'Unknown error from POS API')
                _logger.error(f"❌ eBarimt error for {self.name}: {error_msg}")
                raise ValidationError(f"eBarimt Error: {error_msg}")

            if 'result' not in res:
                raise ValidationError("Invalid response from POS API - missing result data")

            # 6. Response data process
            response = res["result"]
            
            _logger.info(f"✅ eBarimt SUCCESS for {self.name}:")
            _logger.debug(f"   - Bill ID: {response.get('id')}")
            _logger.debug(f"   - Type: {response.get('type')}")
            _logger.debug(f"   - Amount: {response.get('totalAmount')}")
            _logger.debug(f"   - VAT: {response.get('totalVAT')}")
            _logger.debug(f"   - City Tax: {response.get('totalCityTax', 0)}")
            _logger.debug(f"   - Date: {response.get('date')}")
            _logger.debug(f"   - POS ID: {response.get('posId')}")
            
            # QR болон Lottery мэдээлэл
            if response.get('qrData'):
                _logger.debug(f"   - QR Data: {response.get('qrData')}")
            if response.get('lottery'):
                _logger.debug(f"   - Lottery: {response.get('lottery')}")
            
            # 7. VAT sent тэмдэглэх
            self.vat_sent = True
            
            # 8. VAT Receipt үүсгэх
            newEbarimtBill = self.env['vat.receipt'].sudo()
            # The bill this receipt replaced (partial return), as sent or as echoed back.
            has_inactive_id = response.get('inactiveId') or request_body.get('inactiveId')
            
            # API-аас ирсэн lottery авах
            api_lottery = response.get('lottery', '')
            
            receipt_vals = {
                "pos_order_id": self.id,
                "company_id": self.company_id.id,
                "bill_id": response.get("id", ""),
                "amount": self.round_decimal(float(response.get("totalAmount", 0)), 2),
                "vat": self.round_decimal(float(response.get("totalVAT", 0)), 2),
                "city_tax": self.round_decimal(float(response.get("totalCityTax", 0)), 2),
                "bill_type": response.get("type", bill_type),
                "pos_id": str(response.get("posId", "")),
                "sent_at": response.get("date", fields.Datetime.now()),
                "merchant_tin": response.get("merchantTin", merchant_no),
                "customer_tin": response.get("customerTin", ""),
                "bill_state": "done",
                "lottery": api_lottery or "",
                "qr_data": response.get("qrData") or "",
            }
            
            # Lottery-г inactive_id талбарт хадгалах
            if api_lottery:
                if has_inactive_id:
                    receipt_vals["inactive_id"] = f"{has_inactive_id}|LOTTERY:{api_lottery}"
                else:
                    receipt_vals["inactive_id"] = f"LOTTERY:{api_lottery}"
                
                _logger.debug(f"💾 Storing lottery in inactive_id: {api_lottery}")
            else:
                receipt_vals["inactive_id"] = has_inactive_id or ""
            
            created_receipt = newEbarimtBill.create(receipt_vals)
            _logger.info(f"💾 VAT Receipt created: ID={created_receipt.id}, Bill={created_receipt.bill_id}")
            
            # 9. Inactive bill update
            if has_inactive_id:
                inactive_bill = self.env['vat.receipt'].sudo().search([
                    ('bill_id', '=', has_inactive_id)
                ], limit=1)
                if inactive_bill:
                    inactive_bill.write({
                        'refunded': True,
                        'bill_state': "refund"
                    })
                    _logger.info(f"🔄 Marked bill {has_inactive_id} as refunded")

            # 10. Success log
            _logger.info(f"✅ eBarimt successfully sent for {self.name}. Bill ID: {response.get('id')}")
            
            return True
            
        except ValidationError:
            raise
        except Exception as e:
            _logger.error(f"❌ Unexpected error in vat_pos_order_commit: {str(e)}", exc_info=True)
            raise ValidationError(f"eBarimt илгээхэд алдаа гарлаа: {str(e)}")

    def send_ebarimt(self):
        order_to_send_vat = self.filtered(
            lambda order: order.state == "done" or order.state == "paid"
        )
        if order_to_send_vat:
            # The confirmation wizard lives in ebarimt_api (the 16.0 code
            # referenced a non-existent ss_pos_ebarimt xmlid).
            action_data = self.env["ir.actions.act_window"]._for_xml_id(
                "ebarimt_api.action_account_ebarimt_confirmation"
            )
            # Odoo 17+ no longer injects active_model/active_ids into the
            # context of an action returned by a type="object" button.
            action_data["context"] = {
                "active_model": self._name,
                "active_id": order_to_send_vat[:1].id,
                "active_ids": order_to_send_vat.ids,
            }
            return action_data
        return False

    def return_ebarimt(self):
        order_vat_receipt = self.env['vat.receipt'].search([
            ('pos_order_id', '=', self.id)
        ], order="create_date desc", limit=1)
        
        if not order_vat_receipt:
            raise ValidationError("No eBarimt receipt found for this order")

        # A second (partial) refund of the same order must not DELETE the
        # already-returned bill again.
        if order_vat_receipt.bill_state == "refund":
            _logger.info("eBarimt bill of %s is already returned", self.name)
            return {"success": True, "result": {"status": "SUCCESS"}}
        
        posapi_services = self.env['account.ebarimt.posapi'].search([
            ('company_id', '=', self.company_id.id)
        ])
        
        if not posapi_services:
            raise ValidationError("eBarimt POS API service is not configured")
        
        posapi = posapi_services[0]
        res = posapi.return_receipt({
            'id': order_vat_receipt.bill_id,
            'date': order_vat_receipt.sent_at.strftime("%Y-%m-%d %H:%M:%S"),
        })
        
        _logger.debug(f'Return receipt result: {res}')

        if 'message' in res:
            order_vat_receipt.sudo().bill_state = "old"

        if 'result' in res:
            response = res["result"]
            if response.get("status") == "SUCCESS":
                order_vat_receipt.sudo().write({"refunded": True, "bill_state": "refund"})
                
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

    def _ebarimt_current_receipt(self):
        """The bill that counts for this order: the latest one still valid
        (after a partial return that is the replacement), else the latest."""
        self.ensure_one()
        receipts = self.env['vat.receipt'].sudo()
        domain = [('pos_order_id', '=', self.id), ('bill_id', '!=', False)]
        return (receipts.search(domain + [('bill_state', '=', 'done')], order='create_date desc, id desc', limit=1)
                or receipts.search(domain, order='create_date desc, id desc', limit=1))

    def _ebarimt_is_replacement(self, receipt):
        """True when `receipt` replaced an earlier bill of this order (partial return)."""
        self.ensure_one()
        return bool(receipt) and receipt.bill_state == 'done' and bool(self.env['vat.receipt'].sudo().search_count([
            ('pos_order_id', '=', self.id), ('bill_state', '=', 'refund'), ('id', '!=', receipt.id),
        ]))

    def _ebarimt_print_lines(self):
        """Items still sold on this order (what a replacement bill covers)."""
        self.ensure_one()
        lines = []
        for line in self.lines:
            qty = line.qty - (getattr(line, 'refunded_qty', 0) or 0)
            if qty <= 0 or not line.qty:
                continue
            lines.append({
                'name': line.full_product_name or line.product_id.display_name,
                'qty': qty,
                'amount': self.currency_id.round(line.price_subtotal_incl * qty / line.qty),
            })
        return lines

    @staticmethod
    def _ebarimt_fmt(amount):
        """Whole tugrik with thousands separators: 28000.0 -> '28,000'."""
        return '{:,.0f}'.format(round(amount or 0.0))

    @staticmethod
    def _ebarimt_qr_base64(qr_data):
        """PNG of the eBarimt QR as base64, or '' when it can't be made."""
        if not qr_data:
            return ''
        try:
            import base64
            import io
            import qrcode
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=2)
            qr.add_data(qr_data)
            qr.make(fit=True)
            buffer = io.BytesIO()
            qr.make_image(fill_color="black", back_color="white").save(buffer, format='PNG')
            return base64.b64encode(buffer.getvalue()).decode()
        except Exception as e:
            _logger.warning("Could not make the eBarimt QR image: %s", e)
            return ''

    def ebarimt_report_data(self):
        """For the PDF receipt: the current bill, whether it replaced an
        earlier one, the printed items and the amounts, ready to show."""
        self.ensure_one()
        receipt = self._ebarimt_current_receipt()
        replaced = self._ebarimt_is_replacement(receipt)
        if replaced:
            items = self._ebarimt_print_lines()
        else:
            items = [{
                'name': line.full_product_name or line.product_id.display_name,
                'qty': line.qty,
                'amount': line.price_subtotal_incl,
            } for line in self.lines if line.qty]
        lines = [{
            'name': item['name'],
            'qty': '%g' % item['qty'],
            'unit': self._ebarimt_fmt(item['amount'] / item['qty']),
            'amount': self._ebarimt_fmt(item['amount']),
        } for item in items]
        total = receipt.amount if replaced else self.amount_total
        company = self.company_id
        seller_tin = (getattr(company.partner_id, 'vat_tin', False) or company.vat or '')
        return {
            'receipt': receipt,
            'replaced': replaced,
            'lines': lines,
            'total': self._ebarimt_fmt(total),
            'vat': self._ebarimt_fmt(receipt.vat) if receipt else '',
            'city_tax': self._ebarimt_fmt(receipt.city_tax) if receipt and receipt.city_tax else '',
            'seller_tin': seller_tin,
            'buyer_tin': receipt.customer_tin if receipt and receipt.bill_type == 'B2B_RECEIPT' else '',
            'buyer_name': self._ebarimt_buyer_name(receipt),
            'qr': self._ebarimt_qr_base64(receipt.qr_data) if receipt else '',
        }

    @api.model
    def get_ebarimt_info(self, order_ids):
        """POS-д eBarimt мэдээлэл буцаах"""
        result = {}
        orders = self.browse(order_ids)
        
        for order in orders:
            receipt = order._ebarimt_current_receipt()
            if receipt:
                result[order.id] = {
                    'bill_id': receipt.bill_id,
                    'vat': receipt.vat,
                    'city_tax': receipt.city_tax,
                    'amount': receipt.amount,
                    'date': receipt.sent_at.strftime('%Y-%m-%d %H:%M:%S') if receipt.sent_at else '',
                    'lottery': receipt.lottery or '',
                    'bill_type': receipt.bill_type,
                }
        
        return result

    def print_ebarimt_receipt(self):
        """eBarimt мэдээлэлтэй receipt хэвлэх"""
        self.ensure_one()
        
        # Report action буцаах
        return self.env.ref('pos_ebarimt.action_report_pos_ebarimt').report_action(self)

    def _ebarimt_buyer_name(self, receipt):
        """Name of the company a B2B bill was issued to, when the order's
        customer is that company (a TIN typed in the popup has no name)."""
        self.ensure_one()
        if not receipt or receipt.bill_type != 'B2B_RECEIPT' or not receipt.customer_tin:
            return ''
        partner = self.partner_id
        tins = {getattr(partner, 'vat_tin', False), partner.vat} - {False, ''}
        return partner.name if receipt.customer_tin in tins else ''

    @api.model
    def get_ebarimt_receipt_data(self, order_identifier, config_id=None):
        """Bill id / lottery / QR of one order, for the POS receipt.

        order_identifier is the server id, or the exact pos_reference / name
        of an order. No fuzzy matching: a near match would print another
        customer's lottery number and QR code.
        """
        try:
            _logger.debug("Getting ebarimt receipt data for identifier: %s", order_identifier)

            order = None

            if isinstance(order_identifier, int):
                order = self.browse(order_identifier)
            elif isinstance(order_identifier, str):
                if order_identifier.isdigit():
                    order = self.browse(int(order_identifier))
                else:
                    domain = [
                        '|',
                        ('pos_reference', '=', order_identifier),
                        ('name', '=', order_identifier),
                    ]
                    if config_id:
                        domain.append(('session_id.config_id', '=', int(config_id)))
                    orders = self.search(domain, limit=2)
                    # Two orders with the same reference: refuse rather than guess.
                    order = orders if len(orders) == 1 else None

            if not order or not order.exists():
                _logger.warning(f"❌ Order not found for identifier: {order_identifier}")
                return {
                    'success': False,
                    'error': 'Захиалга олдсонгүй',
                    'message': f'Order {order_identifier} системд байхгүй байна'
                }
            
            _logger.info(f"✅ Found order: {order.name} (ID: {order.id})")
            
            # The bill that counts now (the replacement after a partial return).
            receipt = order._ebarimt_current_receipt()
            
            if not receipt:
                _logger.info(f"ℹ️ No VAT receipt found for order {order.name}")
                return {
                    'success': False,
                    'message': f'Order {order.name}-д ebarimt баримт олдсонгүй',
                    'order_name': order.name,
                    'order_id': order.id,
                    'vat_sent': getattr(order, 'vat_sent', False)
                }
            
            _logger.info(f"✅ Found VAT receipt: {receipt.bill_id}")
            
            # LOTTERY-г INACTIVE_ID-аас авах энгийн логик
            lottery = receipt.lottery or ""
            
            # Inactive_id талбараас lottery олох
            if not lottery and receipt.inactive_id and 'LOTTERY:' in receipt.inactive_id:
                try:
                    # LOTTERY: хэсгийг олох
                    lottery_part = receipt.inactive_id.split('LOTTERY:')[1]
                    # Хэрэв | агуулсан бол эхний хэсгийг авах
                    if '|' in lottery_part:
                        lottery = lottery_part.split('|')[0]
                    else:
                        lottery = lottery_part
                    
                    _logger.debug(f"🎯 Found lottery in inactive_id: {lottery}")
                    
                except Exception as e:
                    _logger.warning(f"⚠️ Could not parse lottery from inactive_id: {e}")
            
            # QR код үүсгэх
            qr_code_base64 = ""
            if receipt.qr_data:
                try:
                    import qrcode
                    from PIL import Image
                    import io
                    import base64
                    
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=8,
                        border=2,
                    )
                    
                    qr_data = receipt.qr_data
                    qr.add_data(qr_data)
                    qr.make(fit=True)
                    
                    img = qr.make_image(fill_color="black", back_color="white")
                    buffer = io.BytesIO()
                    img.save(buffer, format='PNG')
                    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()
                    
                    _logger.debug(f"✅ QR code generated successfully for {receipt.bill_id}")
                    
                except ImportError:
                    _logger.warning("⚠️ QRCode library not available")
                except Exception as e:
                    _logger.error(f"❌ QR code generation error: {e}")
            
            # Огноо format
            formatted_date = ""
            if receipt.sent_at:
                try:
                    formatted_date = receipt.sent_at.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    formatted_date = str(receipt.sent_at)
            
            # Буцаах мэдээлэл
            result = {
                'success': True,
                'bill_id': receipt.bill_id or '',
                'lottery': lottery,
                'qr_code_base64': qr_code_base64,
                'qr_data': receipt.qr_data or '',
                'vat': float(receipt.vat or 0),
                'city_tax': float(receipt.city_tax or 0),
                'amount': float(receipt.amount or 0),
                'date': formatted_date,
                'bill_type': receipt.bill_type or '',
                'pos_id': receipt.pos_id or '',
                'merchant_tin': receipt.merchant_tin or '',
                'customer_tin': receipt.customer_tin or '',
                'customer_name': order._ebarimt_buyer_name(receipt),
                'bill_state': receipt.bill_state or 'done',
                'order_id': order.id,
                'order_name': order.name,
                'pos_reference': getattr(order, 'pos_reference', ''),
                'created_at': receipt.create_date.strftime('%Y-%m-%d %H:%M:%S') if receipt.create_date else '',
                # After a partial return the bill covers only the kept items:
                # the receipt prints those instead of the original lines.
                'replaced': order._ebarimt_is_replacement(receipt),
            }
            if result['replaced']:
                result['items'] = order._ebarimt_print_lines()
            
            _logger.info(f"📤 Returning ebarimt data for order {order.name}:")
            _logger.debug(f"   - Bill ID: {result['bill_id']}")
            _logger.debug(f"   - Lottery: {result['lottery']}")
            _logger.debug(f"   - QR available: {bool(result['qr_code_base64'])}")
            _logger.debug(f"   - VAT: {result['vat']}")
            _logger.debug(f"   - City Tax: {result['city_tax']}")
            _logger.debug(f"   - Amount: {result['amount']}")
            _logger.debug(f"   - Type: {result['bill_type']}")
            
            return result
                
        except Exception as e:
            _logger.error(f"❌ Error getting ebarimt data for identifier {order_identifier}: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'message': 'ebarimt мэдээлэл авахад алдаа гарлаа',
                'identifier': order_identifier
            }

    # 16.0 overrode ``_order_fields(ui_order)`` to copy ebarimt_* keys from the
    # exported UI order. That hook does not exist in 19.0: the POS JS model
    # serializes every stored pos.order field by name and ``_process_order``
    # passes them straight to create()/write(). The defaults that
    # ``_order_fields`` applied ('individual' / 'B2C_RECEIPT') are now set in
    # the JS PosOrder.setup() patch (static/src/app/models/pos_order_patch.js).
