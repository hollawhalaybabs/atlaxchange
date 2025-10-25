# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import requests
from datetime import datetime
from requests.exceptions import ConnectTimeout, ReadTimeout
import logging
from odoo.exceptions import UserError
import csv
from io import StringIO
from odoo.http import request
import threading
from odoo import SUPERUSER_ID, api as odoo_api, registry as registry_get

_logger = logging.getLogger(__name__)

class AtlaxchangeLedger(models.Model):
    _name = 'atlaxchange.ledger'
    _description = 'Atlaxchange Client Ledger History'
    _order = 'datetime desc'
    _rec_name = 'transaction_reference'
    _inherit = ['mail.thread', 'mail.activity.mixin']

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
    beneficiary_acct = fields.Char(string='Beneficiary Account')
    session_id = fields.Char(string='Session ID')
    error_message = fields.Text(string='Error Message')


    def action_initiate_reprocess(self):
        """Initiate reprocess for the current ledger records with type='debit'."""
        # Filter records to ensure they are of type 'debit' and have valid statuses
        valid_ledgers = self.filtered(lambda r: r.type == 'debit' and r.status in ['processing'])
        invalid_ledgers = self - valid_ledgers

        # Handle invalid records
        if invalid_ledgers:
            invalid_references = ', '.join(invalid_ledgers.mapped('transaction_reference'))
            raise UserError(
                f"Reprocessing can only be initiated for transactions of type 'debit' with 'processing' status. "
            )
        # Prepare reprocess records
        reprocess_records = [
            (0, 0, {
                'reference': record.transaction_reference,
                'customer_name': record.customer_name,
                'wallet': record.wallet.id,
                'amount': record.amount,
                'destination_currency': record.destination_currency.id,
                'total_amount': record.total_amount,
            })
            for record in valid_ledgers
        ]
        # Create a reprocess batch if there are valid records
        if reprocess_records:
            self.env['atlaxchange.reprocess'].create({
                'reprocess_line_ids': reprocess_records,
            })
            _logger.info(f"reprocess initiated for {len(reprocess_records)} transactions.")
        else:
            raise UserError("No valid transactions found for reprocess.")
        
    def action_initiate_reversal(self):
        """Create a atlaxchange.reversal record from selected ledger lines.

        Only ledger records with status == 'failed' are allowed to be reversed.
        """
        if not self:
            raise UserError("No ledger records selected for reversal.")

        # Only allow records that are in 'failed' status
        failed_ledgers = self.filtered(lambda r: r.status == 'failed')
        invalid_ledgers = self - failed_ledgers
        if invalid_ledgers:
            refs = ', '.join(filter(None, invalid_ledgers.mapped('transaction_reference')))
            raise UserError(
                "Reversal can only be initiated for transactions with status 'failed'. "
                "Invalid selection: %s" % (refs or 'No reference')
            )

        reversal_lines = []
        for rec in failed_ledgers:
            ref = getattr(rec, 'transaction_reference', False) or getattr(rec, 'reference', False)
            if not ref:
                continue
            reversal_lines.append((0, 0, {
                'reference': ref,
                'customer_name': rec.customer_name or '',
                'wallet': rec.wallet.id if getattr(rec, 'wallet', False) else False,
                'amount': float(getattr(rec, 'amount', 0.0) or 0.0),
                'destination_currency': getattr(rec, 'destination_currency', False) and getattr(rec.destination_currency, 'id') or False,
                'total_amount': float(getattr(rec, 'total_amount', 0.0) or 0.0),
            }))

        if not reversal_lines:
            raise UserError("No valid transactions found for reversal.")

        reversal = self.env['atlaxchange.reversal'].create({
            'reversal_line_ids': reversal_lines,
            'reason': 'Transaction failed',  # <-- Provide a default reason
        })

        return {
            'name': 'Reversal',
            'type': 'ir.actions.act_window',
            'res_model': 'atlaxchange.reversal',
            'res_id': reversal.id,
            'view_mode': 'form',
            'target': 'current',
        }

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

        while True:
            params = {'after': next_cursor} if next_cursor else {}
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code != 200:
                    break

                data = response.json()
                transactions = data.get('data', {}).get('transactions', [])

                new_records = []
                for record in transactions:
                    reference = record.get('reference')
                    existing = self.search([('transaction_reference', '=', reference)], limit=1)
                    created_at = datetime.utcfromtimestamp(record['created_at'])
                    currency = self.env['supported.currency'].search([('currency_code', '=', record.get('currency_code'))], limit=1)
                    dest_currency = self.env['supported.currency'].search([('currency_code', '=', record.get('destination_currency'))], limit=1)
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
                        'beneficiary_acct': record.get('beneficiary_acct', ''),
                        'session_id': record.get('session_id', ''),
                        'error_message': record.get('error_message', ''),
                    }
                    if existing:
                        existing.write({
                            'status': status,
                            'beneficiary_acct': record.get('beneficiary_acct', ''),
                            'session_id': record.get('session_id', ''),
                            'error_message': record.get('error_message', ''),
                        })
                    else:
                        new_records.append(vals)

                if new_records:
                    self.create(new_records)

                next_cursor = data.get('data', {}).get('cursor', {}).get('after')
                if not next_cursor:
                    break
            except (ConnectTimeout, ReadTimeout):
                _logger.error("Connection to the API timed out.")
                break
            except Exception as e:
                _logger.error(f"An unexpected error occurred: {str(e)}")
                break


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

    @api.model
    def fetch_ledger_history_enqueue(self):
        """Start fetch_ledger_history in a background thread and return immediately.

        This version schedules the background job and returns {'scheduled': True}
        so the client can reload automatically instead of showing a UserError.
        """
        db_name = self.env.cr.dbname

        def _worker(dbname):
            try:
                _logger.info("Background fetch_ledger_history: worker starting for db=%s", dbname)
                with registry_get(dbname).cursor() as cr:
                    env = odoo_api.Environment(cr, SUPERUSER_ID, {})
                    env['atlaxchange.ledger'].fetch_ledger_history()
                    try:
                        cr.commit()
                    except Exception:
                        _logger.exception("Failed to explicit commit in background worker for db=%s", dbname)
                _logger.info("Background fetch_ledger_history: worker finished for db=%s", dbname)
            except Exception as e:
                _logger.exception("Background fetch_ledger_history failed for db=%s: %s", dbname, e)

        try:
            thread = threading.Thread(target=_worker, args=(db_name,))
            thread.daemon = False
            thread.start()
        except Exception as e:
            # Surface the scheduling error to the caller
            raise UserError(_("Failed to schedule ledger fetch: %s") % str(e))

        # Return a small payload so the client can reload automatically
        return {'scheduled': True}
