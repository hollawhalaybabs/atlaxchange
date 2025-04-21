from odoo import models, fields, api
import requests
import inspect
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

# fetch_users
class FetchUsers(models.Model):
    _name = 'fetch.users'
    _description = 'Fetch Users from API and Create Customers'

    @api.model
    def fetch_and_create_users(self):
        """Fetch users from the external API and create/update customers and ledgers."""
        url = "https://api.atlaxchange.com/api/v1/users"
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
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                if response.status_code == 401:
                    _logger.error("Unauthorized access. Please check your API key and secret.")
                else:
                    _logger.error(f"Failed to fetch users from API. Status Code: {response.status_code}, Response: {response.text}")
                return

            users = response.json().get("data", [])
            _logger.info(f"Fetched {len(users)} users from the API.")
            fetched_count = 0

            # Currency mapping
            currency_mapping = {
                "Nigerian Naira": "NGN",
                "Kenyan Shilling": "KES",
                "Ghana Cedi": "GHS"
            }

            for user in users:
                try:
                    # Determine if the user is a business or an individual
                    is_company = bool(user.get('business_name'))

                    # Create or update partner
                    partner = self.env['res.partner'].search([('email', '=', user['email'])], limit=1)
                    if not partner:
                        partner = self.env['res.partner'].create({
                            'name': f"{user['first_name']} {user['last_name']}",
                            'email': user['email'],
                            'phone': user.get('business_phone', ''),
                            'street': user.get('business_address', ''),
                            'country_id': self.env['res.country'].search([('name', '=', user.get('business_country', ''))], limit=1).id,
                            'is_company': False,
                            'company_name': user.get('business_name', '') if is_company else '',
                            'business_id': user.get('business_id', ''),
                            'is_email_verified': user.get('is_email_verified', False),
                            'external_user_id': user.get('user_id', ''),
                            "is_atlax_customer": True,
                        })

                    # Update existing partner details if necessary
                    else:
                        partner.write({
                            "is_atlax_customer": True,
                        }) 
                        
                    # Create or update user
                    user_obj = self.env['res.users'].search([('login', '=', user['email'])], limit=1)
                    if not user_obj:
                        self.env['res.users'].create({
                            'name': f"{user['first_name']} {user['last_name']}",
                            'login': user['email'],
                            'partner_id': partner.id,
                            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
                        })
                        fetched_count += 1

                    # Process ledgers
                    ledgers = user.get('ledgers', [])
                    if not isinstance(ledgers, list):
                        ledgers = []  # Ensure ledgers is always a list

                    for ledger in ledgers:
                        currency_name = ledger.get('currency_name')
                        currency_code = currency_mapping.get(currency_name, currency_name)  # Map to currency code

                        # Check if the currency exists
                        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
                        if not currency:
                            _logger.warning(f"Currency not found for ledger: {ledger}. Skipping ledger.")
                            continue

                        # Reactivate the currency if it exists but is inactive
                        if not currency.active:
                            currency.active = True
                            _logger.info(f"Reactivated inactive currency: {currency.name}")

                        # Divide the balance by 100
                        balance = ledger.get('balance', 0) / 100
                        wallet_id = ledger.get('id')

                        # Create or update ledger
                        existing_ledger = self.env['account.ledger'].search([
                            ('partner_id', '=', partner.id),
                            ('currency_id', '=', currency.id)
                        ], limit=1)

                        if existing_ledger:
                            existing_ledger.balance = balance
                            existing_ledger.wallet_id = wallet_id
                            # _logger.info(f"Updated ledger for partner {partner.id} with currency {currency.name} to balance {balance}")
                        else:
                            self.env['account.ledger'].create({
                                'partner_id': partner.id,
                                'currency_id': currency.id,
                                'wallet_id': wallet_id,
                                'balance': balance,
                            })
                            # _logger.info(f"Created ledger for partner {partner.id} with currency {currency.name} and balance {balance}")

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
            # _logger.info(f"Successfully fetched and created {fetched_count} users.")

        except requests.exceptions.RequestException as e:
            _logger.error(f"Failed to connect to the API: {str(e)}")



