from odoo import models, _

class AccountStatementReport(models.AbstractModel):
    _name = 'report.atlaxchange_ledger.report_account_statement_pdf'
    _description = 'Account Statement Report'

    def _get_report_values(self, docids, data=None):
        wizard = self.env['account.statement.wizard'].browse(docids)
        partner = self.env['res.partner'].browse(data['partner_id'])
        date_from = data['date_from']
        date_to = data['date_to']
        ledgers = self.env['atlaxchange.ledger'].search([
            ('customer_name', '=', partner.company_name),
            ('datetime', '>=', date_from),
            ('datetime', '<=', date_to)
        ], order='datetime asc')

        # Collections (credit)
        collection_lines = ledgers.filtered(lambda l: l.type == 'credit')
        total_collection = sum(collection_lines.mapped('amount'))
        count_collection = len(collection_lines)

        # Payouts (debit)
        payout_lines = ledgers.filtered(lambda l: l.type == 'debit')
        total_payout = sum(payout_lines.mapped('amount'))
        count_payout = len(payout_lines)

        # Payout breakdown
        payout_success = payout_lines.filtered(lambda l: l.status == 'success')
        payout_failed = payout_lines.filtered(lambda l: l.status in ['failed', 'reversed'])
        count_payout_success = len(payout_success)
        count_payout_failed = len(payout_failed)
        sum_payout_success = sum(payout_success.mapped('amount'))
        sum_fee_success = sum(payout_success.mapped('fee'))

        # Customer balance
        customer_balance = total_collection - sum_payout_success

        # Get currency symbol (assume all collections use the same wallet/currency)
        currency_symbol = ''
        if collection_lines and collection_lines[0].wallet and collection_lines[0].wallet.currency_code:
            currency_symbol = collection_lines[0].wallet.currency_id.symbol or collection_lines[0].wallet.currency_code
        elif payout_lines and payout_lines[0].wallet and payout_lines[0].wallet.currency_code:
            currency_symbol = payout_lines[0].wallet.currency_id.symbol or payout_lines[0].wallet.currency_code

        return {
            'doc_ids': docids,
            'doc_model': 'account.statement.wizard',
            'docs': wizard,
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
                'currency_symbol': currency_symbol,
            }
        }
