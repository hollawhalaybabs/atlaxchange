from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging

_logger = logging.getLogger(__name__)

class TransactionFee(models.Model):
    _name = 'transaction.fee'
    _description = 'Transaction Fee'
    _order = 'id desc'
    _rec_name = 'partner_id'

    # amount = fields.Float(string='Amount')
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
    business_id = fields.Char(string='Business ID')
    user_id = fields.Char(string='User UUID')
    partner_id = fields.Many2one('res.partner', string='Partner', compute='_compute_partner_id', store=True)

    @api.depends('business_id', 'user_id')
    def _compute_partner_id(self):
        for rec in self:
            partner = False
            if rec.business_id:
                partner = self.env['res.partner'].search([('business_id', '=', rec.business_id)], limit=1)
            elif rec.user_id:
                partner = self.env['res.partner'].search([('user_id', '=', rec.user_id)], limit=1)
            rec.partner_id = partner

    def fetch_transaction_fees(self):
        """Fetch transaction fees from external API and update/create records."""
        url = "https://api.atlaxchange.com/api/v1/admin/fees"
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')

        if not api_key or not api_secret:
            _logger.error("API key or secret is missing. Set them in System Parameters.")
            raise UserError(_("API key or secret is missing. Set them in System Parameters."))

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise UserError(_("Failed to fetch transaction fees: %s") % response.text)

        data = response.json().get('data', [])
        for rec in data:
            currency = self.env['supported.currency'].search([('currency_code', '=', rec.get('currency_code'))], limit=1)
            if not currency:
                _logger.warning(f"Currency code {rec.get('currency_code')} not found. Skipping fee_id {rec.get('fee_id')}.")
                continue  # Skip this record if currency not found

            vals = {
                # 'amount': rec.get('amount', 0),
                'currency_id': rec.get('currency_id'),
                'currency_code': currency.id,
                'transfer_direction': rec.get('transfer_direction'),
                'fee_id': rec.get('fee_id'),
                'fee': rec.get('fee', 0) / 100 if rec.get('fee') is not None else 0,
                'percentage': rec.get('percentage', 0),
                'max_fee': rec.get('max_fee', 0),
                'type': rec.get('type') if rec.get('type') in ['fixed', 'percent'] else False,
                'business_id': rec.get('business_id'),
                'user_id': rec.get('user_id'),
            }
            fee = self.search([('fee_id', '=', rec.get('fee_id'))], limit=1)
            if fee:
                fee.write(vals)
            else:
                self.create(vals)

    def action_open_update_fee_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'update.transaction.fee.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_fee_id': self.fee_id,
                'default_partner_id': self.partner_id.id,
                'default_fee': self.fee,
                'default_currency_code': self.currency_code.id,
            }
        }