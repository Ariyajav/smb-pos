import json
import datetime
import ipaddress
import requests
import sys
import logging
from urllib.parse import urlsplit
from odoo import api, models, fields, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# (connect, read) seconds. PosAPI answers a receipt in well under a second; a
# hung service must not freeze the cashier's Validate button.
POSAPI_TIMEOUT = (3, 10)
# The warning check runs before every sale, so it gives up sooner.
POSAPI_WARNING_TIMEOUT = (2, 4)
_MASKED_LOG_KEYS = {"customerTin", "consumerNo", "lottery", "qrData"}
RECEIPT_SECRET_GROUPS = "account.group_account_invoice,point_of_sale.group_pos_manager"



# Tailscale gives each device an address in the CGNAT range; traffic between
# them is WireGuard-encrypted, so plain http to it does not expose the key.
_TAILNET = ipaddress.ip_network("100.64.0.0/10")


def _is_local_host(hostname):
    """This machine, a private LAN address (10.x, 172.16-31.x, 192.168.x) or
    a Tailscale address (100.64.0.0/10), where a gateway key may travel over
    plain http. Only IP literals count: a DNS name could resolve anywhere."""
    if hostname.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (address.is_loopback
            or (address.is_private and not address.is_link_local)
            or address in _TAILNET)


def _short_reason():
    """One line for the message fields POS users can read; the full
    traceback goes to the server log only."""
    _logger.exception("PosAPI call failed")
    exc = sys.exc_info()[1]
    return type(exc).__name__ if exc is not None else "unknown error"

