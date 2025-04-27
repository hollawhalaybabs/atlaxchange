# -*- coding: utf-8 -*-
from odoo import models, fields, api
import requests
from datetime import datetime
from requests.exceptions import ConnectTimeout, ReadTimeout
import logging
from odoo.exceptions import UserError

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
    _rec_name = 'transaction_reference'

    datetime = fields.Datetime(string='Date')
    transaction_reference = fields.Char(string='Reference', index=True)
    bank = fields.Char(string='Bank')
    beneficiary = fields.Char(string='Beneficiary')
    customer_name = fields.Char(string='Customer Name', store=True)
    wallet = fields.Many2one('supported.currency', string='Wallet')
    amount = fields.Float(string='Amount')
    fee = fields.Float(string='Fee')
    type = fields.Selection([
        ('debit', 'Debit'),
        ('credit', 'Credit')
    ], string='Type')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed')
    ], string='Status', default='pending')
    partner_id = fields.Many2one('res.partner', string='Partner')

    @api.model
    def get_dashboard_data(self):
        """Fetch data for the dashboard."""
        try:
            total_credit = sum(self.search([('type', '=', 'credit')]).mapped('amount')) or 0
            total_debit = sum(self.search([('type', '=', 'debit')]).mapped('amount')) or 0
            status_counts = {
                status: self.search_count([('status', '=', status)]) or 0
                for status in ['pending', 'success', 'failed', 'reversed']
            }

            # Aggregate customer data
            query = """
                SELECT customer_name, COUNT(*) as txn_count, SUM(amount) as total_amount
                FROM atlaxchange_ledger
                WHERE customer_name IS NOT NULL
                GROUP BY customer_name
            """
            self.env.cr.execute(query)
            customer_summary = self.env.cr.dictfetchall()

            return {
                'credit': total_credit,
                'debit': total_debit,
                'status_counts': status_counts,
                'customers': customer_summary or [],
            }
        except Exception as e:
            _logger.error(f"Error fetching dashboard data: {str(e)}")
            return {
                'credit': 0,
                'debit': 0,
                'status_counts': {'pending': 0, 'success': 0, 'failed': 0, 'reversed': 0},
                'customers': [],
            }

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
            _logger.error("API key or secret is missing. Set them in System Parameters.")
            return

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        next_cursor = None
        fetched_count = 0  # Track the number of transactions fetched
        existing_references = set(self.search([]).mapped('transaction_reference'))  # Cache existing references

        while True:
            params = {'after': next_cursor} if next_cursor else {}
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code != 200:
                    _logger.error(f"Failed to fetch data from API. Status Code: {response.status_code}, Response: {response.text}")
                    break

                data = response.json()
                transactions = data.get('data', {}).get('transactions', [])
                _logger.info(f"Fetched {len(transactions)} transactions.")

                new_records = []
                for record in transactions:
                    reference = record.get('reference')
                    if reference not in existing_references:
                        # Prepare new record for batch creation
                        created_at = datetime.utcfromtimestamp(record['created_at'])
                        new_records.append({
                            'datetime': created_at,
                            'bank': record['bank_name'],
                            'beneficiary': record['beneficiary_name'],
                            'customer_name': record.get('customer_name', 'N/A'),
                            'transaction_reference': reference,
                            'amount': record['amount'] / 100,  # Divide amount by 100
                            'status': record['status'],
                            'type': record['direction'],
                            'wallet': self.env['supported.currency'].search([('currency_code', '=', record['currency_code'])], limit=1).id,
                            'fee': record['fee'] / 100,
                        })
                        existing_references.add(reference)  # Add to cache to avoid duplicate processing
                        fetched_count += 1

                # Batch create new records
                if new_records:
                    self.create(new_records)
                    _logger.info(f"Created {len(new_records)} new ledger records.")

                # Update the cursor for pagination
                next_cursor = data.get('data', {}).get('cursor', {}).get('after')
                if not next_cursor:
                    break
            except (ConnectTimeout, ReadTimeout):
                _logger.error("Connection to the API timed out.")
                break
            except Exception as e:
                _logger.error(f"An unexpected error occurred: {str(e)}")
                break

        # Log the fetch operation in the audit model
        self.env['fetch.ledger.audit'].create({
            'fetched_count': fetched_count,
            'fetch_time': fields.Datetime.now(),
            'user_id': self.env.user.id,
        })

        _logger.info(f"Successfully fetched {fetched_count} transactions from the API.")



