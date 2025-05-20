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
        "views/conversion_fee_views.xml",
        "views/create_conversion_fee_view.xml",
        "views/update_conversion_fee_wizard_view.xml",
        "data/email_templates.xml",
        "data/automated_actions.xml",
        "data/scheduled_actions.xml",
        "views/reject_wizard_views.xml"
    ],
    "installable": True,
    "application": True
}