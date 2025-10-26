from odoo import models, fields, api
from datetime import datetime
from odoo.exceptions import UserError
import base64
import xlsxwriter
from io import BytesIO
import logging

_logger = logging.getLogger(__name__)


class AccountStatementWizard(models.TransientModel):
    _name = 'account.statement.wizard'
    _description = 'Account Statement Wizard'

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        domain=[('is_atlax_customer', '=', True)])
    wallet_id = fields.Many2one(
        'supported.currency', string='Wallet', required=True,
        help="Choose the wallet (currency) for which to generate the statement.")
    date_from = fields.Date(string='Start Date', required=True)
    date_to = fields.Date(string='End Date', required=True)
    report_format = fields.Selection([
        ('pdf', 'PDF'),
        ('xls', 'Excel'),
    ], string='Report Format', default='xls', required=True)
    dummy = fields.Binary('Dummy')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Restrict wallet list to currencies that exist in partner's ledgers."""
        if not self.partner_id:
            return
        wallet_ids = set()

        # Safely gather wallets from atlaxchange.ledger (field 'wallet')
        try:
            if hasattr(self.partner_id, 'partner_ledger_ids'):
                ledger_wallets = self.partner_id.partner_ledger_ids.mapped('wallet.id')
                wallet_ids.update([wid for wid in ledger_wallets if wid])
        except Exception:
            # ignore mapping errors from unexpected records
            pass

        # Also gather currencies from account.ledger (field 'currency_id')
        try:
            if hasattr(self.partner_id, 'ledger_ids'):
                acct_wallets = self.partner_id.ledger_ids.mapped('currency_id.id')
                wallet_ids.update([wid for wid in acct_wallets if wid])
        except Exception:
            pass

        domain = {'wallet_id': [('id', 'in', list(wallet_ids) or [False])]}
        if len(wallet_ids) == 1:
            self.wallet_id = list(wallet_ids)[0]
        return {'domain': domain}

    def action_generate_statement(self):
        self.ensure_one()

        # Refresh partner balances first (per request)
        try:
            if hasattr(self.partner_id, 'action_refresh_balance'):
                self.partner_id.action_refresh_balance()
        except Exception as e:
            _logger.exception("Failed to refresh partner balance: %s", e)
            # continue, but log the problem

        data = {
            'partner_id': self.partner_id.id,
            'wallet_id': self.wallet_id.id,
            'date_from': self.date_from.strftime('%Y-%m-%d'),
            'date_to': self.date_to.strftime('%Y-%m-%d'),
            'report_format': self.report_format,
        }
        if self.report_format == 'pdf':
            return self.env.ref('atlaxchange_ledger.action_report_account_statement_pdf').report_action(self, data=data)
        else:
            return self.export_statement_xls(data)

    def export_statement_xls(self, data):
        partner = self.env['res.partner'].browse(data['partner_id'])
        wallet = self.env['supported.currency'].browse(data['wallet_id'])
        date_from = data['date_from']
        date_to = data['date_to']

        # Search ledger records for the partner filtered by selected wallet
        ledgers = self.env['atlaxchange.ledger'].search([
            ('customer_name', '=', partner.company_name),
            ('datetime', '>=', date_from),
            ('datetime', '<=', date_to),
            ('wallet', '=', wallet.id)
        ], order='datetime asc')

        collection_lines = ledgers.filtered(lambda l: l.type == 'credit')
        total_collection = sum(collection_lines.mapped('amount'))
        count_collection = len(collection_lines)

        payout_lines = ledgers.filtered(lambda l: l.type == 'debit')
        total_payout = sum(payout_lines.mapped('amount'))
        count_payout = len(payout_lines)

        payout_success = payout_lines.filtered(lambda l: l.status == 'success')
        payout_failed = payout_lines.filtered(lambda l: l.status in ['failed', 'reversed'])
        count_payout_success = len(payout_success)
        count_payout_failed = len(payout_failed)
        sum_payout_success = sum(payout_success.mapped('amount'))
        sum_fee_success = sum(payout_success.mapped('fee'))

        # Customer balance: fetch from account.ledger for this partner and wallet (updated by action_refresh_balance)
        account_ledger = self.env['account.ledger'].search([
            ('partner_id', '=', partner.id),
            ('currency_id', '=', wallet.id)
        ], limit=1)
        customer_balance = account_ledger.balance if account_ledger else 0.0

        # Wallet symbol
        wallet_symbol = wallet.symbol or wallet.currency_code or ''

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        sheet = workbook.add_worksheet('Statement')
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})

        row = 0
        sheet.write(row, 0, 'Statement of Account', bold)
        row += 2
        sheet.write(row, 0, 'Customer')
        sheet.write(row, 1, partner.display_name)
        row += 1
        sheet.write(row, 0, 'Wallet')
        sheet.write(row, 1, f"{wallet_symbol} ({wallet.currency_code})")
        row += 1
        sheet.write(row, 0, 'Period')
        sheet.write(row, 1, f"{date_from} to {date_to}")
        row += 1
        sheet.write(row, 0, 'Customer Balance')
        sheet.write(row, 1, f"{wallet_symbol}{customer_balance:,.2f}", money)
        row += 1
        sheet.write(row, 0, 'Total Collections')
        sheet.write(row, 1, f"{wallet_symbol}{total_collection:,.2f}", money)
        sheet.write(row, 2, count_collection)
        row += 1
        sheet.write(row, 0, 'Total Payouts')
        sheet.write(row, 1, f"{wallet_symbol}{total_payout:,.2f}", money)
        sheet.write(row, 2, count_payout)
        row += 1
        sheet.write(row, 0, 'Successful Payouts')
        sheet.write(row, 1, f"{wallet_symbol}{sum_payout_success:,.2f}", money)
        sheet.write(row, 2, count_payout_success)
        row += 1
        sheet.write(row, 0, 'Failed/Reverse Payouts')
        sheet.write(row, 1, count_payout_failed)
        row += 2

        # Collection Transactions Table
        sheet.write(row, 0, 'Collection Transactions', bold)
        row += 1
        headers = ['Date', 'Reference', 'Wallet', 'Amount', 'Status']
        for col_num, header in enumerate(headers):
            sheet.write(row, col_num, header, bold)
        row += 1
        for col in collection_lines:
            wallet_symbol = col.wallet.symbol if col.wallet else wallet_symbol
            sheet.write(row, 0, str(col.datetime))
            sheet.write(row, 1, col.transaction_reference)
            sheet.write(row, 2, col.wallet.currency_code if col.wallet else '')
            sheet.write(row, 3, float('%.2f' % col.amount), money)
            sheet.write(row, 4, col.status)
            row += 1

        row += 2
        # Payout Transactions Table
        sheet.write(row, 0, 'Payout Transactions', bold)
        row += 1
        headers = [
            'Date', 'Reference', 'Bank', 'Beneficiary', 'Wallet',
            'Amount', 'Fee', 'Conversion Rate', 'Destination Currency', 'Dest. Amount', 'Status'
        ]
        for col_num, header in enumerate(headers):
            sheet.write(row, col_num, header, bold)
        row += 1
        for pay in payout_lines:
            wallet_symbol = pay.wallet.symbol if pay.wallet else wallet_symbol
            sheet.write(row, 0, str(pay.datetime))
            sheet.write(row, 1, pay.transaction_reference)
            sheet.write(row, 2, pay.bank)
            sheet.write(row, 3, pay.beneficiary)
            sheet.write(row, 4, pay.wallet.currency_code if pay.wallet else '')
            sheet.write(row, 5, float('%.2f' % pay.amount), money)
            sheet.write(row, 6, float('%.2f' % pay.fee), money)
            sheet.write(row, 7, f"{pay.conversion_rate:.2f}")
            sheet.write(row, 8, pay.destination_currency.currency_code if pay.destination_currency else '')
            sheet.write(row, 9, f"{pay.destination_currency.symbol if pay.destination_currency else ''}{pay.total_amount:.2f}")
            sheet.write(row, 10, pay.status)
            row += 1

        # Total successful payout (amount and fee) as a bold sum row in the table
        sheet.write(row, 0, 'Total Successful Payouts', bold)
        sheet.write(row, 5, f"{wallet_symbol}{sum_payout_success:,.2f}", bold)
        sheet.write(row, 6, f"{wallet_symbol}{sum_fee_success:,.2f}", bold)

        workbook.close()
        output.seek(0)
        xls_data = output.read()
        output.close()
        self.dummy = base64.b64encode(xls_data)
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=account.statement.wizard&id=%s&field=dummy&download=true&filename=statement.xlsx' % self.id,
            'target': 'self',
        }