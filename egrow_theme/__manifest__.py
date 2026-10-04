{
    "name": "egrow Theme",
    "summary": "egrow colors for the Odoo backend and Point of Sale",
    "description": """
        Replaces Odoo's violet with the egrow palette (blue, green, red,
        grey-blue) in the backend, the Point of Sale and reports, by setting
        Odoo's own SCSS color variables. Uninstall to get Odoo's colors back.
    """,
    "author": "egrow",
    "category": "Hidden",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["web", "point_of_sale"],
    "assets": {
        # The POS and report bundles include this bundle too.
        "web._assets_primary_variables": [
            ("prepend", "egrow_theme/static/src/scss/primary_variables.scss"),
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
