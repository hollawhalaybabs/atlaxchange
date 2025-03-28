from odoo import models, fields

class ResCurrency(models.Model):
    _inherit = 'res.currency'

    # Add custom fields if needed
    atlax_description = fields.Text(string="Atlax Description")
    name = fields.Char(string='Currency', size=4, required=True, help="Currency Code (ISO 4217)")