import json
import datetime
import requests
import traceback, logging
from odoo import api, models, fields, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# (connect, read) seconds. PosAPI answers a receipt in well under a second; a
# hung service must not freeze the cashier's Validate button.
POSAPI_TIMEOUT = (3, 10)
# The warning check runs before every sale, so it gives up sooner.
POSAPI_WARNING_TIMEOUT = (2, 4)
_MASKED_LOG_KEYS = {"customerTin", "consumerNo", "lottery", "qrData"}

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
            if not record.service_url or (
                "http://" not in record.service_url
                and "https://" not in record.service_url
            ):
                raise UserError(
                    _("Your Service URL might be not qualified. Please use such URL: http://192.168.10.25:9010")
                )
            message = False
            try:
                url = record.service_url
                if url[-1] != "/":
                    url += "/"
                url += "rest/send"
                headers = {
                    "Connection": "keep-alive",
                }
                _status_code, res = record.request_connection(url, headers, [], "GET")

                if _status_code != 200 or _status_code != 404:
                    message = (
                        "PosAPI service connection failed.\nHTTP Error response: %s" % res
                    )
                else:
                    message = (
                        "PosAPI service connection succes.\nResult checkAPI:%s" % res
                    )
            except:
                message = (
                    "Couldn't connected to PosAPI service.\nReason might be: %s" % traceback.format_exc()
                )

            record.write(
                {
                    "message": message,
                    "last_send_date": fields.Datetime.now(),
                }
            )
        return True

    def request_receipt(self, json_order):
        """PosAPI-руу төлбөрийн баримт илгээх сервис"""
        self.ensure_one()
        _logger.debug("PosAPI 3.0 request.receipt params: %s" % json_order)

        result = False
        if not self.service_url or (
            "http://" not in self.service_url and "https://" not in self.service_url
        ):
            raise UserError(
                _("Your Service URL might be not qualified. Please use such URL: http://192.168.10.25:9010")
            )
        message = False
        content = False
        try:
            url = self.service_url
            if url[-1] != "/":
                url += "/"
            url += "rest/receipt"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "keep-alive",
            }
            
            _logger.debug("PosAPI POST %s body: %s", url, json.dumps(self._mask_for_log(json_order)))
            _status_code, res = self.request_connection(url, headers, json_order, "POST")
            _logger.info("PosAPI POST %s -> HTTP %s", url, _status_code)
            _logger.debug("PosAPI response: %s", json.dumps(self._mask_for_log(res)) if isinstance(res, dict) else res)

            if _status_code != 200:
                message = (
                    "PosAPI service connection failed.\nHTTP Error response: %s" % res
                )
            else:
                result = res
        except:
            message = (
                "Couldn't connected to PosAPI service.\nReason might be: %s" % traceback.format_exc()
            )

        if result and result.get("status") == 'ERROR':
            message = result.get("message") or "PosAPI returned an error"

        if message:
            # No commit here: the caller decides (a commit in the middle of
            # the POS transaction used to save half an order).
            self.sudo().write({"message": message})
            return {"success": False, "message": message}

        return {"success": True, "result": result}

    def return_receipt(self, json_order):
        """
            PosAPI-руу төлбөрийн баримт буцаах сервис
        """
        self.ensure_one()
        _logger.debug("PosAPI 3.0 delete.receipt params: %s" % json_order)

        result = False
        if not self.service_url or (
            "http://" not in self.service_url and "https://" not in self.service_url
        ):
            raise UserError(
                _("Your Service URL might be not qualified. Please use such URL: http://192.168.10.25:9010")
            )
        message = False
        try:
            url = self.service_url
            if url[-1] != "/":
                url += "/"
            url += "rest/receipt"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "keep-alive",
            }
            _status_code, res = self.request_connection(url, headers, json_order, "DELETE")
            if _status_code != 200:
                message = (
                    "PosAPI service connection failed.\nHTTP Error response: %s" % res
                )
            else:
                result = res
        except:
            message = (
                "Couldn't connected to PosAPI service.\nReason might be: %s" % traceback.format_exc()
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
            if not record.service_url or (
                "http://" not in record.service_url
                and "https://" not in record.service_url
            ):
                raise UserError(
                    _("Your Service URL might be not qualified. Please use such URL: http://192.168.10.25:9010")
                )
            success = True
            message = False
            try:
                url = record.service_url
                if url[-1] != "/":
                    url += "/"
                url += "rest/info"
                headers = {
                    "Content-Type": "application/json",
                }
                _status_code, res = record.request_connection(url, headers, [], "GET")

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
            except:
                message = (
                    "Couldn't connected to PosAPI service.\nReason might be: %s" % traceback.format_exc()
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

        try:
            # Find PosAPI config
            domain = [('company_id', '=', company_id)] if company_id else []
            posapi = self.search(domain, limit=1)

            if not posapi or not posapi.service_url:
                return {
                    'success': False,
                    'warnings': [{'type': 'error', 'message': 'PosAPI тохиргоо олдсонгүй'}],
                    'lottery_ok': False,
                    'sync_ok': False,
                }

            # Call PosAPI /rest/info
            url = posapi.service_url
            if url[-1] != "/":
                url += "/"
            url += "rest/info"

            headers = {"Content-Type": "application/json"}
            _status_code, res = posapi.request_connection(
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
            _logger.error(f"Error checking PosAPI warnings: {e}")
            return {
                'success': False,
                'warnings': [{'type': 'error', 'message': f'Алдаа: {str(e)}'}],
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

    def request_connection(self, url_string, headers, params, request_type="GET", timeout=None):
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
    report_month = fields.Date("Report Month")
    invoice_id = fields.Char("Invoice ID")
    pos_id = fields.Char("Pos ID")
    refunded = fields.Boolean("Refunded", default=False)
    inactive_id = fields.Char("Inactive Bill ID")
    lottery = fields.Char("Lottery")
    qr_data = fields.Text("QR Data")
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
