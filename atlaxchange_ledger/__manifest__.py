{
    "name": "Atlaxchange Ledger",
    "version": "16.0.1.0.0",
    "summary": "Manage Atlaxchange Client Transaction History",
    "category": "Custom",
    "author": "Novus Solutions",
    "website": "https://novussolutionsltd.com",
    "images": ["static/description/atlax_icon.png"],
    "license": "LGPL-3",
    "depends": ["base", "fetch_users_api", "web", "contacts", "atlaxchange_app", "board"],
    "data": [
        "security/ir.model.access.csv",
        "data/cron_job.xml",
        "views/ledger_views.xml",
        "views/ledger_audit_views.xml"
    ],
    # "assets": {
    #     "web.assets_backend": [
    #         "/atlaxchange_ledger/static/src/js/ledger.js",
    #         "/atlaxchange_ledger/static/src/css/ledger.css",
    #     ],
    #     "web.assets_qweb": [
    #         "atlaxchange_ledger/static/src/xml/ledger.xml",
    #     ],
    # },
    "installable": True,
    "application": True,
    "auto_install": False,
}
