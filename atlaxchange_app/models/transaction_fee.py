import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TransactionFee(models.Model):
    _name = 'transaction.fee'
    _description = 'Transaction Fee'
    _order = 'id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    partner_id = fields.Many2one('res.partner', string='Partner', compute='_compute_partner_id', store=True)
    business_id = fields.Char(string='Business ID')
    user_id = fields.Char(string='User UUID')
    fee_line_ids = fields.One2many('transaction.fee.line', 'transaction_fee_id', string='Fee Lines')

    @api.depends('partner_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.partner_id:
                rec.display_name = "%s - Transaction Fees" % rec.partner_id.display_name
            else:
                rec.display_name = _("Default Transaction Fees")

    @api.depends('business_id', 'user_id')
    def _compute_partner_id(self):
        for rec in self:
            partner = False
            if rec.business_id:
                partner = self.env['res.partner'].search([('business_id', '=', rec.business_id)], limit=1)
            elif rec.user_id:
                partner = self.env['res.partner'].search([('external_user_id', '=', rec.user_id)], limit=1)
            rec.partner_id = partner

    def _sync_single_fee_record(self, rec):
        """Create or update TransactionFee and TransactionFeeLine from a single API record."""
        self.ensure_one() if self else None  # safe in single-record flows

        currency_code = rec.get('currency_code')
        currency = self.env['supported.currency'].search([('currency_code', '=', currency_code)], limit=1)
        if not currency:
            _logger.warning(
                "Currency code %s not found. Skipping fee record %s.",
                currency_code,
                rec.get('fee_id'),
            )
            return

        # Find related partner
        partner = None
        if rec.get('business_id'):
            partner = self.env['res.partner'].search([('business_id', '=', rec.get('business_id'))], limit=1)
        elif rec.get('user_id'):
            partner = self.env['res.partner'].search([('external_user_id', '=', rec.get('user_id'))], limit=1)

        # Parent transaction.fee record
        fee_parent = self.search([
            ('partner_id', '=', partner.id if partner else False),
            ('business_id', '=', rec.get('business_id')),
            ('user_id', '=', rec.get('user_id')),
        ], limit=1)
        if not fee_parent:
            fee_parent = self.create({
                'partner_id': partner.id if partner else False,
                'business_id': rec.get('business_id'),
                'user_id': rec.get('user_id'),
            })

        line_vals = {
            'currency_id': rec.get('currency_id'),
            'currency_code': currency.id,
            'transfer_direction': rec.get('transfer_direction'),
            'fee_id': rec.get('fee_id'),
            # API sends minor units – convert to full unit
            'fee': rec.get('fee', 0) / 100 if rec.get('fee') is not None else 0,
            'percentage': rec.get('percentage', 0),
            'max_fee': rec.get('max_fee', 0),
            'type': rec.get('type') if rec.get('type') in ['fixed', 'percent'] else False,
            'transaction_fee_id': fee_parent.id,
        }

        fee_line = self.env['transaction.fee.line'].search([
            ('transaction_fee_id', '=', fee_parent.id),
            ('fee_id', '=', rec.get('fee_id')),
        ], limit=1)
        if fee_line:
            fee_line.write(line_vals)
        else:
            self.env['transaction.fee.line'].create(line_vals)

    def fetch_transaction_fees(self):
        """Fetch transaction fees from external API and update/create fee records."""
        client = self.env['atlax.api.client']
        url = client.url('/v1/admin/fees')
        headers = client.build_headers()
        if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
            _logger.error("API key or secret is missing. Configure env or system parameters.")
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))

        try:
            response = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            _logger.exception("Error while calling Atlax /admin/fees API: %s", e)
            raise UserError(_("Failed to fetch transaction fees due to a network error. Please try again."))

        if response.status_code != 200:
            raise UserError(_("Failed to fetch transaction fees: %s") % response.text)

        data = response.json().get('data', [])
        for rec in data:
            # use a new recordset (self.env['transaction.fee']) to avoid depends on current recordset
            self.env['transaction.fee']._sync_single_fee_record(rec)

    @api.model
    def create_transaction_fee_for_business(self, business_id, currency_code, fee,
                                            transfer_direction, fee_type=None):
        """
        Create a transaction fee for a business via the external API and sync Odoo records.

        Endpoint: POST /fees
        Body:
        {
          "business_id": "...",        # required
          "currency_code": "...",      # required
          "fee": 1200,                 # required (int, minor units e.g. kobo/cents)
          "type": "fixed|percent",     # optional
          "transfer_direction": "...", # required: debit|credit
        }
        """
        # Validation
        if not business_id:
            raise UserError(_("Business ID is required to create a transaction fee."))
        if not currency_code:
            raise UserError(_("Currency code is required to create a transaction fee."))
        if transfer_direction not in ('debit', 'credit'):
            raise UserError(_("Transfer direction must be 'debit' or 'credit'."))

        try:
            fee_value = float(fee)
        except (TypeError, ValueError):
            raise UserError(_("Fee must be a number."))
        if fee_value < 0:
            raise UserError(_("Fee must be a positive amount."))

        # Convert to minor units (int64 expected by API), e.g. 0.5 -> 50, 12 -> 1200
        fee_minor = int(round(fee_value * 100))

        payload = {
            "business_id": business_id,
            "currency_code": currency_code,
            "fee": fee_minor,
            "transfer_direction": transfer_direction,
        }
        if fee_type:
            payload["type"] = fee_type

        client = self.env['atlax.api.client']
        url = client.url('/v1/fees')
        headers = client.build_headers()
        if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
            _logger.error("API key or secret is missing. Configure env or system parameters.")
            raise UserError(_("API key or secret is missing. Configure env or system parameters."))

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            _logger.exception("Error while calling Atlax /fees API: %s", e)
            raise UserError(_("Failed to create transaction fee due to a network error. Please try again."))

        if response.status_code not in (200, 201):
            _logger.error(
                "Failed to create transaction fee. Status: %s, Response: %s",
                response.status_code,
                response.text,
            )
            raise UserError(_("Failed to create transaction fee: %s") % response.text)

        resp_json = response.json()
        recs = resp_json.get('data') or []
        if isinstance(recs, dict):
            recs = [recs]

        for rec in recs:
            self.env['transaction.fee']._sync_single_fee_record(rec)

        return True

    def action_open_update_fee_wizard(self):
        """Open the wizard to update a specific transaction fee line."""
        self.ensure_one()
        fee_line_id = self.fee_line_ids[:1].id if len(self.fee_line_ids) == 1 else False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'update.transaction.fee.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_fee_line_id': fee_line_id,
            },
        }


class TransactionFeeLine(models.Model):
    _name = 'transaction.fee.line'
    _description = 'Transaction Fee Line'
    _order = 'id desc'
    _rec_name = 'fee_id'

    transaction_fee_id = fields.Many2one('transaction.fee', string='Transaction Fee', ondelete='cascade', required=True)
    currency_id = fields.Char(string='Currency UUID')
    currency_code = fields.Many2one('supported.currency', string='Currency', required=True)
    transfer_direction = fields.Selection([
        ('debit', 'Debit'),
        ('credit', 'Credit')
    ], string='Transfer Direction', required=True)
    fee_id = fields.Char(string='Fee UUID', required=True)
    fee = fields.Float(string='Fee')
    percentage = fields.Float(string='Percentage')
    max_fee = fields.Float(string='Max Fee')
    type = fields.Selection([
        ('fixed', 'Fixed'),
        ('percent', 'Percent')
    ], string='Fee Type')

