from odoo import models, fields


class ResUsers(models.Model):
    _inherit = "res.users"

    # Stores the SID of the user's currently active session (for single-session enforcement)
    active_session_sid = fields.Char(index=True, readonly=False)
