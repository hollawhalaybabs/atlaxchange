from odoo import models, fields, api
from datetime import datetime
from odoo.exceptions import UserError
import base64
import xlsxwriter
from io import BytesIO


class AccountStatementWizard(models.TransientModel):
    _name = 'account.statement.wizard'
    _description = 'Account Statement Wizard'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True, domain=[('is_atlax_customer', '=', True)])
    date_from = fields.Date(string='Start Date', required=True)
    date_to = fields.Date(string='End Date', required=True)
    report_format = fields.Selection([
        ('pdf', 'PDF'),
        ('xls', 'Excel'),
    ], string='Report Format', default='pdf', required=True)
    dummy = fields.Binary('Dummy')  # <-- Add this line

    def action_generate_statement(self):
        self.ensure_one()
        data = {
            'partner_id': self.partner_id.id,
            'date_from': self.date_from.strftime('%Y-%m-%d'),
            'date_to': self.date_to.strftime('%Y-%m-%d'),
            'report_format': self.report_format,
        }
        if self.report_format == 'pdf':
            return self.env.ref('atlaxchange_ledger.action_report_account_statement_pdf').report_action(self, data=data)
        else:
            return self.export_statement_xls(data)  # <-- call on self

    def export_statement_xls(self, data):
        partner = self.env['res.partner'].browse(data['partner_id'])
        date_from = data['date_from']
        date_to = data['date_to']

        ledgers = self.env['atlaxchange.ledger'].search([
            ('customer_name', '=', partner.company_name),
            ('datetime', '>=', date_from),
            ('datetime', '<=', date_to)
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

        # Customer balance: total_collection - (sum_payout_success + sum_fee_success)
        customer_balance = total_collection - (sum_payout_success + sum_fee_success)

        # Get wallet currency symbol
        wallet_symbol = ''
        if collection_lines:
            wallet = getattr(collection_lines[0], 'wallet', None)
            currency = getattr(wallet, 'currency_id', None)
            if currency and hasattr(currency, 'symbol') and currency.symbol:
                wallet_symbol = currency.symbol
        elif payout_lines:
            wallet = getattr(payout_lines[0], 'wallet', None)
            currency = getattr(wallet, 'currency_id', None)
            if currency and hasattr(currency, 'symbol') and currency.symbol:
                wallet_symbol = currency.symbol

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
        sheet.write(row, 0, 'Period')
        sheet.write(row, 1, f"{date_from} to {date_to}")
        row += 1
        sheet.write(row, 0, 'Customer Balance')
        sheet.write(row, 1, f"{wallet_symbol}{customer_balance:.2f}")
        row += 1
        sheet.write(row, 0, 'Total Collections')
        sheet.write(row, 1, f"{wallet_symbol}{total_collection:.2f}")
        sheet.write(row, 2, count_collection)
        row += 1
        sheet.write(row, 0, 'Total Payouts')
        sheet.write(row, 1, f"{wallet_symbol}{total_payout:.2f}")
        sheet.write(row, 2, count_payout)
        row += 1
        sheet.write(row, 0, 'Successful Payouts')
        sheet.write(row, 1, f"{wallet_symbol}{sum_payout_success:.2f}")
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
            wallet_symbol = col.wallet.symbol if col.wallet else ''
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
            # For wallet amount, use wallet currency symbol
            wallet_symbol = pay.wallet.symbol if pay.wallet else ''
            sheet.write(row, 0, str(pay.datetime))
            sheet.write(row, 1, pay.transaction_reference)
            sheet.write(row, 2, pay.bank)
            sheet.write(row, 3, pay.beneficiary)
            sheet.write(row, 4, pay.wallet.currency_code if pay.wallet else '')
            sheet.write(row, 5, f"{wallet_symbol}{pay.amount:.2f}")
            sheet.write(row, 6, f"{wallet_symbol}{pay.fee:.2f}")
            sheet.write(row, 7, f"{pay.conversion_rate:.2f}")
            sheet.write(row, 8, pay.destination_currency.currency_code if pay.destination_currency else '')
            # For destination amount, use destination currency symbol
            dest_symbol = pay.destination_currency.symbol if pay.destination_currency else ''
            sheet.write(row, 9, f"{dest_symbol}{pay.total_amount:.2f}")
            sheet.write(row, 10, pay.status)
            row += 1

        # Total successful payout (amount and fee) as a bold sum row in the table
        sheet.write(row, 0, 'Total Successful Payouts', bold)
        sheet.write(row, 5, f"{wallet_symbol}{sum_payout_success:.2f}", bold)
        sheet.write(row, 7, f"{wallet_symbol}{sum_fee_success:.2f}", bold)

        workbook.close()
        output.seek(0)
        xls_data = output.read()
        output.close()
        # Use Odoo's binary field download mechanism
        self.dummy = base64.b64encode(xls_data)
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=account.statement.wizard&id=%s&field=dummy&download=true&filename=statement.xlsx' % self.id,
            'target': 'self',
        }