from odoo import models, fields, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    atlax_env = fields.Selection(
        [('staging', 'Staging'), ('production', 'Production')],
        string='Atlax Environment',
        config_parameter='atlax.api.env',
        help='Controls which environment the Atlax API client targets.'
    )

    atlax_base_url_staging = fields.Char(
        string='Base URL (Staging)',
        config_parameter='atlax.api.base_url.staging',
        help='Optional override for the Atlax API staging base URL.'
    )
    atlax_base_url_production = fields.Char(
        string='Base URL (Production)',
        config_parameter='atlax.api.base_url.production',
        help='Optional override for the Atlax API production base URL.'
    )

    atlax_api_key_staging = fields.Char(
        string='API Key (Staging)',
        config_parameter='atlax.api.key.staging'
    )
    atlax_api_secret_staging = fields.Char(
        string='API Secret (Staging)',
        config_parameter='atlax.api.secret.staging'
    )

    atlax_api_key_production = fields.Char(
        string='API Key (Production)',
        config_parameter='atlax.api.key.production'
    )
    atlax_api_secret_production = fields.Char(
        string='API Secret (Production)',
        config_parameter='atlax.api.secret.production'
    )
