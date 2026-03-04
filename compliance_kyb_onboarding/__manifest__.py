# -*- coding: utf-8 -*-
{
    "name": "Compliance KYB Onboarding",
    "version": "16.0.1.0.0",
    "summary": "KYB onboarding with public /onboarding token URL + internal compliance review linked to BD",
    "category": "Operations/Compliance",
    "author": "Atlax Exchange",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "mail",
        "hr",
        "atlax_business_development",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/kyb_requirement_templates.xml",
        "data/mail_templates.xml",
        "views/kyb_review_views.xml",
        "views/kyb_requirement_template_views.xml",
        "views/kyb_menu.xml",
        "views/res_config_settings_views.xml",
        "views/website_templates.xml",
    ],
    
    "assets": {
        "web.assets_frontend": [
            "compliance_kyb_onboarding/static/src/css/onboarding.css",
        ],
    },
    "application": True,
    "installable": True,
}
