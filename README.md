# eBarimt for Odoo 19

Odoo 19 modules that issue Mongolian eBarimt receipts (PosAPI 3.x) from Point of Sale and invoices.

- `ebarimt_api`: PosAPI connection, receipt records, tax and product codes.
- `pos_ebarimt`: sends a receipt when a POS order is paid and prints the bill id, lottery and QR code on the POS receipt.
- `pos_offering`: prayer readings with no fixed price, for monasteries. On Payment the cashier enters who the offering is from, the number of family members, the reading day and one offering amount for the order. Offering orders get no eBarimt bill. Mark readings with Offering = Reading on the product; edit reading days under Point of Sale > Configuration > Reading Days.
- `egrow_theme`: optional egrow colors for the backend and POS.
- `ebarimt_demo`: demo company, taxes, products and POS covering every eBarimt tax type. Install it on a fresh database only; see `ebarimt_demo/README.md`.

`ebarimt_api` can call PosAPI directly or through a gateway that takes an `X-API-Key` header (set it on the PosAPI record).

## License

LGPL-3.0. See `LICENSE` (GNU LGPL v3) and `COPYING` (GNU GPL v3, which the LGPL builds on).
