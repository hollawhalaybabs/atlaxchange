import requests
from odoo import models, fields, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class SupportedCurrency(models.Model):
    _name = 'supported.currency'
    _description = 'Supported Currency'
    _order = 'id desc'
    _rec_name = 'currency_code'

    currency_code = fields.Char(string='Currency Code', size=4, required=True, help="Currency Code (ISO 4217)")
    currency_id = fields.Char(string='ID')
    name = fields.Char(string='Currency Name', required=True, help="Full name of the currency")
    symbol = fields.Char(string='Symbol', help="Symbol of the currency (e.g., $)")
    exchanges = fields.Many2many(
        'supported.currency',
        'supported_currency_rel',
        'currency_id',
        'exchange_id',
        string='Target Currencies',
        help="Currencies that can be exchanged with this currency"
    )
    status = fields.Boolean(
        string='Active',
        default=True,
        help="Indicates whether the currency is active"
    )

    def fetch_supported_currencies(self):
        """Fetch supported currencies from the API and update the database."""
        api_url = "https://api.atlaxchange.com/api/v1/currencies"

        # Fetch API key and secret from system parameters
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')

        if not api_key or not api_secret:
            _logger.error("API key or secret is missing. Set them in System Parameters.")
            return

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        try:
            response = requests.get(api_url, headers=headers, timeout=10)
            if response.status_code != 200:
                _logger.error(f"Failed to fetch currencies. Status Code: {response.status_code}, Response: {response.text}")
                return

            data = response.json().get('data', [])
            _logger.info(f"Fetched {len(data)} currencies from the API.")

            for currency in data:
                try:
                    # Update the currency record if it exists
                    existing_currency = self.env['supported.currency'].search([('currency_code', '=', currency['code'])], limit=1)
                    if existing_currency:
                        existing_currency.write({
                            'name': currency['name'],
                            'symbol': currency['symbol'],
                            'status': currency['status'] == 'active',
                        })
                    else:
                        self.env['supported.currency'].create({
                            'currency_code': currency['code'],
                            'name': currency['name'],
                            'symbol': currency['symbol'],
                            'status': currency['status'] == 'active',
                        })
                except Exception as e:
                    _logger.error(f"Failed to process currency {currency.get('code')}: {str(e)}")
                    continue

        except requests.exceptions.RequestException as e:
            _logger.error(f"Failed to connect to the API: {str(e)}")

    def post_new_currency(self):
        """Post a new supported currency to the API."""
        api_url = "https://api.atlaxchange.com/api/v1/currencies"

        # Fetch API key and secret from system parameters
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')

        if not api_key or not api_secret:
            raise ValidationError(_("API key or secret is missing. Set them in System Parameters."))

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        # Prepare the payload for the POST request
        exchanges_codes = ', '.join(self.exchanges.mapped('currency_code'))
        payload = {
            "currency_code": self.currency_code,
            "name": self.name,
            "symbol": self.symbol,
            "exchanges": exchanges_codes,
            "status": "active" if self.status else "inactive"
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=10)
            if response.status_code == 201:
                raise ValidationError(_("Successfully posted new currency: %s") % self.currency_code)
            else:
                raise ValidationError(_("Failed to post new currency. Status Code: %s, Response: %s") % (response.status_code, response.text))
        except requests.exceptions.RequestException as e:
            raise ValidationError(_("Failed to connect to the API: %s") % str(e))

    def action_update_exchanges(self):
        self.ensure_one()
        api_url = f"https://api.atlaxchange.com/api/v1/currencies/{self.currency_code}"
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise ValidationError(_("API key or secret is missing. Set them in System Parameters."))

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }
        exchanges_codes = ', '.join(self.exchanges.mapped('currency_code'))
        payload = {
            "exchanges": exchanges_codes
        }
        try:
            response = requests.patch(api_url, headers=headers, json=payload, timeout=10)
            if response.status_code in (200, 201):
                self.exchanges = [(6, 0, self.exchanges.ids)]
            else:
                raise ValidationError(_("Failed to update exchanges. Status Code: %s, Response: %s") % (response.status_code, response.text))
        except requests.exceptions.RequestException as e:
            raise ValidationError(_("Failed to connect to the API: %s") % str(e))
