{
    'name': "eBarimt PosAPI 3.0 Integration",
    'summary': "This module will allow you to integrate Odoo with your PosAPI in order to send sales data to VAT Online System",
    'description': """
        ========================================================================================
    """,
    'author': "egrow",
    'category': 'Accounting',
    'version': '19.0.1.5.3',
    'license': 'LGPL-3',
    'depends': ['base', 'account', 'sale', 'point_of_sale', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'data/ebarimt_data.xml',
        # 'data/mongolian_states.xml',
        'views/ebarimt_views.xml',
        'views/ebarimt_menu_views.xml',
        'views/product_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/account_tax_views.xml',
        # 'views/account_move_views.xml',
        'views/sale_ebarimt_report.xml',
        'wizard/ebarimt_confirmation_views.xml',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
