from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    user_inactivity_timeout = fields.Integer(
        string="User Inactivity Timeout (seconds)",
        config_parameter="user_inactivity_timeout",
        default=3600,
        help="Automatically log out users after this many seconds of inactivity.",
    )
