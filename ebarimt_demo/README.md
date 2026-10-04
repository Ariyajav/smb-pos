# eBarimt Demo Data

Creates a demo setup that covers every eBarimt tax type, so the modules can be
tried and shown without touching a live database. It contains no real keys,
internal addresses or customer data.

**Install it only on a fresh, separate database.** It renames the main company
and changes its country and currency.

## Create the demo database

```
odoo-bin -c <your.conf> -d ebarimt_demo -i ebarimt_demo --stop-after-init
```

Odoo has no Mongolian chart of accounts, so the generic one is loaded and the
company currency is then set to MNT.

Then, in the new database:

1. Open **Accounting › Configuration › eBarimt PosAPI › Demo PosAPI** and
   set the URL (and API key, if you use a gateway) of your PosAPI.
   Do the same for **POS API Request URL** on the company.
2. Open **Point of Sale › eBarimt Demo POS** and start a session.

## What it creates

- Company **eBarimt Demo LLC** (Mongolia, MNT), TIN 37900846788: the public
  PosAPI test merchant.
- Taxes, all price-included unless noted:

| Tax | eBarimt type |
|---|---|
| НӨАТ 10% | VAT_ABLE |
| НХАТ 2%, НХАТ 1% | city tax, added on top of VAT |
| НӨАТ-аас чөлөөлөгдсөн 0% | VAT_FREE (needs a VAT code on the product) |
| НӨАТ 0% (экспорт) | VAT_ZERO (needs a VAT code on the product) |
| НӨАТ 10% (үнэд нэмэгдэнэ) | VAT_ABLE, price excludes tax |

- VAT codes 305 (VAT free) and 501 (0%). These are examples: check them against
  the current eBarimt code list before relying on them.
- A POS with **Бэлэн мөнгө** (CASH) and **Карт** (PAYMENT_CARD), showing only
  the demo products.
- Two customers: a person (B2C) and a company (B2B). Put a TIN from your
  PosAPI test set on the B2B one to try a company bill.

## Test scenarios

| Sale | Expected eBarimt result |
|---|---|
| Demo 1 · НӨАТ 10%, 11,000 | VAT 1,000 |
| Demo 2 · НӨАТ + НХАТ 2%, 28,000 | VAT 2,500, city tax 500 |
| Demo 3 · НӨАТ + НХАТ 1%, 11,100 | VAT 1,000, city tax 100 |
| Demo 4 · НӨАТ-гүй, 3,500 | VAT_FREE item with code 305, no VAT |
| Demo 5 · НӨАТ 0%, 50,000 | VAT_ZERO item with code 501, no VAT |
| Demo 6 or 7 · no VAT code | Sending stops with a clear error asking for a VAT code |
| Demo 8 · service, 5,500 | VAT 500 |
| Demo 9 · tax excluded, 10,000 | Customer pays 11,000, VAT 1,000 |
| Demo 10 and 11 · odd prices | Amounts rounded consistently, totals match payment |
| Mixed basket (1 + 4 + 5) | One bill with VAT_ABLE, VAT_FREE and VAT_ZERO items |
| 10% discount on Demo 1 | Bill total and VAT reduced by 10% |
| Cash with change | Payment equals the bill total, not the cash handed over |
| Card payment | Payment code PAYMENT_CARD |
| B2B customer with TIN | Company bill with the customer TIN, no lottery |
| Full refund | Original bill marked as returned |
| Partial refund | New bill for the kept items, old bill replaced |
| Exchange | New bill for kept and new items, old bill replaced |
| PosAPI stopped during a sale | Bill pending, sent later by the cron |
