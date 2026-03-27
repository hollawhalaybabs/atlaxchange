import logging
from collections import defaultdict

import requests
from odoo import models, fields, api

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
            fetched_count = len(users)
            partner_model = self.env['res.partner']
            grouped_users = defaultdict(list)
            standalone_users = []

            for user in users:
                business_id = partner_model._clean_business_id(user.get('business_id'))
                if business_id:
                    grouped_users[business_id].append(user)
                else:
                    standalone_users.append(user)

            for business_id, business_users in grouped_users.items():
                try:
                    partner_model._sync_business_user_group(business_users, env_source=cfg.get('env'))
                except Exception as e:
                    self.env.cr.rollback()
                    _logger.error(f"Failed to process business {business_id}: {str(e)}")

            for user in standalone_users:
                try:
                    partner_model._sync_user_without_business(user, env_source=cfg.get('env'))
                except Exception as e:
                    self.env.cr.rollback()
                    _logger.error(f"Failed to process user {user.get('email')}: {str(e)}")

            # Log the fetch operation
            self.env['fetch.users.audit'].create({
                'fetched_count': fetched_count,
                'fetch_time': fields.Datetime.now(),
                'user_id': self.env.user.id,
            })

        except requests.exceptions.RequestException as e:
            _logger.error(f"Failed to connect to the API: {str(e)}")



