from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests

class UpdateTransactionFeeWizard(models.TransientModel):
    _name = 'update.transaction.fee.wizard'
    _description = 'Update Transaction Fee Wizard'
    _rec_name = 'fee_id'

    partner_id = fields.Many2one('res.partner', string='Partner')
    fee_line_id = fields.Many2one('transaction.fee.line', string='Fee Line')
    fee_id = fields.Char(string='Fee ID')
    fee = fields.Float(string='Fee', required=True)
    currency_code = fields.Many2one('supported.currency', string='Currency')

    @api.onchange('fee_line_id')
    def _onchange_fee_line_id(self):
        if self.fee_line_id:
            self.fee_id = self.fee_line_id.fee_id
            self.fee = self.fee_line_id.fee
            self.currency_code = self.fee_line_id.currency_code.id
            self.partner_id = self.fee_line_id.transaction_fee_id.partner_id.id

    def action_update_fee(self):
        self.ensure_one()
        if not self.fee_id:
            raise UserError(_("Fee ID is missing."))
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        url = f"https://api.atlaxchange.com/api/v1/admin/fees/{self.fee_id}"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        payload = {
            "fee": int(self.fee * 100),  # Ensure integer for API
        }
        response = requests.patch(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to update fee: %s") % response.text)
        # Update the transaction.fee.line record locally
        fee_line = self.env['transaction.fee.line'].search([('fee_id', '=', self.fee_id)], limit=1)
        if fee_line:
            fee_line.write({'fee': self.fee})
        return {'type': 'ir.actions.act_window_close'}