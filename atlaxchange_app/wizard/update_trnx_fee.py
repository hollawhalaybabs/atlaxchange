from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests

class UpdateTransactionFeeWizard(models.TransientModel):
    _name = 'update.transaction.fee.wizard'
    _description = 'Update Transaction Fee Wizard'

    partner_id = fields.Many2one('res.partner', string='Partner')
    fee_id = fields.Char(string='Fee ID', readonly=True, store=True)
    fee = fields.Float(string='Conversion Rate', required=True)
    currency_code = fields.Many2one('supported.currency', string='Currency')

    @api.onchange('fee_id', 'partner_id')
    def _onchange_fee_or_partner(self):
        domain = []
        if self.fee_id:
            fee_rec = self.env['transaction.fee'].search([('fee_id', '=', self.fee_id)], limit=1)
        elif self.partner_id:
            fee_rec = self.env['transaction.fee'].search([('partner_id', '=', self.partner_id.id)], limit=1)
        else:
            fee_rec = False
        if fee_rec:
            self.fee_id = fee_rec.fee_id
            self.partner_id = fee_rec.partner_id.id
            self.fee = fee_rec.fee
            self.currency_code = fee_rec.currency_code.id

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
        # Update the transaction.fee record locally
        fee_rec = self.env['transaction.fee'].search([('fee_id', '=', self.fee_id)], limit=1)
        if fee_rec:
            fee_rec.write({'fee': self.fee})
        return {'type': 'ir.actions.act_window_close'}