import os
import re
from urllib.parse import urljoin
from odoo import models


class AtlaxApiClient(models.AbstractModel):
    _name = 'atlax.api.client'
    _description = 'Atlax API Client (env-aware)'

    def _strip_version_suffix(self, base_url: str) -> str:
        base_url = (base_url or '').rstrip('/')
        return re.sub(r"/v\d+$", "", base_url)

    def _get_env(self):
        ICP = self.env['ir.config_parameter'].sudo()
        env = (os.environ.get('ATLAX_ENV') or ICP.get_param('atlax.api.env') or '').strip().lower()
        if env in ('staging', 'production', 'prod'):
            return 'staging' if env == 'staging' else 'production'
        # Default to production if unspecified
        return 'production'

    def _get_base_url(self, env):
        ICP = self.env['ir.config_parameter'].sudo()
        if env == 'staging':
            base_url = (
                os.environ.get('ATLAX_BASE_URL_STAGING')
                or ICP.get_param('atlax.api.base_url.staging')
                or ICP.get_param('atlax.api.base_url')
                or 'https://api.atlaxchange.com/api'
            )
            return self._strip_version_suffix(base_url)
        # production
        base_url = (
            os.environ.get('ATLAX_BASE_URL_PROD')
            or os.environ.get('ATLAX_BASE_URL_PRODUCTION')
            or ICP.get_param('atlax.api.base_url.production')
            or ICP.get_param('atlax.api.base_url')
            or 'https://api.atlaxchange.com/api'
        )
        return self._strip_version_suffix(base_url)

    def _get_credentials(self, env):
        ICP = self.env['ir.config_parameter'].sudo()
        if env == 'staging':
            api_key = (
                os.environ.get('ATLAX_API_KEY_STAGING')
                or ICP.get_param('atlax.api.key.staging')
            )
            api_secret = (
                os.environ.get('ATLAX_API_SECRET_STAGING')
                or ICP.get_param('atlax.api.secret.staging')
            )
        else:
            api_key = (
                os.environ.get('ATLAX_API_KEY_PROD')
                or os.environ.get('ATLAX_API_KEY_PRODUCTION')
                or ICP.get_param('atlax.api.key.production')
                or ICP.get_param('atlax.api.key')
            )
            api_secret = (
                os.environ.get('ATLAX_API_SECRET_PROD')
                or os.environ.get('ATLAX_API_SECRET_PRODUCTION')
                or ICP.get_param('atlax.api.secret.production')
                or ICP.get_param('atlax.api.secret')
            )

        # Backward compatibility fallbacks
        if not api_key:
            api_key = ICP.get_param('fetch_users_api.api_key')
        if not api_secret:
            api_secret = ICP.get_param('fetch_users_api.api_secret')

        return {
            'api_key': api_key,
            'api_secret': api_secret,
        }

    def get_api_config(self):
        env = self._get_env()
        base_url = self._get_base_url(env)
        creds = self._get_credentials(env)
        return {
            'env': env,
            'base_url': base_url.rstrip('/'),
            **creds,
        }

    def url(self, path):
        cfg = self.get_api_config()
        base = cfg['base_url']
        # Ensure single slash and proper join
        path = path if path.startswith('/') else f'/{path}'
        return urljoin(base + '/', path.lstrip('/'))

    def build_headers(self, extra_headers=None):
        cfg = self.get_api_config()
        headers = {
            'Content-Type': 'application/json',
        }
        if cfg.get('api_key'):
            headers['X-API-KEY'] = cfg['api_key']
        if cfg.get('api_secret'):
            headers['X-API-SECRET'] = cfg['api_secret']
        if extra_headers:
            headers.update(extra_headers)
        return headers
