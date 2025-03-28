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
        "base","contacts"
    ],
    'data': [
        # Add XML/CSV files here, e.g., 'views/view_file.xml',
        'data/cron_job.xml',
        'data/system_parameters.xml',   
        # 'security/fetch_users_security.xml',
        'security/ir.model.access.csv',
        'views/fetch_users_audit_view.xml',
        'views/res_partner_views.xml'
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}