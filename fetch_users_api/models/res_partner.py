from odoo import models, fields, api, _
import requests
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    business_id = fields.Char(string='Business ID', help="Unique identifier for the business")
    rate_id = fields.Char(string='Rate ID', readonly=True, store=True, help="Rate ID for the partner")
    is_atlax_customer = fields.Boolean(string='Customer', default=False)
    is_email_verified = fields.Boolean(string='Is Email Verified', default=False)
    external_user_id = fields.Char(string='External User ID', help="Unique identifier for the user from the external system")
    ledger_ids = fields.One2many('account.ledger', 'partner_id', string='Ledgers')
    partner_ledger_ids = fields.One2many(
        'atlaxchange.ledger', 
        compute='_compute_partner_ledger_ids', 
        string='Partner Ledgers',
        search='_search_partner_ledger_ids'
    )
    partner_ledger_count = fields.Integer(
        string='Ledger Count', 
        compute='_compute_partner_ledger_count'
    )
    payment_settings_ids = fields.One2many(
        'business.payment.settings', 'partner_id', string='Business Payment Settings'
    )

    @api.depends('name', 'company_name')
    def _compute_partner_ledger_ids(self):
        for partner in self:
            # Search for related ledger records
            ledger_records = self.env['atlaxchange.ledger'].search([
                '|',
                ('customer_name', '=', partner.name),
                ('customer_name', '=', partner.company_name)
            ])
            # Assign the IDs of the related records using the (6, 0, [ids]) format
            partner.partner_ledger_ids = [(6, 0, ledger_records.ids)]

    @api.depends('partner_ledger_ids')
    def _compute_partner_ledger_count(self):
        for partner in self:
            partner.partner_ledger_count = len(partner.partner_ledger_ids)

    @api.model
    def _search_partner_ledger_ids(self, operator, value):
        # Search for partners based on related ledger records
        ledger_partners = self.env['atlaxchange.ledger'].search([('id', operator, value)]).mapped('partner_id.id')
        return [('id', 'in', ledger_partners)]

    def action_open_partner_ledgers(self):
        """Open the ledger records for this partner."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Partner Ledgers',
            'res_model': 'atlaxchange.ledger',
            'view_mode': 'tree,form',
            'domain': [
                '|',
                ('customer_name', '=', self.name),
                ('customer_name', '=', self.company_name)
            ],
            'context': {'default_customer_name': self.name},
        }

    def action_fetch_payment_settings(self):
        """Fetch payment settings from external API and update/create business.payment.settings records."""
        self.ensure_one()
        if not self.business_id:
            raise UserError(_("Business ID is required to fetch payment settings."))

        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        url = f"https://api.atlaxchange.com/api/v1/business/payment-settings/{self.business_id}"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise UserError(_("Failed to fetch payment settings: %s") % response.text)

        data = response.json().get('data', {})
        if not data:
            raise UserError(_("No payment settings data received."))

        # Handle IP addresses (comma-separated string to many2many)
        ip_addresses = [ip.strip() for ip in data.get('ip_address', '').split(',') if ip.strip()]
        ip_address_ids = []
        for ip in ip_addresses:
            ip_rec = self.env['business.ip.address'].search([('name', '=', ip)], limit=1)
            if not ip_rec:
                ip_rec = self.env['business.ip.address'].create({'name': ip})
            ip_address_ids.append(ip_rec.id)

        # Handle allowed_wallets and payout_currencies (currency_code to many2many)
        allowed_wallets = self.env['supported.currency'].search([('currency_code', 'in', data.get('allowed_wallets', []))])
        payout_currencies = self.env['supported.currency'].search([('currency_code', 'in', data.get('payout_currencies', []))])

        # Update or create the business.payment.settings record
        vals = {
            'partner_id': self.id,
            'business_id': data.get('business_id'),
            'can_make_transfer': data.get('can_make_transfer', False),
            'ip_address_ids': [(6, 0, ip_address_ids)],
            'allowed_wallets': [(6, 0, allowed_wallets.ids)],
            'payout_currencies': [(6, 0, payout_currencies.ids)],
        }
        existing = self.env['business.payment.settings'].search([
            ('partner_id', '=', self.id),
            ('business_id', '=', data.get('business_id'))
        ], limit=1)
        if existing:
            existing.write(vals)
        else:
            self.env['business.payment.settings'].create(vals)
        return True

    def button_fetch_payment_settings(self):
        """Button to fetch payment settings, can be used in the form view."""
        return self.action_fetch_payment_settings()

    def action_refresh_balance(self):
        """Refresh this partner's ledger balances from the API and fetch supported currencies."""
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        url = "https://api.atlaxchange.com/api/v1/users"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise UserError(_("Failed to fetch users: %s") % response.text)

        users = response.json().get("data", [])
        matched_user = None
        for user in users:
            if user.get("business_id") == self.business_id:
                matched_user = user
                break

        if not matched_user:
            raise UserError(_("No user found with this Business ID."))

        ledgers = matched_user.get("ledgers", [])
        for ledger in ledgers:
            wallet_id = ledger.get("id")
            currency_name = ledger.get("currency_name")
            balance = ledger.get("balance", 0) / 100

            currency = self.env['supported.currency'].search([
                '|',
                ('name', '=', currency_name),
                ('currency_code', '=', currency_name)
            ], limit=1)
            if not currency:
                _logger.warning(f"Currency not found for ledger: {ledger}. Skipping ledger.")
                continue

            existing_ledger = self.env['account.ledger'].search([
                ('partner_id', '=', self.id),
                ('wallet_id', '=', wallet_id),
                ('currency_id', '=', currency.id)
            ], limit=1)

            if existing_ledger:
                existing_ledger.write({
                    'balance': balance,
                })
            else:
                self.env['account.ledger'].create({
                    'partner_id': self.id,
                    'currency_id': currency.id,
                    'wallet_id': wallet_id,
                    'balance': balance,
                })

        # Also refresh supported currencies
        self.env['supported.currency'].fetch_supported_currencies()
        return True

    def action_kyc_verification(self):
        """Patch KYC verification for this partner's business_id."""
        self.ensure_one()
        if not self.business_id:
            raise UserError(_("Business ID is required for KYC verification."))

        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        url = f"https://api.atlaxchange.com/api/v1/admin/{self.business_id}"
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        # You may need to adjust the payload as per your API requirements
        payload = {"kyc_verified": True}
        response = requests.patch(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to update KYC verification: %s") % response.text)
        return True