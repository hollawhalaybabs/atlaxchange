{
    "name": "Atlax Business Development",
    "version": "16.0.1.0.0",
    "summary": "Business development pipeline for customers and vendors",
    "author": "Novus Solutions",
    "category": "CRM",
    "depends": ["base", "mail", "helpdesk", "atlaxchange_app"],
    "data": [
        "security/ir.model.access.csv",
        "data/email_templates.xml",
        "views/bd_opportunity_views.xml"
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
