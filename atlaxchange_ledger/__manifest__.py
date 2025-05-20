{
    "name": "Atlaxchange Ledger",
    "version": "16.0.1.0.0",
    "summary": "Manage Atlaxchange Client Transaction History",
    "category": "Custom",
    "author": "Novus Solutions",
    "website": "https://novussolutionsltd.com",
    "images": ["static/description/atlax_icon.png"],
    "license": "LGPL-3",
    "depends": ["base", "fetch_users_api", "web", "contacts", "atlaxchange_app"],
    "data": [
        "security/ir.model.access.csv",
        "data/cron_job.xml",
        "views/ledger_views.xml",
        "views/ledger_audit_views.xml",
        "views/ledger_dashboard.xml",  # Dashboard views (Kanban, Graph, Pivot, Tree)
    ],
    "assets": {
        "web.assets_backend": [
            "/atlaxchange_ledger/static/src/js/ledger_dashboard.js",  # JavaScript for KPI dashboard
            "/atlaxchange_ledger/static/src/scss/ledger_dashboard.scss",  # SCSS for dashboard styling
            "/atlaxchange_ledger/static/src/xml/ledger_dashboard_templates.xml",
        ],
        "web.assets_qweb": [
            "/atlaxchange_ledger/static/src/xml/ledger_dashboard_templates.xml",  # QWeb templates for KPI dashboard
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
