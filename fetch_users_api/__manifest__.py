{
    'name': 'Atlax Addons',
    'version': '16.0.1.0.0',
    'summary': 'Custom addons for AtlaxChange',
    'description': 'This module contains custom addons for AtlaxChange.',
    'author': 'Novus Solutions',
    'website': 'https://www.novussolutionsltd.com',
    'category': 'Custom',
    'license': 'LGPL-3',
    'depends': [
        "base", "contacts", "atlaxchange_app"
    ],
    'data': [
        'data/cron_job.xml',
        'data/system_parameters.xml',
        'security/ir.model.access.csv',
        'views/fetch_users_audit_view.xml',
        'views/res_partner_views.xml',
        'views/business_payment_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}