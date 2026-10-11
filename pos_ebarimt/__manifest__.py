{
    "name": "POS eBarimt Integration",
    "summary": "ebarimt PosAPI 3.0 Integration for POS",
    "description": """
        This module sends POS Orders to ebarimt system.

        Features:
        * Automatic ebarimt receipt generation after payment
        * Support for B2C and B2B receipts
        * VAT and city tax calculations
        * Receipt refund functionality
        * Integration with Mongolian ebarimt POS API 3.0
        * QR Code display on receipts
        * Lottery number display for consumer receipts
    """,
    "author": "egrow",
    "category": "Point of Sale",
    "version": "19.0.1.7.0",
    "license": "LGPL-3",
    "depends": [
        "base",
        "point_of_sale",
        "ebarimt_api",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/pos_ebarimt_cron.xml",
        "views/pos_config_view.xml",
        "views/pos_order_view.xml",
        "views/pos_payment_method_view.xml",
        "views/district_code_view.xml",
        "views/buna_classfication_views.xml",
        "views/pos_ebarimt_report.xml",
        "views/vat_receipt_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_ebarimt/static/src/app/**/*",
            "pos_ebarimt/static/src/css/pos_ebarimt.css",
        ],
    },
    "external_dependencies": {
        "python": ["qrcode", "Pillow"],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
