from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests

class UpdateConversionFeeWizard(models.TransientModel):
    _name = 'update.conversion.fee.wizard'
    _description = 'Update Conversion Fee Wizard'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string='Partner', domain=[('is_atlax_customer', '=', True)])
    conversion_id = fields.Many2one('conversion.fee', string='Conversion Rate')
    rate_id = fields.Char(string='Rate ID', readonly=True)
    rate = fields.Float(string='Rate Amount', required=True)
    submitted_at = fields.Datetime(string='Submitted At', default=fields.Datetime.now, readonly=True)

    def action_update_fee(self):
        """Call external API to update the conversion fee."""
        self.ensure_one()
        if not self.rate_id:
            raise UserError(_("Rate ID is missing."))

        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        url = f"https://api.atlaxchange.com/api/v1/currency-rates/{self.rate_id}"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        payload = {
            "rate": self.rate,  # Ensure integer for API
        }
        response = requests.patch(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to update conversion fee: %s") % response.text)
        # Update the conversion.fee record with the new rate 
        fee = self.env['conversion.fee'].search([('rate_id', '=', self.rate_id)], limit=1)
        if fee:
            fee.write({
                'rate': self.rate,
                'updated_at': self.submitted_at,
            })
        return {'type': 'ir.actions.act_window_close'}




