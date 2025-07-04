{
    "name": "Atlaxchange – Trade & Treasury (FX & Liquidity)",
    "version": "16.0.1.0.0",
    "summary": "Compute & manage company FX business rates from multiple liquidity sources",
    "author": "Novus Solutions",
    "category": "Customization",
    "depends": ["base", "mail", "atlaxchange_app"], 
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/fx_rate_sequence.xml",
        "views/fx_rate_views.xml",
        "views/menus.xml",
    ],
    "demo": [],
    "application": True,
    "license": "LGPL-3",
}
