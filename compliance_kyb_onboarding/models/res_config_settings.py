# -*- coding: utf-8 -*-
from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    kyb_show_risk_section_public = fields.Boolean(
        string="Show Risk-based section on public onboarding",
        config_parameter="compliance_kyb_onboarding.show_risk_public",
        default=False,
    )
