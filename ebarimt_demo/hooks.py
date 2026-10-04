"""Demo data for the eBarimt modules, created once at install.

Everything is made in Python (not XML) because the company, taxes and POS
depend on what the accounting chart already created in the fresh database.
Records get XML ids under this module, so they can be found and are removed
with it.
"""

import logging

_logger = logging.getLogger(__name__)

# Public PosAPI test TIN (the ITC test merchant), not a real business.
DEMO_MERCHANT_TIN = "37900846788"
# Placeholder: point it at your own PosAPI or gateway after install.
DEMO_SERVICE_URL = "http://localhost:7080"


def _xmlid(env, record, name):
    env["ir.model.data"].create({
        "module": "ebarimt_demo",
        "name": name,
        "model": record._name,
        "res_id": record.id,
        "noupdate": True,
    })
    return record


def _setup_company(env):
    company = env.ref("base.main_company")
    mn = env.ref("base.mn")
    mnt = env.ref("base.MNT")
    mnt.active = True
    vals = {
        "name": "eBarimt Demo LLC",
        "country_id": mn.id,
        "vat": DEMO_MERCHANT_TIN,
        "vat_tin": DEMO_MERCHANT_TIN,
        "service_url": DEMO_SERVICE_URL,
        "ebarimt_pos_number": "1",
    }
    if "account_fiscal_country_id" in company._fields:
        vals["account_fiscal_country_id"] = mn.id
    company.write(vals)
    company.partner_id.write({"vat_tin": DEMO_MERCHANT_TIN, "country_id": mn.id})
    # Odoo has no Mongolian chart; the generic one gives the accounts and
    # journals the POS needs.
    # Odoo would otherwise load it again at the end of the install, which
    # resets the currency set below.
    if hasattr(env.registry, "_auto_install_template"):
        del env.registry._auto_install_template
    if not company.chart_template:
        env["account.chart.template"].try_loading("generic_coa", company, install_demo=False)
    # The chart sets its own currency, so MNT goes on afterwards (through a
    # fresh environment: loading a chart can reset the registry).
    env = env()
    company = env["res.company"].browse(company.id)
    if company.currency_id != mnt:
        company.currency_id = mnt.id
        env.flush_all()
    return company


def _setup_posapi(env, company):
    posapi = env["account.ebarimt.posapi"].create({
        "name": "Demo PosAPI",
        "company_id": company.id,
        "service_url": DEMO_SERVICE_URL,
    })
    _xmlid(env, posapi, "demo_posapi")


def _setup_taxes(env, company):
    Tax = env["account.tax"].with_company(company)
    country = company.account_fiscal_country_id or company.country_id
    vat_group = _xmlid(env, env["account.tax.group"].create({
        "name": "НӨАТ", "company_id": company.id, "country_id": country.id,
    }), "tax_group_vat")
    city_group = _xmlid(env, env["account.tax.group"].create({
        "name": "НХАТ", "company_id": company.id, "country_id": country.id,
    }), "tax_group_city")
    common = {
        "company_id": company.id,
        "type_tax_use": "sale",
        "amount_type": "percent",
        "price_include_override": "tax_included",
    }
    specs = {
        "tax_vat10": {"name": "НӨАТ 10%", "amount": 10.0, "ebarimt_tax_type": "VAT_ABLE"},
        "tax_city2": {"name": "НХАТ 2%", "amount": 2.0, "city_tax": True},
        "tax_city1": {"name": "НХАТ 1%", "amount": 1.0, "city_tax": True},
        "tax_vat_free": {"name": "НӨАТ-аас чөлөөлөгдсөн 0%", "amount": 0.0, "ebarimt_tax_type": "VAT_FREE"},
        "tax_vat_zero": {"name": "НӨАТ 0% (экспорт)", "amount": 0.0, "ebarimt_tax_type": "VAT_ZERO"},
        "tax_vat10_excl": {"name": "НӨАТ 10% (үнэд нэмэгдэнэ)", "amount": 10.0, "ebarimt_tax_type": "VAT_ABLE",
                           "price_include_override": "tax_excluded"},
    }
    taxes = {}
    for key, spec in specs.items():
        group = city_group if spec.get("city_tax") else vat_group
        vals = dict(common, ebarimt_send_data=True, tax_group_id=group.id, **spec)
        taxes[key] = _xmlid(env, Tax.create(vals), key)
    # The generic chart's own taxes (15%, 0% Exports, ...) don't exist in
    # Mongolia: archive them and make VAT 10% the default sales tax.
    ours = [t.id for t in taxes.values()]
    env["account.tax"].search([("company_id", "=", company.id), ("id", "not in", ours)]).active = False
    company.account_sale_tax_id = taxes["tax_vat10"]
    company.account_purchase_tax_id = False
    return taxes


def _setup_vat_codes(env):
    # Example codes only: check them against the current eBarimt list of
    # VAT-free / 0% goods before relying on them.
    VatCode = env["product.vat.code"]
    free = _xmlid(env, VatCode.create({
        "name": "305", "tax_type": "VAT_FREE",
        "label": "Demo VAT-free code (check against the eBarimt list)",
    }), "vat_code_free")
    zero = _xmlid(env, VatCode.create({
        "name": "501", "tax_type": "VAT_ZERO",
        "label": "Demo 0% code (check against the eBarimt list)",
    }), "vat_code_zero")
    return free, zero


