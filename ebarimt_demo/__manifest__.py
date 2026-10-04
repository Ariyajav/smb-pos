{
    "name": "eBarimt Demo Data",
    "summary": "Demo company, taxes, products and POS covering every eBarimt tax type",
    "description": """
        Install on a fresh, separate database to try the eBarimt modules.
        Creates a Mongolian demo company, every eBarimt tax type (VAT 10%,
        city tax, VAT free, VAT 0%, tax excluded), one product per case and
        a POS with Cash and Card. No real keys, URLs or customer data.
        Do not install on a live database: it changes the main company.
    """,
    "author": "egrow",
    "category": "Point of Sale",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["account", "point_of_sale", "ebarimt_api", "pos_ebarimt"],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
