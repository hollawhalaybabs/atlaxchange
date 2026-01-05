{
    "name": "User Session Timeout",
    "summary": "Automatically logs out inactive users of Odoo",
    "description": """
User Session Timeout for Odoo 16
===============================

Enhances Odoo 16 security by logging out users after inactivity. Monitors mouse, keyboard, and scroll activity to terminate idle sessions, protecting sensitive data.

Key Features:
- Configurable timeout via 'user_inactivity_timeout' (default: 10 minutes).
- Multi-tab activity synchronization.
- Tracks diverse user interactions efficiently.
- Pauses timer when tab is hidden.
- Seamless Odoo 16 integration.

Contact: info@novussolutions.com
    """,
    "version": "16.0",
    "category": "Extra Tools",
    "author": "Novus Solutions",
    "license": "AGPL-3",
    "depends": ["base", "base_setup", "web"],
    "data": [
        "data/ir_config_parameter_data.xml",
        "views/res_config_settings_view.xml",
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "user_session_timeout/static/src/js/user_session_timeout.js",
        ],
        "web.assets_frontend": [
            "user_session_timeout/static/src/js/user_session_timeout.js",
        ],
    },
    'images': ['static/description/icon.png'],
    "installable": True,
    "application": False,
    "auto_install": False,
}
