from odoo import models, fields, api
import requests
import logging

_logger = logging.getLogger(__name__)

# fetch_users_audit
class FetchUsersAudit(models.Model):
    _name = 'fetch.users.audit'
    _description = 'Fetch Users Audit Log'
    _order = 'fetch_time desc'

    fetch_time = fields.Datetime(string='Fetch Time', default=fields.Datetime.now, readonly=True)
    fetched_count = fields.Integer(string='Fetched Users Count', readonly=True)
    user_id = fields.Many2one('res.users', string='Fetched By', default=lambda self: self.env.user)

class FetchUsers(models.Model):
    _name = 'fetch.users'
    _description = 'Fetch Users from API and Create Customers'

    @api.model
    def fetch_and_create_users(self):
        """Fetch users from the external API and create/update customers and ledgers."""
        client = self.env['atlax.api.client']
        cfg = client.get_api_config()
        url = client.url('/v1/users')
        headers = client.build_headers()
        if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
            _logger.error("API key or secret is missing. Configure env or system parameters.")
            return

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                _logger.error(f"Failed to fetch users from API. Status Code: {response.status_code}, Response: {response.text}")
                return

            users = response.json().get("data", [])
            _logger.info(f"Fetched raw user data: {users}")
            fetched_count = 0

            for user in users:
                try:
                    is_company = bool(user.get('business_name'))
                    partner_vals = {
                        'name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                        'email': user.get('email', ''),
                        'phone': user.get('business_phone', ''),
                        'street': user.get('business_address', ''),
                        'country_id': self.env['res.country'].search([('name', '=', user.get('business_country', ''))], limit=1).id,
                        'is_company': False,
                        'company_name': user.get('business_name', '') if is_company else '',
                        'business_id': user.get('business_id', ''),
                        'is_email_verified': user.get('is_email_verified', False),
                        'external_user_id': user.get('user_id', ''),
                        'is_atlax_customer': True,
                    }
                    partner = self.env['res.partner'].search([('email', '=', user.get('email', ''))], limit=1)
                    if not partner:
                        partner = self.env['res.partner'].create({**partner_vals, 'atlax_env_source': cfg.get('env')})
                    else:
                        vals = {**partner_vals}
                        if not partner.atlax_env_source:
                            vals['atlax_env_source'] = cfg.get('env')
                        partner.write(vals)

                    # Process ledgers
                    ledgers = user.get('ledgers', [])
                    if not isinstance(ledgers, list):
                        ledgers = []

                    for ledger in ledgers:
                        currency_name = ledger.get('currency_name')
                        balance = ledger.get('balance', 0) / 100
                        wallet_id = ledger.get('id')

                        # Try to find supported.currency by currency_name or code
                        currency = self.env['supported.currency'].search([
                            '|',
                            ('name', '=', currency_name),
                            ('currency_code', '=', currency_name)
                        ], limit=1)
                        if not currency:
                            _logger.warning(f"Currency not found for ledger: {ledger}. Skipping ledger.")
                            continue

                        # Reactivate the currency if it exists but is inactive
                        if hasattr(currency, 'status') and not currency.status:
                            currency.status = True
                            _logger.info(f"Reactivated inactive currency: {currency.name}")

                        # Create or update account.ledger for this partner and currency
                        existing_ledger = self.env['account.ledger'].search([
                            ('partner_id', '=', partner.id),
                            ('currency_id', '=', currency.id)
                        ], limit=1)

                        if existing_ledger:
                            existing_ledger.write({
                                'balance': balance,
                                'wallet_id': wallet_id,
                            })
                        else:
                            self.env['account.ledger'].create({
                                'partner_id': partner.id,
                                'currency_id': currency.id,
                                'wallet_id': wallet_id,
                                'balance': balance,
                            })

                except Exception as e:
                    self.env.cr.rollback()
                    _logger.error(f"Failed to process user {user.get('email')}: {str(e)}")
                    continue

            # Log the fetch operation
            self.env['fetch.users.audit'].create({
                'fetched_count': fetched_count,
                'fetch_time': fields.Datetime.now(),
                'user_id': self.env.user.id,
            })

        except requests.exceptions.RequestException as e:
            _logger.error(f"Failed to connect to the API: {str(e)}")



