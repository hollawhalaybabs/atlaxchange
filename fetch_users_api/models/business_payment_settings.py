from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests

class BusinessPaymentSettings(models.Model):
    _name = 'business.payment.settings'
    _description = 'Business Payment Settings'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True, ondelete='cascade')
    business_id = fields.Char(string='Business ID', required=True)
    ip_address_ids = fields.Many2many('business.ip.address', string='IP Addresses')
    can_make_transfer = fields.Boolean(string='Can Make Transfer', default=False)
    allowed_wallets = fields.Many2many('supported.currency', 'business_payment_settings_allowed_wallet_rel', 'settings_id', 'currency_id', string='Allowed Wallets')
    payout_currencies = fields.Many2many('supported.currency', 'business_payment_settings_payout_currency_rel', 'settings_id', 'currency_id', string='Payout Currencies')

    @api.depends('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and self.partner_id.business_id:
            self.business_id = self.partner_id.business_id
        else:
            self.business_id = False

    def action_update_payment_settings(self):
        """Update payment settings via external API PATCH request."""
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        url = "https://api.atlaxchange.com/api/v1/business/payment-settings"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        ip_list = ','.join(self.ip_address_ids.mapped('name'))
        allowed_wallets = self.allowed_wallets.mapped('currency_code')
        payout_currencies = self.payout_currencies.mapped('currency_code')
        payload = {
            "business_id": self.business_id,
            "ip_address": ip_list,
            "can_make_transfer": self.can_make_transfer,
            "allowed_wallets": allowed_wallets,
            "payout_currencies": payout_currencies,
        }
        response = requests.patch(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to update payment settings: %s") % response.text)
        return True

class BusinessIpAddress(models.Model):
    _name = 'business.ip.address'
    _description = 'Business IP Address'

    name = fields.Char(string='IP Address', required=True)
    settings_ids = fields.Many2many('business.payment.settings', string='Payment Settings')