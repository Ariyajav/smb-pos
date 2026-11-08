{
    "name": "POS Offerings",
    "summary": "Prayer readings with no fixed price: one offering amount per order",
    "description": """
        For monasteries: the cashier adds the readings (products marked as
        offering readings, sold at no fixed price) and, on Payment, enters
        who the offering is from, the number of family members, the reading
        day and one offering amount for the whole order. The amount is added
        as an "Offering" line. Offering orders get no eBarimt bill.
    """,
    "author": "egrow",
    "category": "Point of Sale",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "pos_ebarimt",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/pos_offering_data.xml",
        "views/pos_offering_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_offering/static/src/app/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
