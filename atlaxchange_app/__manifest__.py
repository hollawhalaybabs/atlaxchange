{
    "name": "Atlaxchange Application",
    "version": "1.0",
    "summary": "Manages funding, trading, and refund workflows with approval processes.",
    "author": "Novus Solutions",
    "website": "https://novussolutionsltd.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "crm", "contacts"],
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "views/funding_views.xml",
        "views/trade_views.xml",
        "views/refund_views.xml",
        "views/currency_views.xml",
        "data/email_templates.xml",
        "data/automated_actions.xml",
        "data/scheduled_actions.xml"
    ],
    "installable": True,
    "application": True
}