{
    "name": "Theme Atlax",
    "description": "Custom theme for Atlax Exchange",
    "version": "1.0",
    "category": "Theme/Custom",
    "license": "LGPL-3",
    "author": "Novus Solutions",
    "depends": ["web"],
    "data": [
        "views/theme_atlax.xml"
    ],
    "assets": {
        "web.assets_frontend": [
            "/theme_atlax/static/src/scss/style.scss"
        ]
    },
    "installable": True,
    "application": False,
}