def _setup_products(env, taxes, vat_free_code, vat_zero_code):
    category = _xmlid(env, env["pos.category"].create({"name": "eBarimt Demo"}), "pos_categ_demo")
    Product = env["product.template"]

    def tax_ids(*keys):
        return [(6, 0, [taxes[k].id for k in keys])]

    specs = [
        ("product_vat", "Demo 1 · НӨАТ 10%", 11000, tax_ids("tax_vat10"), {}),
        ("product_vat_city", "Demo 2 · НӨАТ 10% + НХАТ 2% (архи)", 28000, tax_ids("tax_vat10", "tax_city2"), {}),
        ("product_vat_city1", "Demo 3 · НӨАТ 10% + НХАТ 1%", 11100, tax_ids("tax_vat10", "tax_city1"), {}),
        ("product_vat_free", "Demo 4 · НӨАТ-гүй (код 305)", 3500, tax_ids("tax_vat_free"),
         {"vat_code_id": vat_free_code.id}),
        ("product_vat_zero", "Demo 5 · НӨАТ 0% (код 501)", 50000, tax_ids("tax_vat_zero"),
         {"vat_code_id": vat_zero_code.id}),
        ("product_vat_free_nocode", "Demo 6 · НӨАТ-гүй, кодгүй (алдаа гарна)", 2000, tax_ids("tax_vat_free"), {}),
        ("product_no_tax", "Demo 7 · Татваргүй, кодгүй (алдаа гарна)", 1000, [(6, 0, [])], {}),
        ("product_service", "Demo 8 · Үйлчилгээ, НӨАТ 10%", 5500, tax_ids("tax_vat10"), {"type": "service"}),
        ("product_vat_excl", "Demo 9 · НӨАТ үнэд нэмэгдэнэ", 10000, tax_ids("tax_vat10_excl"), {}),
        ("product_odd_1005", "Demo 10 · Бутархай үнэ 1,005", 1005, tax_ids("tax_vat10"), {}),
        ("product_odd_333", "Demo 11 · Бутархай үнэ 333.33", 333.33, tax_ids("tax_vat10"), {}),
    ]
    for xmlid, name, price, taxes_cmd, extra in specs:
        vals = {
            "name": name,
            "list_price": price,
            "taxes_id": taxes_cmd,
            "available_in_pos": True,
            "pos_categ_ids": [(6, 0, [category.id])],
            "type": "consu",
        }
        vals.update(extra)
        _xmlid(env, Product.create(vals), xmlid)


def _setup_partners(env):
    Partner = env["res.partner"]
    _xmlid(env, Partner.create({
        "name": "Demo Хувь хүн (B2C)",
        "country_id": env.ref("base.mn").id,
    }), "partner_b2c")
    # Fill vat_tin with a TIN from your PosAPI test set to try a B2B bill.
    _xmlid(env, Partner.create({
        "name": "Demo Байгууллага (B2B)",
        "is_company": True,
        "country_id": env.ref("base.mn").id,
    }), "partner_b2b")


def _setup_pos(env, company):
    Journal = env["account.journal"].with_company(company)
    cash_journal = _xmlid(env, Journal.create({
        "name": "eBarimt Demo Cash", "type": "cash", "code": "EDCSH", "company_id": company.id,
    }), "journal_cash")
    card_journal = _xmlid(env, Journal.create({
        "name": "eBarimt Demo Card", "type": "bank", "code": "EDCRD", "company_id": company.id,
    }), "journal_card")
    Method = env["pos.payment.method"].with_company(company)
    cash = _xmlid(env, Method.create({
        "name": "Бэлэн мөнгө", "journal_id": cash_journal.id, "company_id": company.id,
        "ebarimt_payment_code": "CASH",
    }), "payment_cash")
    card = _xmlid(env, Method.create({
        "name": "Карт", "journal_id": card_journal.id, "company_id": company.id,
        "ebarimt_payment_code": "PAYMENT_CARD",
    }), "payment_card")
    config = env["pos.config"].with_company(company).create({
        "name": "eBarimt Demo POS",
        "company_id": company.id,
        "payment_method_ids": [(6, 0, [cash.id, card.id])],
        "send_ebarimt": True,
        "ebarimt_branch_no": "0001",
        "limit_categories": True,
        "iface_available_categ_ids": [(6, 0, [env.ref("ebarimt_demo.pos_categ_demo").id])],
    })
    _xmlid(env, config, "pos_config_demo")


def _check_empty_database(env):
    """The hook rewrites the main company: refuse anything but a new database."""
    from odoo.exceptions import UserError
    if env["account.move"].search_count([], limit=1) or env["pos.order"].search_count([], limit=1):
        raise UserError(
            "ebarimt_demo may only be installed in a new, empty database: "
            "it renames the main company and changes its currency."
        )


def post_init_hook(env):
    _check_empty_database(env)
    company = _setup_company(env)
    _setup_posapi(env, company)
    taxes = _setup_taxes(env, company)
    vat_free_code, vat_zero_code = _setup_vat_codes(env)
    _setup_products(env, taxes, vat_free_code, vat_zero_code)
    _setup_partners(env)
    _setup_pos(env, company)
    _logger.info("eBarimt demo data created for %s", company.name)
