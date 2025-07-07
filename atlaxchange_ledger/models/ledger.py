# -*- coding: utf-8 -*-
from odoo import models, fields, api
import requests
from datetime import datetime
from requests.exceptions import ConnectTimeout, ReadTimeout
import logging
from odoo.exceptions import UserError
import csv
from io import StringIO
from odoo.http import request

_logger = logging.getLogger(__name__)

class FetchLedgerAudit(models.Model):
    _name = 'fetch.ledger.audit'
    _description = 'Fetch Ledger Audit Log'
    _order = 'fetch_time desc'

    fetch_time = fields.Datetime(string='Fetch Time', default=fields.Datetime.now, readonly=True)
    fetched_count = fields.Integer(string='Fetched Transactions Count', readonly=True)
    user_id = fields.Many2one('res.users', string='Fetched By', default=lambda self: self.env.user, readonly=True)

class AtlaxchangeLedger(models.Model):
    _name = 'atlaxchange.ledger'
    _description = 'Atlaxchange Client Ledger History'
    _order = 'id desc'
    _rec_name = 'customer_name'

    datetime = fields.Datetime(string='Date')
    transaction_reference = fields.Char(string='Reference', index=True)
    bank = fields.Char(string='Bank')
    bank_code = fields.Char(string='Bank Code')
    beneficiary = fields.Char(string='Beneficiary')
    customer_name = fields.Char(string='Customer Name', store=True)
    wallet = fields.Many2one('supported.currency', string='Wallet')
    amount = fields.Float(string='Amount', store=True, digits=(16, 2))
    total_amount = fields.Float(string='Dest. Amount', digits=(16, 2))
    fee = fields.Float(string='Fee')
    conversion_rate = fields.Float(string='Rate')
    destination_currency = fields.Many2one('supported.currency', string='Destination Currency')  # updated
    type = fields.Selection([
        ('debit', 'Debit'),
        ('credit', 'Credit')
    ], string='Type')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed')
    ], string='Status', default='pending')
    partner_id = fields.Many2one('res.partner', string='Partner')


    def action_initiate_refund(self):
        """Initiate refund for the current ledger records with type='debit'."""
        # Filter records to ensure they are of type 'debit' and have valid statuses
        valid_ledgers = self.filtered(lambda r: r.type == 'debit' and r.status in ['pending', 'failed'])
        invalid_ledgers = self - valid_ledgers

        # Handle invalid records
        if invalid_ledgers:
            invalid_references = ', '.join(invalid_ledgers.mapped('transaction_reference'))
            raise UserError(
                f"Refund can only be initiated for transactions of type 'debit' with 'pending' or 'failed' status. "
            )

        # Prepare refund records
        refund_records = [
            (0, 0, {
                'ledger_id': record.id,
                'amount': record.amount,
                'reference': f"Refund for transaction {record.transaction_reference}",
            })
            for record in valid_ledgers
        ]

        # Create a refund batch if there are valid records
        if refund_records:
            self.env['atlaxchange.refund'].create({
                'name': 'Refund Batch',
                'refund_line_ids': refund_records,
            })
            _logger.info(f"Refund initiated for {len(refund_records)} transactions.")
        else:
            raise UserError("No valid transactions found for refund.")

    @api.model
    def fetch_ledger_history(self):
        """Fetch ledger history from the external API and update/create records."""
        url = 'https://api.atlaxchange.com/api/v1/transactions/history'
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')

        if not api_key or not api_secret:
            # _logger.error("API key or secret is missing. Set them in System Parameters.")
            return

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        next_cursor = None
        fetched_count = 0

        while True:
            params = {'after': next_cursor} if next_cursor else {}
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code != 200:
                    # _logger.error(f"Failed to fetch data from API. Status Code: {response.status_code}, Response: {response.text}")
                    break

                data = response.json()
                transactions = data.get('data', {}).get('transactions', [])
                # _logger.info(f"Fetched {len(transactions)} transactions.")

                new_records = []
                for record in transactions:
                    reference = record.get('reference')
                    existing = self.search([('transaction_reference', '=', reference)], limit=1)
                    created_at = datetime.utcfromtimestamp(record['created_at'])
                    currency = self.env['supported.currency'].search([('currency_code', '=', record.get('currency_code'))], limit=1)
                    dest_currency = self.env['supported.currency'].search([('currency_code', '=', record.get('destination_currency'))], limit=1)
                    # Ensure status is mapped and defaults to 'pending' if not present or not recognized
                    status = record.get('status', 'pending')
                    if status not in dict(self._fields['status'].selection):
                        status = 'pending'
                    vals = {
                        'datetime': created_at,
                        'bank': record.get('bank_name'),
                        'bank_code': record.get('bank_code'),
                        'beneficiary': record.get('beneficiary_name'),
                        'customer_name': record.get('customer_name', 'N/A'),
                        'transaction_reference': reference,
                        'amount': abs(record.get('amount', 0) / 100),
                        'total_amount': abs(record.get('total_amount', 0) / 100),
                        'fee': record.get('fee', 0) / 100,
                        'conversion_rate': record.get('conversion_rate', 0),
                        'destination_currency': dest_currency.id if dest_currency else False,
                        'status': status,
                        'type': record.get('direction'),
                        'wallet': currency.id if currency else False,
                    }
                    if existing:
                        # Update only the status if record exists
                        existing.write({'status': status})
                    else:
                        new_records.append(vals)
                        fetched_count += 1

                if new_records:
                    self.create(new_records)
                    _logger.info(f"Created {len(new_records)} new ledger records.")

                next_cursor = data.get('data', {}).get('cursor', {}).get('after')
                if not next_cursor:
                    break
            except (ConnectTimeout, ReadTimeout):
                _logger.error("Connection to the API timed out.")
                break
            except Exception as e:
                _logger.error(f"An unexpected error occurred: {str(e)}")
                break

        self.env['fetch.ledger.audit'].create({
            'fetched_count': fetched_count,
            'fetch_time': fields.Datetime.now(),
            'user_id': self.env.user.id,
        })

        _logger.info(f"Successfully fetched {fetched_count} transactions from the API.")

    def export_transaction_report(self):
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Customer', 'Currency', 'Amount', 'Fee', 'Status', 'Date'])
        for rec in self.search([]):
            writer.writerow([
                rec.partner_id.display_name,
                rec.wallet.name if rec.wallet else '',
                rec.amount,
                rec.fee,
                rec.status,
                rec.datetime,
            ])
        output.seek(0)
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'text/csv'),
                ('Content-Disposition', 'attachment; filename="ledger_report.csv"')
            ]
        )
    
    @api.model
    def cron_send_daily_summary(self):
        today = fields.Date.today()
        ledgers = self.search([('datetime', '>=', today)])
        total_volume = sum(ledgers.mapped('amount'))
        total_fee = sum(ledgers.mapped('fee'))
        body = f"Today's volume: {total_volume}\nToday's profit: {total_fee}"
        # Send to group or manager
        users = self.env.ref('base.group_system').users
        for user in users:
            user.partner_id.message_post(body=body, subject="Daily Ledger Summary")