class eBarimtPosAPI(models.Model):
    _name = "account.ebarimt.posapi"
    _description = "Model for PosAPI 3.0 Integration"

    name = fields.Char(
        "eBarimt PosAPI",
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        "Company",
        default=lambda self: self.env.company,
    )
    service_url = fields.Char(
        "Service URL",
        copy=False,
    )
    api_key = fields.Char(
        "Gateway API Key",
        copy=False,
        groups="base.group_system",
        help="X-API-Key for the operator gateway. Leave empty when calling PosAPI directly.",
    )
    last_send_date = fields.Datetime(
        "Last Send Date",
        readonly=True,
        help="Last Date of sendData function of PosAPI was called",
    )
    next_send_date = fields.Datetime(
        "Next Data Send Date",
        readonly=True,
        copy=False,
    )
    send_interval_unit = fields.Selection(
        [
            ('daily', 'Daily'),
            ('hourly', 'Hourly'),
            ('30minute', 'Every 30 minute'),
        ],
        "Call Interval for Send Data",
        required=True,
        default="hourly",
    )
    message = fields.Text(
        "Message",
        copy=False,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if any('service_url' in vals for vals in vals_list):
            self._ebarimt_check_url_access()
        records = super().create(vals_list)
        records._ebarimt_check_url_scheme()
        return records

    def write(self, vals):
        if 'service_url' in vals:
            self._ebarimt_check_url_access()
        res = super().write(vals)
        if 'service_url' in vals or 'api_key' in vals:
            self._ebarimt_check_url_scheme()
        return res

    def _ebarimt_check_url_access(self):
        # The gateway key is sent to this URL, so whoever can change it can
        # read the key: keep it as locked down as the key itself.
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only administrators can change the PosAPI Service URL."))

    def _ebarimt_check_url_scheme(self):
        """The gateway key must not travel unencrypted to another machine."""
        for record in self.sudo():
            if record.service_url and record.api_key:
                record._ebarimt_base_url()

    def _ebarimt_base_url(self):
        """Service URL ending with '/', checked: http(s) with a host, and
        https whenever a gateway key is sent (except to this machine or the LAN)."""
        self.ensure_one()
        url = (self.service_url or "").strip()
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise UserError(
                _("Your Service URL might be not qualified. Please use such URL: http://192.168.10.25:9010")
            )
        if (parts.scheme != "https" and self.sudo().api_key
                and not _is_local_host(parts.hostname)):
            raise UserError(_("The PosAPI Service URL must use https when a Gateway API Key is set "
                              "(plain http is allowed only to localhost, a private LAN address or a Tailscale address)."))
        return url if url.endswith("/") else url + "/"

    def _get_next_send_date(self):
        if self.send_interval_unit == "daily":
            next_update = relativedelta(days=+1)
        elif self.send_interval_unit == "hourly":
            next_update = relativedelta(hours=+1)
        elif self.send_interval_unit == "30minute":
            next_update = relativedelta(minutes=+30)
        else:
            return False
        return datetime.datetime.now() + next_update

    @api.model
    def run_send_data(self, company_ids=None):
        if company_ids:
            records = self.search(
                [
                    ("next_send_date", "<=", fields.Datetime.now()),
                    ("company_id", "in", company_ids),
                ]
            )
        else:
            records = self.search(
                [
                    ("next_send_date", "<=", fields.Datetime.now()),
                ]
            )
        to_send = self.env["account.ebarimt.posapi"]
        for record in records:
            record.next_send_date = record._get_next_send_date()
            to_send += record

        return to_send.send_data()

    def send_data(self):
        """
            PosAPI-с Төлбөрийн баримтын нэгдсэн системд мэдээлэл илгээх сервис
        """
        for record in self:
            record._send_data_one()
        return True

    def _send_data_one(self):
        """Call PosAPI sendData once; store and return (ok, message)."""
        self.ensure_one()
        ok = False
        url = self._ebarimt_base_url()
        try:
            _status_code, res = self._request_connection(url + "rest/sendData", {"Connection": "keep-alive"}, [], "GET")
            if _status_code == 200:
                ok = True
                message = _("Receipts were sent to the eBarimt system.")
                try:
                    _info_status, info = self._request_connection(url + "rest/info", {}, [], "GET")
                    if _info_status == 200 and isinstance(info, dict) and info.get("lastSentDate"):
                        message += "\n" + _("Last sent: %s", info["lastSentDate"])
                except requests.RequestException:
                    pass
            else:
                message = _("PosAPI sendData failed (HTTP %(code)s): %(res)s", code=_status_code, res=res)
        except requests.RequestException:
            message = _("Couldn't connect to PosAPI service. Reason might be: %s", _short_reason())
        vals = {"message": message}
        if ok:
            vals["last_send_date"] = fields.Datetime.now()
        self.write(vals)
        return ok, message

    @api.model
    def pos_send_data(self, company_id=None):
        """POS button: ask PosAPI to send the stored receipts now. Any POS
        user may trigger it; sendData only pushes receipts that PosAPI
        already holds."""
        company = self.env["res.company"].browse(company_id) if company_id else self.env.company
        if company not in self.env.user.company_ids:
            raise AccessError(_("You have no access to this company."))
        posapi = self.sudo().search([("company_id", "=", company.id)], limit=1)
        if not posapi:
            return {"ok": False, "message": _("No PosAPI settings for %s.", company.name)}
        ok, message = posapi._send_data_one()
        return {"ok": ok, "message": message}

    def _request_receipt(self, json_order):
        """PosAPI-руу төлбөрийн баримт илгээх сервис"""
        self.ensure_one()
        _logger.debug("PosAPI 3.0 request.receipt params: %s", json.dumps(self._mask_for_log(json_order)))

        result = False
        url = self._ebarimt_base_url() + "rest/receipt"
        message = False
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "keep-alive",
            }
            
            _logger.debug("PosAPI POST %s body: %s", url, json.dumps(self._mask_for_log(json_order)))
            _status_code, res = self._request_connection(url, headers, json_order, "POST")
            _logger.info("PosAPI POST %s -> HTTP %s", url, _status_code)
            _logger.debug("PosAPI response: %s", json.dumps(self._mask_for_log(res)) if isinstance(res, dict) else res)

            if _status_code != 200:
                message = (
                    "PosAPI service connection failed.\nHTTP Error response: %s" % res
                )
            else:
                result = res
        except Exception:
            message = (
                "Couldn't connected to PosAPI service.\nReason might be: %s" % _short_reason()
            )

        if result and result.get("status") == 'ERROR':
            message = result.get("message") or "PosAPI returned an error"

        if message:
            # No commit here: the caller decides (a commit in the middle of
            # the POS transaction used to save half an order).
            self.sudo().write({"message": message})
            return {"success": False, "message": message}

        return {"success": True, "result": result}

    def _return_receipt(self, json_order):
        """
            PosAPI-руу төлбөрийн баримт буцаах сервис
        """
        self.ensure_one()
        _logger.debug("PosAPI 3.0 delete.receipt params: %s" % json_order)

        result = False
        url = self._ebarimt_base_url() + "rest/receipt"
        message = False
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "keep-alive",
            }
            _status_code, res = self._request_connection(url, headers, json_order, "DELETE")
            if _status_code != 200:
                message = (
                    "PosAPI service connection failed.\nHTTP Error response: %s" % res
                )
            else:
                result = res
        except Exception:
            message = (
                "Couldn't connected to PosAPI service.\nReason might be: %s" % _short_reason()
            )

        if result and not result.get("status", "SUCCESS"):
            message = result["message"]

        if message:
            # No commit here: the caller decides (a commit in the middle of
            # the POS transaction used to save half an order).
            self.sudo().write({"message": message})
            return {"success": False, "message": message}

        return {"success": True, "result": result}

    def action_check_service(self):
        self.ensure_one()
        for record in self:
            url = record._ebarimt_base_url() + "rest/info"
            success = True
            message = False
            try:
                headers = {
                    "Content-Type": "application/json",
                }
                _status_code, res = record._request_connection(url, headers, [], "GET")

                if _status_code != 200:
                    message = (
                        "PosAPI service connection failed.\nHTTP Error response: %s" % res
                    )
                    success = False
                else:
                    get_info_result = res

                    message = (
                        "Result INFO:\n%s" % get_info_result
                    )
            except Exception:
                message = (
                    "Couldn't connected to PosAPI service.\nReason might be: %s" % _short_reason()
                )
                success = False

            if not success:
                self.write({"message": message})
                raise UserError(message)

            self.write(
                {
                    "message": message,
                    "last_send_date": fields.Datetime.now(),
                    "next_send_date": self._get_next_send_date(),
                }
            )

            return True

    @api.model
    def check_posapi_warnings(self, company_id=None):
        """
        PosAPI-ийн төлөв шалгаж анхааруулга буцаах
        - Сугалааны дугаар дуусаж байгаа эсэх
        - Борлуулалтын мэдээ илгээх хугацаа хэтэрсэн эсэх
        """
        warnings = []
        lottery_ok = True
        sync_ok = True
        left_lotteries = 0
        days_until_deadline = 3

        company = self.env["res.company"].browse(company_id) if company_id else self.env.company
        if company not in self.env.user.company_ids:
            raise AccessError(_("You have no access to this company."))

        try:
            # Find PosAPI config
            posapi = self.search([('company_id', '=', company.id)], limit=1)

            if not posapi or not posapi.service_url:
                return {
                    'success': False,
                    'warnings': [{'type': 'error', 'message': 'PosAPI тохиргоо олдсонгүй'}],
                    'lottery_ok': False,
                    'sync_ok': False,
                }

            # Call PosAPI /rest/info
            url = posapi._ebarimt_base_url() + "rest/info"

            headers = {"Content-Type": "application/json"}
            _status_code, res = posapi._request_connection(
                url, headers, [], "GET", timeout=POSAPI_WARNING_TIMEOUT
            )

            if _status_code != 200:
                return {
                    'success': False,
                    'warnings': [{'type': 'error', 'message': 'PosAPI холболт амжилтгүй'}],
                    'lottery_ok': False,
                    'sync_ok': False,
                }

            # Check lottery count
            left_lotteries = res.get('leftLotteries', 0)
            lottery_threshold = 100  # Default threshold

            if left_lotteries == 0:
                warnings.append({
                    'type': 'critical',
                    'message': '⛔ СУГАЛААНЫ ДУГААР ДУУССАН! Баримт сугалаагүй хэвлэгдэнэ.',
                    'code': 'NO_LOTTERY'
                })
                lottery_ok = False
            elif left_lotteries < lottery_threshold:
                warnings.append({
                    'type': 'warning',
                    'message': f'⚠️ Сугалааны дугаар дуусаж байна! Үлдсэн: {left_lotteries}',
                    'code': 'LOW_LOTTERY'
                })

            # Check sync deadline (3 days)
            last_sent_date = res.get('lastSentDate', '')
            if last_sent_date:
                from datetime import datetime, timedelta
                try:
                    last_sent_dt = datetime.strptime(last_sent_date, '%Y-%m-%d %H:%M:%S')
                    now = datetime.now()
                    days_passed = (now - last_sent_dt).days
                    days_until_deadline = 3 - days_passed

                    if days_passed >= 3:
                        warnings.append({
                            'type': 'critical',
                            'message': f'⛔ МЭДЭЭ ИЛГЭЭХ ХУГАЦАА ХЭТЭРСЭН! ({days_passed} өдөр болсон)',
                            'code': 'SYNC_OVERDUE'
                        })
                        sync_ok = False
                    elif days_passed >= 2:
                        warnings.append({
                            'type': 'warning',
                            'message': f'⚠️ Мэдээ илгээх хугацаа дуусаж байна! {days_until_deadline} өдөр үлдсэн',
                            'code': 'SYNC_WARNING'
                        })
                except Exception as e:
                    _logger.error(f"Error parsing lastSentDate: {e}")

            return {
                'success': True,
                'warnings': warnings,
                'lottery_ok': lottery_ok,
                'sync_ok': sync_ok,
                'left_lotteries': left_lotteries,
                'days_until_deadline': days_until_deadline,
                'last_sent_date': last_sent_date,
            }

        except Exception as e:
            _logger.exception("Error checking PosAPI warnings")
            return {
                'success': False,
                'warnings': [{'type': 'error', 'message': 'PosAPI шалгахад алдаа гарлаа'}],
                'lottery_ok': False,
                'sync_ok': False,
            }

    @api.model
    def _mask_for_log(self, data):
        """Copy of a PosAPI payload with customer data and lottery numbers
        masked (a printed lottery number can be claimed by anyone)."""
        if isinstance(data, dict):
            return {
                k: (("***" + str(v)[-3:]) if k in _MASKED_LOG_KEYS and v else self._mask_for_log(v))
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [self._mask_for_log(v) for v in data]
        return data

    # The PosAPI calls are private (leading underscore) so they can't be
    # called over RPC: POS users can read this record, and a public method
    # let any cashier issue or void bills, or send the gateway key to any URL.
    def _request_connection(self, url_string, headers, params, request_type="GET", timeout=None):
        """Call PosAPI (or the gateway in front of it).

        Raises requests.RequestException (Timeout, ConnectionError, ...) when
        the service can't be reached in time; every caller turns that into a
        message instead of blocking the POS forever.
        """
        api_key = self.sudo().api_key if self else False
        if api_key:
            headers = dict(headers, **{"X-API-Key": api_key})
        kwargs = {
            "headers": headers,
            "timeout": timeout or POSAPI_TIMEOUT,
            # Never forward the API key to wherever a redirect points.
            "allow_redirects": False,
        }
        if request_type == "POST":
            res = requests.post(url_string, json=params, **kwargs)
        elif request_type == "DELETE":
            res = requests.delete(url_string, json=params, **kwargs)
        else:
            res = requests.get(url_string, **kwargs)
        if request_type == "DELETE" and res.status_code == 200:
            return (res.status_code, {"status": "SUCCESS"})
        try:
            return (res.status_code, res.json())
        except ValueError:
            return (res.status_code, {"status": "ERROR", "message": res.text[:500]})


class VatBillReceipt(models.Model):
    _name = "vat.receipt"
    _description = "Ebarimt Receipt"
    _order = "create_date desc, id desc"
    _rec_name = "bill_id"

    account_move_id = fields.Many2one("account.move")
    pos_order_id = fields.Many2one("pos.order")
    account_payment_id = fields.Many2one("account.payment")

    company_id = fields.Many2one(
        "res.company", "Company", required=True, default=lambda self: self.env.company
    )

    bill_id = fields.Char("Bill ID")
    bill_type = fields.Char("Bill Type")
    tax_type = fields.Char("Tax Type")
    merchant_tin = fields.Char("Merchant Tin")
    customer_tin = fields.Char("Customer Tin")
    amount = fields.Float("Total Amount")
    vat = fields.Float("Total Vat")
    city_tax = fields.Float("Total City Tax")
    sent_at = fields.Datetime("Sent Date")
    posapi_date = fields.Char(
        "PosAPI Date", readonly=True,
        help="Bill date exactly as PosAPI returned it (PosAPI's local time). "
             "Sent back unchanged when the bill is returned.",
    )
    report_month = fields.Date("Report Month")
    invoice_id = fields.Char("Invoice ID")
    pos_id = fields.Char("Pos ID")
    refunded = fields.Boolean("Refunded", default=False)
    inactive_id = fields.Char("Inactive Bill ID")
    # A lottery number (and the QR that carries it) can be claimed by whoever
    # holds it: cashiers get them only for the receipt they are printing.
    lottery = fields.Char("Lottery", groups=RECEIPT_SECRET_GROUPS)
    qr_data = fields.Text("QR Data", groups=RECEIPT_SECRET_GROUPS)
    bill_state = fields.Selection(
        [
            ('done', 'Bill Sent'),
            ('old', 'Needs to be Refunded'),
            ('refund', 'Refunded'),
            ('invoice', 'Invoice')
        ],
        "State",
        default="done",
    )

    @api.model
    def _posapi_sent_vals(self, posapi_date):
        """sent_at is the server's own clock; PosAPI's ``date`` is kept as
        given, because a return must send it back unchanged."""
        if not isinstance(posapi_date, str):
            posapi_date = False
        return {"sent_at": fields.Datetime.now(), "posapi_date": posapi_date}

    def _posapi_return_date(self):
        """The bill date PosAPI expects back when the bill is returned.
        Bills saved before posapi_date existed kept PosAPI's local time in
        sent_at itself."""
        self.ensure_one()
        if self.posapi_date:
            return self.posapi_date
        return self.sent_at.strftime("%Y-%m-%d %H:%M:%S") if self.sent_at else ""
