from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests

class UpdateConversionFeeWizard(models.TransientModel):
    _name = 'update.conversion.fee.wizard'
    _description = 'Update Conversion Fee Wizard'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string='Partner', domain=[('is_atlax_customer', '=', True)])
    conversion_id = fields.Many2one('conversion.fee', string='Conversion Fee')
    rate_line_id = fields.Many2one('conversion.fee.rate.line', string='Rate Line')
    rate_id = fields.Char(string='Rate ID')
    rate = fields.Float(string='Rate Amount', required=True)
    submitted_at = fields.Datetime(string='Submitted At', default=fields.Datetime.now, readonly=True)

    @api.onchange('rate_line_id')
    def _onchange_rate_line_id(self):
        if self.rate_line_id:
            self.rate_id = self.rate_line_id.rate_id
            self.rate = self.rate_line_id.rate
            self.conversion_id = self.rate_line_id.conversion_fee_id
            self.partner_id = self.rate_line_id.conversion_fee_id.partner_id

    def action_update_fee(self):
        """Call external API to update the conversion fee rate line."""
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
            "rate": self.rate, 
        }
        response = requests.patch(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to update conversion fee: %s") % response.text)
        # Update the conversion.fee.rate.line record with the new rate 
        rate_line = self.env['conversion.fee.rate.line'].search([('rate_id', '=', self.rate_id)], limit=1)
        if rate_line:
            rate_line.write({
                'rate': self.rate,
                'updated_at': self.submitted_at,
            })
        return {'type': 'ir.actions.act_window_close'}




