from odoo import models, _

class AccountStatementReport(models.AbstractModel):
    _name = 'report.atlaxchange_ledger.report_account_statement_pdf'
    _description = 'Account Statement Report'

    def _get_report_values(self, docids, data=None):
        wizard = self.env['account.statement.wizard'].browse(docids)
        partner = self.env['res.partner'].browse(data['partner_id'])
        wallet = self.env['supported.currency'].browse(data['wallet_id'])
        date_from = data['date_from']
        date_to = data['date_to']

        ledgers = self.env['atlaxchange.ledger'].search([
            ('customer_name', '=', partner.company_name),
            ('datetime', '>=', date_from),
            ('datetime', '<=', date_to),
            ('wallet', '=', wallet.id)
        ], order='datetime asc')

        # Collections (credit)
        collection_lines = ledgers.filtered(lambda l: l.transfer_direction == 'credit')
        total_collection = sum(collection_lines.mapped('amount'))
        count_collection = len(collection_lines)

        # Payouts (debit)
        payout_lines = ledgers.filtered(lambda l: l.transfer_direction == 'debit')
        total_payout = sum(payout_lines.mapped('amount'))
        count_payout = len(payout_lines)

        # Payout breakdown
        payout_success = payout_lines.filtered(lambda l: l.status == 'success')
        payout_failed = payout_lines.filtered(lambda l: l.status in ['failed', 'reversed'])
        count_payout_success = len(payout_success)
        count_payout_failed = len(payout_failed)
        sum_payout_success = sum(payout_success.mapped('amount'))
        sum_fee_success = sum(payout_success.mapped('fee'))

        # Customer balance from account.ledger for the selected wallet
        account_ledger = self.env['account.ledger'].search([
            ('partner_id', '=', partner.id),
            ('currency_id', '=', wallet.id)
        ], limit=1)
        customer_balance = account_ledger.balance if account_ledger else 0.0

        # Wallet symbol
        wallet_symbol = wallet.symbol or wallet.currency_code or ''

        company = self.env.company
        return {
            'doc_ids': docids,
            'doc_model': 'account.statement.wizard',
            'docs': wizard,
            'company': company,
            'statement_data': {
                'partner': partner,
                'date_from': date_from,
                'date_to': date_to,
                'customer_balance': customer_balance,
                'count_collection': count_collection,
                'count_payout': count_payout,
                'count_payout_success': count_payout_success,
                'count_payout_failed': count_payout_failed,
                'total_collection': total_collection,
                'total_payout': total_payout,
                'sum_payout_success': sum_payout_success,
                'sum_fee_success': sum_fee_success,
                'collection_lines': collection_lines,
                'payout_lines': payout_lines,
                'wallet_symbol': wallet_symbol,
            }
        }
