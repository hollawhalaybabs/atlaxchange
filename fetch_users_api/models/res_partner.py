from collections import defaultdict
import logging

import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    business_id = fields.Char(string='Business ID', index=True, help="Unique identifier for the business")
    rate_id = fields.Char(string='Rate ID', readonly=True, store=True, help="Rate ID for the partner")
    is_atlax_customer = fields.Boolean(string='Customer', default=False)
    is_email_verified = fields.Boolean(string='Is Email Verified', default=False)
    external_user_id = fields.Char(string='External User ID', index=True, copy=False, help="Unique identifier for the user from the external system")
    business_email = fields.Char(string='Business Email', index=True)
    kyc_status = fields.Char(string='KYC Status')
    role = fields.Char(string='Role', index=True)
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
    atlax_env_source = fields.Selection([
        ('production', 'Production'),
        ('staging', 'Sandbox')
    ], string='Atlax Env', readonly=True, help="Environment source from Atlax API when the customer was fetched.")

    @api.model
    def _clean_text(self, value):
        return " ".join((value or '').split()).strip()

    @api.model
    def _clean_business_id(self, business_id):
        return self._clean_text(business_id)

    @api.model
    def _clean_external_user_id(self, external_user_id):
        return self._clean_text(external_user_id)

    @api.model
    def _user_display_name(self, user_data):
        name = self._clean_text(f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}")
        return name or self._clean_text(user_data.get('business_name')) or self._clean_text(user_data.get('email')) or _('Unknown User')

    @api.model
    def _find_country(self, country_name):
        country_name = self._clean_text(country_name)
        if not country_name:
            return False
        return self.env['res.country'].search([('name', '=', country_name)], limit=1)

    @api.model
    def _normalize_api_user(self, user_data):
        role = self._clean_text(user_data.get('role')).lower()
        business_name = self._clean_text(user_data.get('business_name'))
        business_email = self._clean_text(user_data.get('business_email') or user_data.get('businessEmail'))
        country = self._find_country(user_data.get('business_country'))
        return {
            'name': self._user_display_name(user_data),
            'email': self._clean_text(user_data.get('email')),
            'phone': self._clean_text(user_data.get('business_phone') or user_data.get('phone')),
            'street': self._clean_text(user_data.get('business_address')),
            'country_id': country.id if country else False,
            'business_id': self._clean_business_id(user_data.get('business_id')),
            'business_name': business_name,
            'business_email': business_email,
            'kyc_status': self._clean_text(user_data.get('kyc_status')),
            'role': role,
            'external_user_id': self._clean_external_user_id(user_data.get('user_id')),
            'is_email_verified': bool(user_data.get('is_email_verified', False)),
        }

    @api.model
    def _prune_partner_vals(self, vals, force_keys=None):
        force_keys = set(force_keys or [])
        cleaned_vals = {}
        for key, value in vals.items():
            if key in force_keys or value not in (False, None, ''):
                cleaned_vals[key] = value
        return cleaned_vals

    @api.model
    def get_partners_by_business_id(self, business_id):
        business_id = self._clean_business_id(business_id)
        if not business_id:
            return self.env['res.partner']
        return self.with_context(active_test=False).search([
            ('business_id', '=', business_id),
        ], order='create_date asc, id asc')

    @api.model
    def _find_partner_by_external_user_id(self, external_user_id, business_id=None):
        external_user_id = self._clean_external_user_id(external_user_id)
        business_id = self._clean_business_id(business_id)
        if not external_user_id:
            return self.env['res.partner']

        domain = [('external_user_id', '=', external_user_id)]
        if business_id:
            domain.append(('business_id', '=', business_id))

        partner = self.with_context(active_test=False).search(domain, order='parent_id asc, create_date asc, id asc', limit=1)
        if partner or not business_id:
            return partner

        return self.with_context(active_test=False).search([
            ('external_user_id', '=', external_user_id),
        ], order='parent_id asc, create_date asc, id asc', limit=1)

    @api.model
    def _find_partner_by_email(self, email, business_id=None):
        email = self._clean_text(email)
        business_id = self._clean_business_id(business_id)
        if not email:
            return self.env['res.partner']

        domain = [('email', '=', email)]
        if business_id:
            domain.append(('business_id', '=', business_id))

        partner = self.with_context(active_test=False).search(domain, order='parent_id asc, create_date asc, id asc', limit=1)
        if partner or not business_id:
            return partner

        return self.with_context(active_test=False).search([
            ('email', '=', email),
        ], order='parent_id asc, create_date asc, id asc', limit=1)

    @api.model
    def _get_business_admin_user(self, users):
        for user_data in users:
            if self._clean_text(user_data.get('role')).lower() == 'business-admin':
                return user_data
        return False

    @api.model
    def resolve_main_partner_for_business(self, business_id, users=None):
        users = users or []
        business_partners = self.get_partners_by_business_id(business_id)
        admin_user = self._get_business_admin_user(users)
        if admin_user:
            admin_partner = self._find_partner_by_external_user_id(admin_user.get('user_id'), business_id)
            if admin_partner:
                return admin_partner
        return business_partners[:1]

    @api.model
    def _prepare_main_partner_vals(self, normalized_user, env_source=None):
        business_name = normalized_user.get('business_name') or normalized_user.get('name') or normalized_user.get('business_id')
        return {
            'name': business_name,
            'email': normalized_user.get('business_email') or normalized_user.get('email'),
            'phone': normalized_user.get('phone'),
            'street': normalized_user.get('street'),
            'country_id': normalized_user.get('country_id'),
            'company_type': 'company',
            'is_company': True,
            'parent_id': False,
            'company_name': False,
            'business_id': normalized_user.get('business_id'),
            'business_email': normalized_user.get('business_email') or normalized_user.get('email'),
            'kyc_status': normalized_user.get('kyc_status'),
            'role': normalized_user.get('role'),
            'external_user_id': normalized_user.get('external_user_id'),
            'is_email_verified': normalized_user.get('is_email_verified'),
            'is_atlax_customer': True,
            'atlax_env_source': env_source,
        }

    @api.model
    def _prepare_child_contact_vals(self, normalized_user, main_partner, env_source=None):
        return {
            'name': normalized_user.get('name'),
            'email': normalized_user.get('email'),
            'phone': normalized_user.get('phone'),
            'street': normalized_user.get('street'),
            'country_id': normalized_user.get('country_id'),
            'company_type': 'person',
            'is_company': False,
            'parent_id': main_partner.id,
            'company_name': main_partner.name,
            'business_id': normalized_user.get('business_id'),
            'business_email': normalized_user.get('business_email') or main_partner.business_email,
            'kyc_status': normalized_user.get('kyc_status'),
            'role': normalized_user.get('role'),
            'external_user_id': normalized_user.get('external_user_id'),
            'is_email_verified': normalized_user.get('is_email_verified'),
            'is_atlax_customer': False,
            'atlax_env_source': env_source,
            'active': True,
        }

    @api.model
    def _should_sync_partner_ledgers(self, partner):
        partner.ensure_one()
        return bool(partner.is_atlax_customer and partner.business_id)

    @api.model
    def _merge_duplicate_child_contacts(self, main_partner, contacts):
        duplicate_map = defaultdict(list)
        for contact in contacts.sorted(lambda partner: (partner.create_date or fields.Datetime.now(), partner.id)):
            user_key = self._clean_external_user_id(contact.external_user_id)
            if user_key:
                duplicate_map[user_key].append(contact)

        for duplicate_contacts in duplicate_map.values():
            if len(duplicate_contacts) < 2:
                continue

            keeper = duplicate_contacts[0]
            for duplicate in duplicate_contacts[1:]:
                merged_vals = {}
                if not keeper.email and duplicate.email:
                    merged_vals['email'] = duplicate.email
                if not keeper.phone and duplicate.phone:
                    merged_vals['phone'] = duplicate.phone
                if not keeper.role and duplicate.role:
                    merged_vals['role'] = duplicate.role
                if not keeper.business_email and duplicate.business_email:
                    merged_vals['business_email'] = duplicate.business_email
                if not keeper.kyc_status and duplicate.kyc_status:
                    merged_vals['kyc_status'] = duplicate.kyc_status
                if merged_vals:
                    keeper.write(merged_vals)

                duplicate.write({
                    'parent_id': main_partner.id,
                    'company_type': 'person',
                    'is_company': False,
                    'company_name': main_partner.name,
                    'is_atlax_customer': False,
                    'active': False,
                })

    @api.model
    def migrate_duplicate_business_partners(self, main_partner, business_partners=None):
        business_partners = business_partners or self.get_partners_by_business_id(main_partner.business_id)
        duplicates = business_partners - main_partner
        for partner in duplicates:
            partner.write({
                'parent_id': main_partner.id,
                'company_type': 'person',
                'is_company': False,
                'company_name': main_partner.name,
                'is_atlax_customer': False,
                'active': True,
            })

        self._merge_duplicate_child_contacts(main_partner, duplicates)
        return duplicates

    @api.model
    def find_or_create_update_sub_contact(self, user_data, main_partner, env_source=None):
        normalized_user = self._normalize_api_user(user_data)
        business_id = normalized_user.get('business_id')
        contact = self._find_partner_by_external_user_id(normalized_user.get('external_user_id'), business_id)
        if not contact:
            contact = self._find_partner_by_email(normalized_user.get('email'), business_id)

        child_vals = self._prepare_child_contact_vals(normalized_user, main_partner, env_source=env_source)
        if contact:
            contact.write(self._prune_partner_vals(child_vals, force_keys={'parent_id', 'company_type', 'is_company', 'company_name', 'is_atlax_customer', 'active'}))
            return contact

        return self.create(child_vals)

    @api.model
    def _sync_user_ledgers_from_payload(self, partner, user_data):
        if not self._should_sync_partner_ledgers(partner):
            return

        ledgers = user_data.get('ledgers', [])
        if not isinstance(ledgers, list):
            return

        for ledger in ledgers:
            currency_name = ledger.get('currency_name')
            balance = (ledger.get('balance') or 0) / 100
            wallet_id = ledger.get('id')

            currency = self.env['supported.currency'].search([
                '|',
                ('name', '=', currency_name),
                ('currency_code', '=', currency_name)
            ], limit=1)
            if not currency:
                _logger.warning(f"Currency not found for ledger: {ledger}. Skipping ledger.")
                continue

            if hasattr(currency, 'status') and not currency.status:
                currency.status = True

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

    @api.model
    def _sync_user_without_business(self, user_data, env_source=None):
        normalized_user = self._normalize_api_user(user_data)
        partner = self._find_partner_by_external_user_id(normalized_user.get('external_user_id'))
        if not partner:
            partner = self._find_partner_by_email(normalized_user.get('email'))

        vals = {
            'name': normalized_user.get('name'),
            'email': normalized_user.get('email'),
            'phone': normalized_user.get('phone'),
            'street': normalized_user.get('street'),
            'country_id': normalized_user.get('country_id'),
            'company_type': 'person',
            'is_company': False,
            'business_email': normalized_user.get('business_email'),
            'kyc_status': normalized_user.get('kyc_status'),
            'role': normalized_user.get('role'),
            'external_user_id': normalized_user.get('external_user_id'),
            'is_email_verified': normalized_user.get('is_email_verified'),
            'is_atlax_customer': True,
            'atlax_env_source': env_source,
        }
        if partner:
            partner.write(self._prune_partner_vals(vals, force_keys={'company_type', 'is_company', 'is_atlax_customer'}))
        else:
            partner = self.create(vals)

        self._sync_user_ledgers_from_payload(partner, user_data)
        return partner

    @api.model
    def _sync_business_user_group(self, users, env_source=None):
        users = users or []
        if not users:
            return self.env['res.partner']

        normalized_users = [self._normalize_api_user(user_data) for user_data in users]
        business_id = normalized_users[0].get('business_id')
        if not business_id:
            return self.env['res.partner']

        admin_user = self._get_business_admin_user(users)
        normalized_main_user = self._normalize_api_user(admin_user or users[0])
        existing_partners = self.get_partners_by_business_id(business_id)
        main_partner = self.resolve_main_partner_for_business(business_id, users=users)

        main_vals = self._prepare_main_partner_vals(normalized_main_user, env_source=env_source)
        if main_partner:
            main_partner.write(self._prune_partner_vals(main_vals, force_keys={'parent_id', 'company_type', 'is_company', 'company_name', 'is_atlax_customer'}))
        else:
            main_partner = self.create(main_vals)

        # Promote the chosen parent first, then relink the remaining partners under it.
        self.migrate_duplicate_business_partners(main_partner, existing_partners | main_partner)

        main_user_id = self._clean_external_user_id(main_partner.external_user_id)
        synced_contacts = self.env['res.partner']
        for user_data, normalized_user in zip(users, normalized_users):
            external_user_id = normalized_user.get('external_user_id')
            if external_user_id and external_user_id == main_user_id:
                self._sync_user_ledgers_from_payload(main_partner, user_data)
                continue

            contact = self.find_or_create_update_sub_contact(user_data, main_partner, env_source=env_source)
            self._sync_user_ledgers_from_payload(contact, user_data)
            synced_contacts |= contact

        self._merge_duplicate_child_contacts(main_partner, (existing_partners | synced_contacts) - main_partner)
        return main_partner | synced_contacts

    @api.model
    def cleanup_duplicate_business_partners(self, business_ids=None):
        if business_ids is None:
            business_ids = self.with_context(active_test=False).search([
                ('business_id', '!=', False),
            ]).mapped('business_id')

        cleaned_businesses = 0
        relinked_partners = 0
        for business_id in filter(None, map(self._clean_business_id, business_ids)):
            partners = self.get_partners_by_business_id(business_id)
            if not partners:
                continue

            main_partner = self.resolve_main_partner_for_business(business_id)
            if not main_partner:
                continue

            main_partner.write({
                'parent_id': False,
                'company_type': 'company',
                'is_company': True,
                'is_atlax_customer': True,
            })
            relinked_partners += len(self.migrate_duplicate_business_partners(main_partner, partners))
            cleaned_businesses += 1

        return {
            'cleaned_businesses': cleaned_businesses,
            'relinked_partners': relinked_partners,
        }

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
        client = self.env['atlax.api.client']
        url = client.url(f"/v1/business/payment-settings/{self.business_id}")
        headers = client.build_headers()
        if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))
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

    def action_noop(self):
        """A no-op action used for stat badges (click does nothing)."""
        return True

    def action_refresh_balance(self):
        """Refresh this partner's ledger balances from the API and fetch supported currencies."""
        self.ensure_one()
        if not self._should_sync_partner_ledgers(self):
            raise UserError(_("Only Atlax customers with a Business ID can have partner ledgers refreshed."))

        client = self.env['atlax.api.client']
        cfg = client.get_api_config()
        url = client.url('/v1/users')
        headers = client.build_headers()
        if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))
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
        # Mark partner with current env source
        self.atlax_env_source = cfg.get('env')
        return True

    def action_kyc_verification(self):
        """Patch KYC verification for this partner's business_id."""
        self.ensure_one()
        if not self.business_id:
            raise UserError(_("Business ID is required for KYC verification."))
        client = self.env['atlax.api.client']
        url = client.url(f"/v1/admin/business-kyc/{self.business_id}")
        headers = client.build_headers()
        if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))
        # You may need to adjust the payload as per your API requirements
        payload = {"kyc_verified": True}
        response = requests.patch(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise UserError(_("Failed to update KYC verification: %s") % response.text)
        return True

    def action_create_transaction_fee(self):
        """Open wizard to create a transaction fee for this Atlax customer."""
        self.ensure_one()
        if not self.is_atlax_customer:
            raise UserError(_("Only Atlax customers can have transaction fees."))
        if not self.business_id:
            raise UserError(_("This customer does not have a Business ID set."))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'create.transaction.fee.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
            },
        }