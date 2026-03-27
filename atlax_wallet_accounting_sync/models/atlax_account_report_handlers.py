import json
from collections import defaultdict
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare
from odoo.tools.misc import format_date, get_lang


class AtlaxWalletReportMixin(models.AbstractModel):
    _name = 'atlax.wallet.report.mixin'
    _description = 'Atlax Wallet Report Mixin'

    def _atlax_get_report_currency(self, report, options):
        return report._atlax_get_report_currency(options)

    def _atlax_account_name_sql(self, table_alias='account'):
        lang = self.env.user.lang or get_lang(self.env).code
        if self.pool['account.account'].name.translate:
            return f"COALESCE({table_alias}.name->>'{lang}', {table_alias}.name->>'en_US')"
        return f'{table_alias}.name'

    def _atlax_journal_name_sql(self, table_alias='journal'):
        lang = self.env.user.lang or get_lang(self.env).code
        if self.pool['account.journal'].name.translate:
            return f"COALESCE({table_alias}.name->>'{lang}', {table_alias}.name->>'en_US')"
        return f'{table_alias}.name'

    def _atlax_amount_sign(self, account_type):
        if account_type in (
            'equity',
            'equity_unaffected',
            'income',
            'income_other',
            'liability_credit_card',
            'liability_current',
            'liability_non_current',
            'liability_payable',
        ):
            return -1.0
        return 1.0

    def _atlax_split_amount(self, amount):
        amount = float(amount or 0.0)
        return {
            'debit': amount if amount > 0.0 else 0.0,
            'credit': -amount if amount < 0.0 else 0.0,
            'balance': amount,
        }

    def _atlax_make_cell(self, value, currency, *, blank_if_zero=True, col_class='number'):
        return {
            'name': '',
            'no_format': value,
            'class': col_class,
            'atlax_currency_id': currency.id if currency else False,
            'atlax_blank_if_zero': blank_if_zero,
        }

    def _atlax_wallet_account_ids(self, company_ids):
        mappings = self.env['wallet.account.map'].sudo().search([
            ('active', '=', True),
            ('company_id', 'in', company_ids),
        ])
        return {
            'bank_settlement': list({account.id for account in mappings.mapped('bank_settlement_account_id') if account}),
            'fee_income': list({account.id for account in mappings.mapped('fee_income_account_id') if account}),
            'fx_position': list({account.id for account in mappings.mapped('fx_position_account_id') if account}),
            'payout_clearing': list({account.id for account in mappings.mapped('payout_clearing_account_id') if account}),
            'wallet_liability': list({account.id for account in mappings.mapped('wallet_liability_account_id') if account}),
        }

    def _atlax_partner_ledger_account_ids(self, company_ids):
        account_ids = self._atlax_wallet_account_ids(company_ids)
        return sorted(set(account_ids['wallet_liability']) | set(account_ids['payout_clearing']))

    def _atlax_query_amounts_by_account(self, report, options, domain, *, date_scope='normal'):
        account_name = self._atlax_account_name_sql()
        tables, where_clause, where_params = report._query_get(options, date_scope, domain=domain)
        query = f"""
            SELECT
                account.id AS account_id,
                account.code AS account_code,
                {account_name} AS account_name,
                account.account_type AS account_type,
                COALESCE(SUM(account_move_line.amount_currency), 0.0) AS amount_currency
            FROM {tables}
            JOIN account_account account ON account.id = account_move_line.account_id
            WHERE {where_clause}
            GROUP BY account.id, account.code, account.name, account.account_type
            ORDER BY account.code
        """
        self._cr.execute(query, where_params)
        return self._cr.dictfetchall()

    def _atlax_query_amount_total(self, report, options, domain, *, date_scope='normal'):
        tables, where_clause, where_params = report._query_get(options, date_scope, domain=domain)
        query = f"""
            SELECT COALESCE(SUM(account_move_line.amount_currency), 0.0) AS amount_currency
            FROM {tables}
            WHERE {where_clause}
        """
        self._cr.execute(query, where_params)
        return float((self._cr.dictfetchone() or {}).get('amount_currency') or 0.0)

    def _atlax_section_line(self, report, name, amount, currency, *, markup, level=1, class_name='', parent_id=None):
        return {
            'id': report._get_generic_line_id(None, None, markup=markup, parent_line_id=parent_id),
            'name': name,
            'level': level,
            'parent_id': parent_id,
            'class': class_name,
            'atlax_currency_id': currency.id,
            'columns': [self._atlax_make_cell(amount, currency, blank_if_zero=False)],
        }

    def _atlax_account_line(self, report, row, currency, *, markup, level, parent_id=None):
        display_amount = float(row['amount_currency'] or 0.0) * self._atlax_amount_sign(row['account_type'])
        return {
            'id': report._get_generic_line_id('account.account', row['account_id'], markup=markup, parent_line_id=parent_id),
            'name': f"{row['account_code']} {row['account_name']}",
            'level': level,
            'parent_id': parent_id,
            'atlax_currency_id': currency.id,
            'columns': [self._atlax_make_cell(display_amount, currency, blank_if_zero=False)],
        }


class AtlaxBalanceSheetReportHandler(models.AbstractModel):
    _name = 'atlax.balance.sheet.report.handler'
    _inherit = ['account.report.custom.handler', 'atlax.wallet.report.mixin']
    _description = 'Atlax Balance Sheet Report Handler'

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals):
        currency = self._atlax_get_report_currency(report, options)
        if not currency:
            return []

        asset_rows = self._atlax_query_amounts_by_account(
            report,
            options,
            [('account_id.account_type', 'in', ('asset_cash', 'asset_current', 'asset_fixed', 'asset_non_current', 'asset_prepayments', 'asset_receivable'))],
        )
        liability_rows = self._atlax_query_amounts_by_account(
            report,
            options,
            [('account_id.account_type', 'in', ('liability_credit_card', 'liability_current', 'liability_non_current', 'liability_payable'))],
        )

        asset_total = sum(float(row['amount_currency'] or 0.0) * self._atlax_amount_sign(row['account_type']) for row in asset_rows)
        liability_total = sum(float(row['amount_currency'] or 0.0) * self._atlax_amount_sign(row['account_type']) for row in liability_rows)
        net_position = asset_total - liability_total

        lines = [self._atlax_section_line(report, _('Assets'), asset_total, currency, markup='atlax_assets', level=1)]
        lines += [self._atlax_account_line(report, row, currency, markup='atlax_asset_account', level=2) for row in asset_rows]
        lines.append(self._atlax_section_line(report, _('Liabilities'), liability_total, currency, markup='atlax_liabilities', level=1))
        lines += [self._atlax_account_line(report, row, currency, markup='atlax_liability_account', level=2) for row in liability_rows]
        lines.append(self._atlax_section_line(report, _('Net Position'), net_position, currency, markup='atlax_net_position', level=1, class_name='total'))
        return [(0, line) for line in lines]


class AtlaxProfitAndLossReportHandler(models.AbstractModel):
    _name = 'atlax.profit.loss.report.handler'
    _inherit = ['account.report.custom.handler', 'atlax.wallet.report.mixin']
    _description = 'Atlax Profit and Loss Report Handler'

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals):
        currency = self._atlax_get_report_currency(report, options)
        if not currency:
            return []

        income_rows = self._atlax_query_amounts_by_account(
            report,
            options,
            [('account_id.account_type', 'in', ('income', 'income_other'))],
            date_scope='strict_range',
        )
        expense_rows = self._atlax_query_amounts_by_account(
            report,
            options,
            [('account_id.account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))],
            date_scope='strict_range',
        )

        income_total = sum(float(row['amount_currency'] or 0.0) * self._atlax_amount_sign(row['account_type']) for row in income_rows)
        expense_total = sum(float(row['amount_currency'] or 0.0) * self._atlax_amount_sign(row['account_type']) for row in expense_rows)
        net_profit = income_total - expense_total

        lines = [self._atlax_section_line(report, _('Income'), income_total, currency, markup='atlax_income', level=1)]
        lines += [self._atlax_account_line(report, row, currency, markup='atlax_income_account', level=2) for row in income_rows]
        lines.append(self._atlax_section_line(report, _('Expenses'), expense_total, currency, markup='atlax_expenses', level=1))
        lines += [self._atlax_account_line(report, row, currency, markup='atlax_expense_account', level=2) for row in expense_rows]
        lines.append(self._atlax_section_line(report, _('Net Profit'), net_profit, currency, markup='atlax_net_profit', level=1, class_name='total'))
        return [(0, line) for line in lines]


class AtlaxExecutiveSummaryReportHandler(models.AbstractModel):
    _name = 'atlax.executive.summary.report.handler'
    _inherit = ['account.report.custom.handler', 'atlax.wallet.report.mixin']
    _description = 'Atlax Executive Summary Report Handler'

    def _summary_line(self, report, name, value, currency, *, markup, level=2, class_name='', percentage=False):
        if value is None:
            cell = {}
        elif percentage:
            formatted_value = f"{round(value, 2)}%"
            cell = {
                'name': formatted_value,
                'no_format': value,
                'class': 'number',
                'atlax_skip_currency_format': True,
            }
        else:
            cell = self._atlax_make_cell(value, currency, blank_if_zero=False)
        return {
            'id': report._get_generic_line_id(None, None, markup=markup),
            'name': name,
            'level': level,
            'class': class_name,
            'atlax_currency_id': currency.id if not percentage else False,
            'columns': [cell],
        }

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals):
        currency = self._atlax_get_report_currency(report, options)
        if not currency:
            return []
        company_ids = report.get_report_company_ids(options)
        account_ids = self._atlax_wallet_account_ids(company_ids)
        end_options = dict(options)
        end_options['date'] = dict(options['date'], date_from=False)

        funding_received = -self._atlax_query_amount_total(
            report,
            options,
            [('account_id', 'in', account_ids['wallet_liability']), ('move_id.wallet_posting_type', '=', 'funding')],
            date_scope='strict_range',
        )
        wallet_debits = self._atlax_query_amount_total(
            report,
            options,
            [('account_id', 'in', account_ids['wallet_liability']), ('move_id.wallet_posting_type', '=', 'wallet_debit')],
            date_scope='strict_range',
        )
        fee_income = -self._atlax_query_amount_total(
            report,
            options,
            [('account_id', 'in', account_ids['fee_income'])],
            date_scope='strict_range',
        )
        destination_settlements = self._atlax_query_amount_total(
            report,
            options,
            [('account_id', 'in', account_ids['bank_settlement']), ('move_id.wallet_posting_type', '=', 'destination_settlement')],
            date_scope='strict_range',
        )
        current_wallet_balance = -self._atlax_query_amount_total(
            report,
            end_options,
            [('account_id', 'in', account_ids['wallet_liability'])],
            date_scope='normal',
        )

        asset_position_rows = self._atlax_query_amounts_by_account(
            report,
            end_options,
            [('account_id.account_type', 'in', ('asset_cash', 'asset_current', 'asset_fixed', 'asset_non_current', 'asset_prepayments', 'asset_receivable'))],
        )
        liability_position_rows = self._atlax_query_amounts_by_account(
            report,
            end_options,
            [('account_id.account_type', 'in', ('liability_credit_card', 'liability_current', 'liability_non_current', 'liability_payable'))],
        )
        net_operational_position = sum(
            float(row['amount_currency'] or 0.0) * self._atlax_amount_sign(row['account_type'])
            for row in asset_position_rows
        ) - sum(
            float(row['amount_currency'] or 0.0) * self._atlax_amount_sign(row['account_type'])
            for row in liability_position_rows
        )
        fee_margin = (fee_income / funding_received * 100.0) if funding_received else 0.0

        lines = [
            self._summary_line(report, _('Wallet Activity'), None, currency, markup='atlax_exec_wallet_header', level=1),
            self._summary_line(report, _('Funding Received'), funding_received, currency, markup='atlax_exec_funding'),
            self._summary_line(report, _('Wallet Debits'), wallet_debits, currency, markup='atlax_exec_wallet_debits'),
            self._summary_line(report, _('Current Customer Wallet Balance'), current_wallet_balance, currency, markup='atlax_exec_wallet_balance'),
            self._summary_line(report, _('Revenue'), None, currency, markup='atlax_exec_revenue_header', level=1),
            self._summary_line(report, _('Fee Income'), fee_income, currency, markup='atlax_exec_fee_income'),
            self._summary_line(report, _('Fee Margin'), fee_margin, currency, markup='atlax_exec_fee_margin', percentage=True),
            self._summary_line(report, _('Treasury'), None, currency, markup='atlax_exec_treasury_header', level=1),
            self._summary_line(report, _('Destination Settlements'), destination_settlements, currency, markup='atlax_exec_destination_settlement'),
            self._summary_line(report, _('Net Operational Position'), net_operational_position, currency, markup='atlax_exec_net_operational', class_name='total'),
        ]
        return [(0, line) for line in lines]


class AtlaxGeneralLedgerReportHandler(models.AbstractModel):
    _name = 'atlax.general.ledger.report.handler'
    _inherit = ['account.general.ledger.report.handler', 'atlax.wallet.report.mixin']
    _description = 'Atlax General Ledger Report Handler'

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals):
        lines = []
        date_from = fields.Date.from_string(options['date'].get('date_from') or options['date'].get('date') or options['date']['date_to'])
        currency = self._atlax_get_report_currency(report, options)
        if not currency:
            return []

        totals_by_column_group = defaultdict(lambda: {'amount_currency': 0.0, 'debit': 0.0, 'credit': 0.0, 'balance': 0.0})
        for account, column_group_results in self._query_values(report, options):
            eval_dict = {}
            has_lines = False
            for column_group_key, results in column_group_results.items():
                account_sum = results.get('sum', {})
                account_un_earn = results.get('unaffected_earnings', {})
                amount_currency = account_sum.get('amount_currency', 0.0) + account_un_earn.get('amount_currency', 0.0)
                split_amounts = self._atlax_split_amount(amount_currency)

                eval_dict[column_group_key] = {
                    'amount_currency': amount_currency,
                    **split_amounts,
                }

                max_date = account_sum.get('max_date')
                has_lines = has_lines or (max_date and max_date >= date_from)

                totals_by_column_group[column_group_key]['amount_currency'] += amount_currency
                totals_by_column_group[column_group_key]['debit'] += split_amounts['debit']
                totals_by_column_group[column_group_key]['credit'] += split_amounts['credit']
                totals_by_column_group[column_group_key]['balance'] += split_amounts['balance']

            lines.append(self._get_account_title_line(report, options, account, has_lines, eval_dict, currency))

        lines.append(self._get_total_line(report, options, totals_by_column_group, currency))
        return [(0, line) for line in lines]

    def _get_initial_balance_values(self, report, account_ids, options):
        balances = super()._get_initial_balance_values(report, account_ids, options)
        for dummy_account_id, dummy_account_data in balances.items():
            account, init_balance_by_group = dummy_account_data
            for column_group_key, result in init_balance_by_group.items():
                amount_currency = float(result.get('amount_currency', 0.0))
                result.update(self._atlax_split_amount(amount_currency))
                result['amount_currency'] = amount_currency
        return balances

    def _get_account_title_line(self, report, options, account, has_lines, eval_dict, currency):
        line_columns = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            col_value = eval_dict[column['column_group_key']].get(col_expr_label)

            if col_value is None:
                line_columns.append({})
                continue

            if col_expr_label in ('date', 'communication', 'partner_name'):
                line_columns.append({})
                continue

            line_columns.append(self._atlax_make_cell(col_value, currency, blank_if_zero=col_expr_label != 'balance'))

        unfold_all = self._context.get('print_mode') or options.get('unfold_all')
        line_id = report._get_generic_line_id('account.account', account.id)
        return {
            'id': line_id,
            'name': f'{account.code} {account.name}',
            'search_key': account.code,
            'columns': line_columns,
            'level': 1,
            'unfoldable': has_lines,
            'unfolded': has_lines and (line_id in options.get('unfolded_lines') or unfold_all),
            'expand_function': '_report_expand_unfoldable_line_general_ledger',
            'class': 'o_account_reports_totals_below_sections' if self.env.company.totals_below_sections else '',
            'atlax_currency_id': currency.id,
        }

    def _get_aml_line(self, report, parent_line_id, options, eval_dict, init_bal_by_col_group, currency):
        line_columns = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            group_vals = eval_dict[column['column_group_key']]

            if col_expr_label == 'date':
                if group_vals.get('date'):
                    line_columns.append({
                        'name': format_date(self.env, group_vals['date']),
                        'no_format': group_vals['date'],
                        'class': 'date',
                    })
                else:
                    line_columns.append({})
                continue

            if col_expr_label in ('communication', 'partner_name'):
                col_value = group_vals.get(col_expr_label)
                if col_value is None:
                    line_columns.append({})
                else:
                    line_columns.append({
                        'name': col_value,
                        'no_format': col_value,
                        'class': 'o_account_report_line_ellipsis',
                    })
                continue

            raw_amount = float(group_vals.get('amount_currency', 0.0))
            split_amounts = self._atlax_split_amount(raw_amount)
            if col_expr_label == 'amount_currency':
                col_value = raw_amount
                blank_if_zero = True
            elif col_expr_label == 'debit':
                col_value = split_amounts['debit']
                blank_if_zero = True
            elif col_expr_label == 'credit':
                col_value = split_amounts['credit']
                blank_if_zero = True
            elif col_expr_label == 'balance':
                col_value = split_amounts['balance'] + init_bal_by_col_group[column['column_group_key']]
                blank_if_zero = False
            else:
                col_value = group_vals.get(col_expr_label)
                blank_if_zero = True

            if col_value is None:
                line_columns.append({})
            else:
                line_columns.append(self._atlax_make_cell(col_value, currency, blank_if_zero=blank_if_zero))

        aml_id = None
        move_name = None
        caret_type = None
        for column_group_dict in eval_dict.values():
            aml_id = column_group_dict.get('id')
            if aml_id:
                caret_type = 'account.payment' if column_group_dict.get('payment_id') else 'account.move.line'
                move_name = column_group_dict['move_name']
                break

        return {
            'id': report._get_generic_line_id('account.move.line', aml_id, parent_line_id=parent_line_id),
            'caret_options': caret_type,
            'parent_id': parent_line_id,
            'name': move_name,
            'columns': line_columns,
            'level': 2,
            'atlax_currency_id': currency.id,
        }

    def _get_total_line(self, report, options, eval_dict, currency):
        line_columns = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            col_value = eval_dict[column['column_group_key']].get(col_expr_label)
            if col_expr_label in ('date', 'communication', 'partner_name'):
                line_columns.append({})
            elif col_value is None:
                line_columns.append({})
            else:
                line_columns.append(self._atlax_make_cell(col_value, currency, blank_if_zero=False))

        return {
            'id': report._get_generic_line_id(None, None, markup='total'),
            'name': _('Total'),
            'class': 'total',
            'level': 1,
            'columns': line_columns,
            'atlax_currency_id': currency.id,
        }

    def _report_expand_unfoldable_line_general_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        def init_load_more_progress(line_dict):
            return {
                column['column_group_key']: line_col.get('no_format', 0.0)
                for column, line_col in zip(options['columns'], line_dict['columns'])
                if column['expression_label'] == 'balance'
            }

        report = self.env['account.report'].browse(options['report_id'])
        currency = self._atlax_get_report_currency(report, options)
        model, model_id = report._get_model_info_from_id(line_dict_id)
        if model != 'account.account':
            raise UserError(_('Wrong ID for general ledger line to expand: %s', line_dict_id))

        lines = []
        if offset == 0:
            if unfold_all_batch_data:
                account, init_balance_by_col_group = unfold_all_batch_data['initial_balances'][model_id]
            else:
                account, init_balance_by_col_group = self._get_initial_balance_values(report, [model_id], options)[model_id]

            initial_balance_line = report._get_partner_and_general_ledger_initial_balance_line(options, line_dict_id, init_balance_by_col_group, currency)
            if initial_balance_line:
                initial_balance_line['atlax_currency_id'] = currency.id
                lines.append(initial_balance_line)
                progress = init_load_more_progress(initial_balance_line)

        limit_to_load = report.load_more_limit + 1 if report.load_more_limit and not self._context.get('print_mode') else None
        if unfold_all_batch_data:
            aml_results = unfold_all_batch_data['aml_values'][model_id]
        else:
            aml_results = self._get_aml_values(report, options, [model_id], offset=offset, limit=limit_to_load)[model_id]

        has_more = False
        treated_results_count = 0
        next_progress = progress
        for aml_result in aml_results.values():
            if limit_to_load and treated_results_count == report.load_more_limit:
                has_more = True
                break

            new_line = self._get_aml_line(report, line_dict_id, options, aml_result, next_progress, currency)
            lines.append(new_line)
            next_progress = init_load_more_progress(new_line)
            treated_results_count += 1

        return {
            'lines': lines,
            'offset_increment': treated_results_count,
            'has_more': has_more,
            'progress': json.dumps(next_progress),
        }


class AtlaxTrialBalanceReportHandler(models.AbstractModel):
    _name = 'atlax.trial.balance.report.handler'
    _inherit = 'account.trial.balance.report.handler'
    _description = 'Atlax Trial Balance Report Handler'

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals):
        currency = report._atlax_get_report_currency(options) or self.env.company.currency_id

        def _update_column(line, column_key, new_value, blank_if_zero=True):
            line['columns'][column_key]['name'] = report.format_value(new_value, currency=currency, figure_type='monetary', blank_if_zero=blank_if_zero)
            line['columns'][column_key]['no_format'] = new_value
            line['columns'][column_key]['atlax_currency_id'] = currency.id

        def _update_balance_columns(line, debit_column_key, credit_column_key, total_diff_values_key):
            debit_value = line['columns'][debit_column_key]['no_format']
            credit_value = line['columns'][credit_column_key]['no_format']

            if debit_value and credit_value:
                new_debit_value = 0.0
                new_credit_value = 0.0

                if float_compare(debit_value, credit_value, precision_digits=currency.decimal_places) == 1:
                    new_debit_value = debit_value - credit_value
                    total_diff_values[total_diff_values_key] += credit_value
                else:
                    new_credit_value = (debit_value - credit_value) * -1
                    total_diff_values[total_diff_values_key] += debit_value

                _update_column(line, debit_column_key, new_debit_value)
                _update_column(line, credit_column_key, new_credit_value)

        lines = [
            line[1]
            for line in self.env['atlax.general.ledger.report.handler']._dynamic_lines_generator(report, options, all_column_groups_expression_totals)
        ]

        total_diff_values = {
            'initial_balance': 0.0,
            'end_balance': 0.0,
        }

        for line in lines[:-1]:
            res_model = report._get_model_info_from_id(line['id'])[0]
            if res_model == 'account.account':
                _update_balance_columns(line, 0, 1, 'initial_balance')
                _update_balance_columns(line, -2, -1, 'end_balance')

            line.pop('expand_function', None)
            line.pop('groupby', None)
            line.update({
                'unfoldable': False,
                'unfolded': False,
                'class': 'o_account_searchable_line o_account_coa_column_contrast',
                'atlax_currency_id': currency.id,
            })

            if res_model == 'account.account':
                line['caret_options'] = 'atlax_trial_balance'

        if lines:
            total_line = lines[-1]
            _update_column(total_line, 0, total_line['columns'][0]['no_format'] - total_diff_values['initial_balance'], blank_if_zero=False)
            _update_column(total_line, 1, total_line['columns'][1]['no_format'] - total_diff_values['initial_balance'], blank_if_zero=False)
            _update_column(total_line, -2, total_line['columns'][-2]['no_format'] - total_diff_values['end_balance'], blank_if_zero=False)
            _update_column(total_line, -1, total_line['columns'][-1]['no_format'] - total_diff_values['end_balance'], blank_if_zero=False)

        return [(0, line) for line in lines]

    def _caret_options_initializer(self):
        return {
            'atlax_trial_balance': [
                {'name': _('General Ledger'), 'action': 'atlax_caret_option_open_general_ledger'},
                {'name': _('Journal Items'), 'action': 'open_journal_items'},
            ],
        }

    def atlax_caret_option_open_general_ledger(self, options, params):
        record_id = None
        report = self.env['account.report'].browse(options['report_id'])
        for dummy_markup, model, model_id in reversed(report._parse_line_id(params['line_id'])):
            if model == 'account.account':
                record_id = model_id
                break

        if record_id is None:
            raise UserError(_("'Open General Ledger' caret option is only available for account lines."))

        gl_report = self.env.ref('atlax_wallet_accounting_sync.atlax_general_ledger_report')
        gl_options = gl_report._get_options({**options, 'report_id': gl_report.id})
        gl_options['unfolded_lines'] = [gl_report._get_generic_line_id('account.account', record_id)]

        action_vals = self.env['ir.actions.actions']._for_xml_id('atlax_wallet_accounting_sync.action_atlax_report_general_ledger')
        action_vals['params'] = {
            'options': gl_options,
            'ignore_session': 'read',
        }
        return action_vals


class AtlaxPartnerLedgerReportHandler(models.AbstractModel):
    _name = 'atlax.partner.ledger.report.handler'
    _inherit = ['account.report.custom.handler', 'atlax.wallet.report.mixin']
    _description = 'Atlax Partner Ledger Report Handler'

    def _wallet_partner_domain(self, report):
        partner_account_ids = self._atlax_partner_ledger_account_ids(report.get_report_company_ids({}))
        return [('account_id', 'in', partner_account_ids), ('partner_id', '!=', False)] if partner_account_ids else [('id', '=', 0)]

    def _custom_options_initializer(self, report, options, previous_options=None):
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        options['unfold_all'] = (self._context.get('print_mode') and not options.get('unfolded_lines')) or options.get('unfold_all')

    def _query_partner_period_amounts(self, report, options, *, date_scope, partner_ids=None):
        partner_account_ids = self._atlax_partner_ledger_account_ids(report.get_report_company_ids(options))
        if not partner_account_ids:
            return {}

        results = defaultdict(dict)
        for column_group_key, group_options in report._split_options_per_column_group(options).items():
            domain = [('account_id', 'in', partner_account_ids), ('partner_id', '!=', False)]
            if partner_ids is not None:
                domain.append(('partner_id', 'in', partner_ids))

            tables, where_clause, where_params = report._query_get(group_options, date_scope, domain=domain)
            query = f"""
                SELECT
                    account_move_line.partner_id AS partner_id,
                    COALESCE(SUM(account_move_line.amount_currency), 0.0) AS amount_currency
                FROM {tables}
                WHERE {where_clause}
                GROUP BY account_move_line.partner_id
            """
            self._cr.execute(query, where_params)
            for row in self._cr.dictfetchall():
                results[row['partner_id']][column_group_key] = float(row['amount_currency'] or 0.0)

        return results

    def _build_partner_lines(self, report, options):
        currency = self._atlax_get_report_currency(report, options)
        partner_values = {}
        period_amounts = self._query_partner_period_amounts(report, options, date_scope='strict_range')

        end_options = dict(options)
        end_options['date'] = dict(options['date'], date_from=False)
        end_balances = self._query_partner_period_amounts(report, end_options, date_scope='normal')

        partner_ids = sorted(set(period_amounts.keys()) | set(end_balances.keys()))
        partners = self.env['res.partner'].browse(partner_ids).sorted(lambda partner: partner.name or '')

        totals_by_column_group = {
            column_group_key: {'debit': 0.0, 'credit': 0.0, 'amount_currency': 0.0, 'balance': 0.0}
            for column_group_key in options['column_groups']
        }

        lines = []
        for partner in partners:
            values_by_group = defaultdict(dict)
            for column_group_key in options['column_groups']:
                raw_period = period_amounts.get(partner.id, {}).get(column_group_key, 0.0)
                raw_end_balance = end_balances.get(partner.id, {}).get(column_group_key, 0.0)
                split_period = self._atlax_split_amount(raw_period)
                values_by_group[column_group_key] = {
                    'debit': split_period['debit'],
                    'credit': split_period['credit'],
                    'amount_currency': -raw_period,
                    'balance': -raw_end_balance,
                }
                totals_by_column_group[column_group_key]['debit'] += split_period['debit']
                totals_by_column_group[column_group_key]['credit'] += split_period['credit']
                totals_by_column_group[column_group_key]['amount_currency'] += -raw_period
                totals_by_column_group[column_group_key]['balance'] += -raw_end_balance

            partner_values[partner.id] = values_by_group
            lines.append(self._get_report_line_partners(report, options, partner, values_by_group, currency))

        return lines, totals_by_column_group, partner_values

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals):
        if not self._atlax_get_report_currency(report, options):
            return []
        partner_lines, totals_by_column_group, dummy_values = self._build_partner_lines(report, options)
        lines = [(0, line) for line in partner_lines]
        lines.append((0, self._get_report_line_total(report, options, totals_by_column_group, self._atlax_get_report_currency(report, options))))
        return lines

    def _get_report_line_partners(self, report, options, partner, partner_values, currency):
        unfold_all = (self._context.get('print_mode') and not options.get('unfolded_lines')) or options.get('unfold_all')
        unfoldable = False
        column_values = []

        for column in options['columns']:
            col_expr_label = column['expression_label']
            value = partner_values[column['column_group_key']].get(col_expr_label)
            if value is None:
                column_values.append({})
                continue

            if col_expr_label in ('journal_code', 'account_code', 'ref', 'date_maturity', 'matching_number'):
                column_values.append({})
                continue

            unfoldable = unfoldable or (col_expr_label in ('debit', 'credit', 'balance') and value)
            column_values.append(self._atlax_make_cell(value, currency, blank_if_zero=col_expr_label != 'balance'))

        line_id = report._get_generic_line_id('res.partner', partner.id)
        return {
            'id': line_id,
            'name': (partner.name or '')[:128],
            'columns': column_values,
            'level': 2,
            'trust': partner.trust,
            'unfoldable': unfoldable,
            'unfolded': line_id in options.get('unfolded_lines') or unfold_all,
            'expand_function': '_report_expand_unfoldable_line_partner_ledger',
            'atlax_currency_id': currency.id,
        }

    def _get_initial_balance_values(self, report, partner_ids, options):
        currency = self._atlax_get_report_currency(report, options)
        if not partner_ids:
            return {}

        partner_account_ids = self._atlax_partner_ledger_account_ids(report.get_report_company_ids(options))
        if not partner_account_ids:
            return {
                partner_id: {column_group_key: {} for column_group_key in options['column_groups']}
                for partner_id in partner_ids
            }

        query_results = {
            partner_id: {column_group_key: {} for column_group_key in options['column_groups']}
            for partner_id in partner_ids
        }
        for column_group_key, group_options in report._split_options_per_column_group(options).items():
            date_from = group_options['date'].get('date_from') or group_options['date'].get('date') or group_options['date']['date_to']
            new_date_to = fields.Date.from_string(date_from) - timedelta(days=1)
            initial_options = dict(group_options, date=dict(group_options['date'], date_from=False, date_to=fields.Date.to_string(new_date_to)))
            tables, where_clause, where_params = report._query_get(initial_options, 'normal', domain=[
                ('account_id', 'in', partner_account_ids),
                ('partner_id', 'in', partner_ids),
            ])
            query = f"""
                SELECT
                    account_move_line.partner_id AS partner_id,
                    COALESCE(SUM(account_move_line.amount_currency), 0.0) AS amount_currency
                FROM {tables}
                WHERE {where_clause}
                GROUP BY account_move_line.partner_id
            """
            self._cr.execute(query, where_params)
            for row in self._cr.dictfetchall():
                raw_amount = float(row['amount_currency'] or 0.0)
                split_amounts = self._atlax_split_amount(raw_amount)
                query_results.setdefault(
                    row['partner_id'],
                    {group_key: {} for group_key in options['column_groups']},
                )[column_group_key] = {
                    'debit': split_amounts['debit'],
                    'credit': split_amounts['credit'],
                    'amount_currency': -raw_amount,
                    'balance': -raw_amount,
                }

        return query_results

    def _get_aml_values(self, report, options, partner_ids, offset=0, limit=None):
        partner_account_ids = self._atlax_partner_ledger_account_ids(report.get_report_company_ids(options))
        if not partner_account_ids or not partner_ids:
            return {partner_id: [] for partner_id in partner_ids}

        results = {partner_id: [] for partner_id in partner_ids}
        account_name = self._atlax_account_name_sql('account')
        journal_name = self._atlax_journal_name_sql('journal')
        all_params = []
        queries = []
        for column_group_key, group_options in report._split_options_per_column_group(options).items():
            tables, where_clause, where_params = report._query_get(group_options, 'strict_range', domain=[
                ('account_id', 'in', partner_account_ids),
                ('partner_id', 'in', partner_ids),
            ])
            queries.append(f"""
                SELECT
                    account_move_line.id,
                    account_move_line.date,
                    account_move_line.date_maturity,
                    account_move_line.name,
                    account_move_line.ref,
                    account_move_line.company_id,
                    account_move_line.account_id,
                    account_move_line.payment_id,
                    account_move_line.partner_id,
                    account_move_line.currency_id,
                    account_move_line.amount_currency,
                    account_move_line.matching_number,
                    account_move.name AS move_name,
                    account_move.move_type AS move_type,
                    account.code AS account_code,
                    {account_name} AS account_name,
                    journal.code AS journal_code,
                    {journal_name} AS journal_name,
                    %s AS column_group_key
                FROM {tables}
                JOIN account_move ON account_move.id = account_move_line.move_id
                JOIN account_account account ON account.id = account_move_line.account_id
                JOIN account_journal journal ON journal.id = account_move_line.journal_id
                WHERE {where_clause}
                ORDER BY account_move_line.date, account_move_line.id
            """)
            all_params.append(column_group_key)
            all_params += where_params

        query = ' UNION ALL '.join(queries)
        if offset:
            query += ' OFFSET %s'
            all_params.append(offset)
        if limit:
            query += ' LIMIT %s'
            all_params.append(limit)

        self._cr.execute(query, all_params)
        for aml_result in self._cr.dictfetchall():
            results[aml_result['partner_id']].append(aml_result)

        return results

    def _report_expand_unfoldable_line_partner_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        def init_load_more_progress(line_dict):
            return {
                column['column_group_key']: line_col.get('no_format', 0.0)
                for column, line_col in zip(options['columns'], line_dict['columns'])
                if column['expression_label'] == 'balance'
            }

        report = self.env['account.report'].browse(options['report_id'])
        currency = self._atlax_get_report_currency(report, options)
        markup, model, record_id = report._parse_line_id(line_dict_id)[-1]
        if model != 'res.partner':
            raise UserError(_('Wrong ID for partner ledger line to expand: %s', line_dict_id))

        lines = []
        if offset == 0:
            init_balances = self._get_initial_balance_values(report, [record_id], options).get(
                record_id,
                {column_group_key: {} for column_group_key in options['column_groups']},
            )
            initial_balance_line = report._get_partner_and_general_ledger_initial_balance_line(options, line_dict_id, init_balances, currency)
            if initial_balance_line:
                initial_balance_line['atlax_currency_id'] = currency.id
                lines.append(initial_balance_line)
                progress = init_load_more_progress(initial_balance_line)

        limit_to_load = report.load_more_limit + 1 if report.load_more_limit and not self._context.get('print_mode') else None
        aml_results = self._get_aml_values(report, options, [record_id], offset=offset, limit=limit_to_load)[record_id]

        has_more = False
        treated_results_count = 0
        next_progress = progress
        for aml_result in aml_results:
            if limit_to_load and treated_results_count == report.load_more_limit:
                has_more = True
                break

            new_line = self._get_report_line_move_line(report, options, aml_result, line_dict_id, next_progress, currency)
            lines.append(new_line)
            next_progress = init_load_more_progress(new_line)
            treated_results_count += 1

        return {
            'lines': lines,
            'offset_increment': treated_results_count,
            'has_more': has_more,
            'progress': json.dumps(next_progress),
        }

    def _get_report_line_move_line(self, report, options, aml_query_result, partner_line_id, init_bal_by_col_group, currency):
        caret_type = 'account.payment' if aml_query_result['payment_id'] else 'account.move.line'
        columns = []
        raw_amount = float(aml_query_result['amount_currency'] or 0.0)
        split_amounts = self._atlax_split_amount(raw_amount)

        for column in options['columns']:
            col_expr_label = column['expression_label']
            if column['column_group_key'] != aml_query_result['column_group_key']:
                columns.append({})
                continue

            if col_expr_label == 'journal_code':
                columns.append({'name': aml_query_result['journal_code'], 'no_format': aml_query_result['journal_code'], 'class': ''})
            elif col_expr_label == 'account_code':
                columns.append({'name': aml_query_result['account_code'], 'no_format': aml_query_result['account_code'], 'class': ''})
            elif col_expr_label == 'ref':
                columns.append({
                    'name': report._format_aml_name(aml_query_result['name'], aml_query_result['ref'], aml_query_result['move_name']),
                    'no_format': aml_query_result['ref'],
                    'class': 'o_account_report_line_ellipsis',
                })
            elif col_expr_label == 'date_maturity':
                maturity = aml_query_result['date_maturity']
                columns.append(maturity and {
                    'name': format_date(self.env, fields.Date.from_string(maturity)),
                    'no_format': maturity,
                    'class': 'date',
                } or {})
            elif col_expr_label == 'matching_number':
                columns.append({'name': aml_query_result['matching_number'] or '', 'no_format': aml_query_result['matching_number'], 'class': ''})
            elif col_expr_label == 'debit':
                columns.append(self._atlax_make_cell(split_amounts['debit'], currency))
            elif col_expr_label == 'credit':
                columns.append(self._atlax_make_cell(split_amounts['credit'], currency))
            elif col_expr_label == 'amount_currency':
                columns.append(self._atlax_make_cell(-raw_amount, currency))
            elif col_expr_label == 'balance':
                columns.append(self._atlax_make_cell(init_bal_by_col_group.get(column['column_group_key'], 0.0) - raw_amount, currency, blank_if_zero=False))
            else:
                columns.append({})

        return {
            'id': report._get_generic_line_id('account.move.line', aml_query_result['id'], parent_line_id=partner_line_id),
            'parent_id': partner_line_id,
            'name': format_date(self.env, aml_query_result['date']),
            'class': 'text',
            'columns': columns,
            'caret_options': caret_type,
            'level': 2,
            'atlax_currency_id': currency.id,
        }

    def _get_report_line_total(self, report, options, totals_by_column_group, currency):
        column_values = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            value = totals_by_column_group[column['column_group_key']].get(col_expr_label)
            if col_expr_label in ('journal_code', 'account_code', 'ref', 'date_maturity', 'matching_number'):
                column_values.append({})
            else:
                column_values.append(self._atlax_make_cell(value, currency, blank_if_zero=col_expr_label != 'balance'))

        return {
            'id': report._get_generic_line_id(None, None, markup='total'),
            'name': _('Total'),
            'class': 'total',
            'level': 1,
            'columns': column_values,
            'atlax_currency_id': currency.id,
        }

    def _caret_options_initializer(self):
        return {
            'account.move.line': [{'name': _('View Journal Entry'), 'action': 'caret_option_open_record_form'}],
            'account.payment': [{'name': _('View Payment'), 'action': 'caret_option_open_record_form', 'action_param': 'payment_id'}],
        }

    def open_journal_items(self, options, params):
        params['view_ref'] = 'account.view_move_line_tree_grouped_partner'
        action = self.env['account.report'].open_journal_items(options=options, params=params)
        action.get('context', {}).update({'search_default_group_by_account': 0, 'search_default_group_by_partner': 1})
        return action


class AtlaxJournalReportHandler(models.AbstractModel):
    _name = 'atlax.journal.report.handler'
    _inherit = ['account.journal.report.handler', 'atlax.wallet.report.mixin']
    _description = 'Atlax Journal Report Handler'

    def _get_first_move_line(self, options, parent_key, line_key, values, is_unreconciled_payment):
        report = self.env['account.report'].browse(options['report_id'])
        currency = self._atlax_get_report_currency(report, options)
        columns = []
        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            group_values = values[column_group_key]
            raw_amount = float(group_values.get('amount_currency') or 0.0)
            split_amounts = self._atlax_split_amount(raw_amount)
            not_receivable_with_partner = group_values['partner_name'] and group_values['account_type'] not in ('asset_receivable', 'liability_payable')
            columns.extend([
                {
                    'name': '%s %s' % (group_values['account_code'], '' if group_values['partner_name'] else group_values['account_name']),
                    'name_right': group_values['partner_name'],
                    'class': 'o_account_report_line_ellipsis' + (' color-blue' if not_receivable_with_partner else ''),
                    'template': 'account_reports.cell_template_journal_audit_report',
                    'style': 'text-align:left;',
                },
                {'name': group_values['name'], 'class': 'o_account_report_line_ellipsis', 'style': 'text-align:left;'},
                self._atlax_make_cell(split_amounts['debit'], currency),
                self._atlax_make_cell(split_amounts['credit'], currency),
            ] + self._get_move_line_additional_col(column_group_options, False, group_values, is_unreconciled_payment))

        return {
            'id': line_key,
            'name': next(col_group_val for col_group_val in values.values())['move_name'],
            'level': 3,
            'date': format_date(self.env, next(col_group_val for col_group_val in values.values())['date']),
            'columns': columns,
            'parent_id': parent_key,
            'move_id': next(col_group_val for col_group_val in values.values())['move_id'],
            'class': 'o_account_reports_ja_move_line',
            'atlax_currency_id': currency.id,
        }

    def _query_journal(self, options):
        params = []
        queries = []
        report = self.env['account.report'].browse(options['report_id'])
        if self.pool['account.journal'].name.translate:
            lang = self.env.user.lang or get_lang(self.env).code
            journal_name = f"COALESCE(j.name->>'{lang}', j.name->>'en_US')"
        else:
            journal_name = 'j.name'

        for column_group_key, options_group in report._split_options_per_column_group(options).items():
            tables, where_clause, where_params = report._query_get(options_group, 'strict_range')
            params.append(column_group_key)
            params += where_params
            queries.append(f"""
                SELECT
                    %s AS column_group_key,
                    j.id,
                    {journal_name} AS name,
                    j.code,
                    j.type,
                    j.currency_id,
                    journal_curr.name AS currency_name,
                    cp.currency_id AS company_currency
                FROM {tables}
                JOIN account_journal j ON j.id = account_move_line.journal_id
                JOIN res_company cp ON cp.id = account_move_line.company_id
                LEFT JOIN res_currency journal_curr ON journal_curr.id = j.currency_id
                WHERE {where_clause}
                ORDER BY j.id
            """)

        result = {}
        self._cr.execute(' UNION ALL '.join(queries), params)
        for journal_result in self._cr.dictfetchall():
            result.setdefault(journal_result['id'], {column_group_key: {} for column_group_key in options['column_groups']})
            result[journal_result['id']][journal_result['column_group_key']] = journal_result

        return result

    def _query_aml(self, options, offset=0, journal=False):
        params = []
        queries = []
        lang = self.env.user.lang or get_lang(self.env).code
        account_name = f"COALESCE(acc.name->>'{lang}', acc.name->>'en_US')" if self.pool['account.account'].name.translate else 'acc.name'
        journal_name = f"COALESCE(j.name->>'{lang}', j.name->>'en_US')" if self.pool['account.journal'].name.translate else 'j.name'
        tax_name = f"COALESCE(tax.name->>'{lang}', tax.name->>'en_US')" if self.pool['account.tax'].name.translate else 'tax.name'
        tag_name = f"COALESCE(tag.name->>'{lang}', tag.name->>'en_US')" if self.pool['account.account.tag'].name.translate else 'tag.name'
        report = self.env['account.report'].browse(options['report_id'])

        for column_group_key, options_group in report._split_options_per_column_group(options).items():
            options_group['date'] = options['date']
            tables, where_clause, where_params = report._query_get(options_group, 'strict_range', domain=[('journal_id', '=', journal.id)])
            sort_by_date = options_group.get('sort_by_date')
            params.append(column_group_key)
            params += where_params

            limit_to_load = report.load_more_limit + 1 if report.load_more_limit and not self._context.get('print_mode') else None

            params += [limit_to_load, offset]
            queries.append(f"""
                SELECT
                    %s AS column_group_key,
                    account_move_line.id AS move_line_id,
                    account_move_line.name,
                    account_move_line.amount_currency,
                    account_move_line.tax_base_amount,
                    account_move_line.currency_id AS move_line_currency,
                    account_move_line.amount_currency,
                    am.id AS move_id,
                    am.name AS move_name,
                    am.journal_id,
                    am.date,
                    am.currency_id AS move_currency,
                    am.amount_total_in_currency_signed AS amount_currency_total,
                    am.currency_id != cp.currency_id AS is_multicurrency,
                    p.name AS partner_name,
                    acc.code AS account_code,
                    {account_name} AS account_name,
                    acc.account_type AS account_type,
                    COALESCE(account_move_line.debit, 0) AS debit,
                    COALESCE(account_move_line.credit, 0) AS credit,
                    COALESCE(account_move_line.balance, 0) AS balance,
                    {journal_name} AS journal_name,
                    j.code AS journal_code,
                    j.type AS journal_type,
                    j.currency_id AS journal_currency,
                    journal_curr.name AS journal_currency_name,
                    cp.currency_id AS company_currency,
                    CASE WHEN j.type = 'sale' THEN am.payment_reference WHEN j.type = 'purchase' THEN am.ref ELSE '' END AS reference,
                    array_remove(array_agg(DISTINCT {tax_name}), NULL) AS taxes,
                    array_remove(array_agg(DISTINCT {tag_name}), NULL) AS tax_grids
                FROM {tables}
                JOIN account_move am ON am.id = account_move_line.move_id
                JOIN account_account acc ON acc.id = account_move_line.account_id
                LEFT JOIN res_partner p ON p.id = account_move_line.partner_id
                JOIN account_journal j ON j.id = am.journal_id
                JOIN res_company cp ON cp.id = am.company_id
                LEFT JOIN account_move_line_account_tax_rel aml_at_rel ON aml_at_rel.account_move_line_id = account_move_line.id
                LEFT JOIN account_tax parent_tax ON parent_tax.id = aml_at_rel.account_tax_id AND parent_tax.amount_type = 'group'
                LEFT JOIN account_tax_filiation_rel tax_filiation_rel ON tax_filiation_rel.parent_tax = parent_tax.id
                LEFT JOIN account_tax tax ON (tax.id = aml_at_rel.account_tax_id AND tax.amount_type != 'group') OR tax.id = tax_filiation_rel.child_tax
                LEFT JOIN account_account_tag_account_move_line_rel tag_rel ON tag_rel.account_move_line_id = account_move_line.id
                LEFT JOIN account_account_tag tag ON tag_rel.account_account_tag_id = tag.id
                LEFT JOIN res_currency journal_curr ON journal_curr.id = j.currency_id
                WHERE {where_clause}
                GROUP BY account_move_line.id, am.id, p.id, acc.id, j.id, cp.id, journal_curr.id
                ORDER BY j.id, CASE WHEN am.name = '/' THEN 1 ELSE 0 END,
                {"am.date, am.name," if sort_by_date else "am.name, am.date,"}
                CASE acc.account_type
                    WHEN 'liability_payable' THEN 1
                    WHEN 'asset_receivable' THEN 1
                    WHEN 'liability_credit_card' THEN 5
                    WHEN 'asset_cash' THEN 5
                    ELSE 2
                END,
                account_move_line.tax_line_id NULLS FIRST
                LIMIT %s
                OFFSET %s
            """)

        result = {}
        self._cr.execute('(' + ') UNION ALL ('.join(queries) + ')', params)
        for aml_result in self._cr.dictfetchall():
            result.setdefault(aml_result['move_line_id'], {column_group_key: {} for column_group_key in options['column_groups']})
            result[aml_result['move_line_id']][aml_result['column_group_key']] = aml_result

        return result

    def _query_months(self, options, line_id=False, offset=0, journal=False):
        params = []
        queries = []
        report = self.env['account.report'].browse(options['report_id'])
        for column_group_key, options_group in report._split_options_per_column_group(options).items():
            tables, where_clause, where_params = report._query_get(options_group, 'strict_range', domain=[('journal_id', '=', journal.id)])
            params.append(column_group_key)
            params += where_params
            queries.append(f"""
                (WITH aml_by_months AS (
                    SELECT DISTINCT ON (to_char(account_move_line.date, 'MM YYYY'))
                        to_char(account_move_line.date, 'MM YYYY') AS month,
                        to_char(account_move_line.date, 'fmMon YYYY') AS display_month,
                        %s AS column_group_key,
                        account_move_line.date
                    FROM {tables}
                    WHERE {where_clause}
                )
                SELECT column_group_key, month, display_month
                FROM aml_by_months
                ORDER BY date)
            """)

        self._cr.execute(' UNION ALL '.join(queries), params)
        result = {}
        for aml_result in self._cr.dictfetchall():
            result.setdefault(aml_result['month'], {column_group_key: {} for column_group_key in options['column_groups']})
            result[aml_result['month']][aml_result['column_group_key']] = aml_result

        return result

    def _get_journal_initial_balance(self, options, journal_id, date_month=False):
        queries = []
        params = []
        report = self.env['account.report'].browse(options['report_id'])
        for column_group_key, options_group in report._split_options_per_column_group(options).items():
            new_options = self.env['account.general.ledger.report.handler']._get_options_initial_balance(options_group)
            tables, where_clause, where_params = report._query_get(new_options, 'normal', domain=[('journal_id', '=', journal_id)])
            params.append(column_group_key)
            params += where_params
            queries.append(f"""
                SELECT
                    %s AS column_group_key,
                    SUM(account_move_line.balance) AS balance
                FROM {tables}
                JOIN account_journal journal ON journal.id = account_move_line.journal_id AND account_move_line.account_id = journal.default_account_id
                WHERE {where_clause}
                GROUP BY journal.id
            """)

        self._cr.execute(' UNION ALL '.join(queries), params)

        init_balance_by_col_group = {column_group_key: 0.0 for column_group_key in options['column_groups']}
        for result_row in self._cr.dictfetchall():
            init_balance_by_col_group[result_row['column_group_key']] = result_row['balance']
        return init_balance_by_col_group

    def _get_aml_line(self, options, parent_key, eval_dict, line_index, journal, is_unreconciled_payment):
        report = self.env['account.report'].browse(options['report_id'])
        currency = self._atlax_get_report_currency(report, options)
        columns = []
        general_vals = next(col_group_val for col_group_val in eval_dict.values())
        if general_vals['journal_type'] == 'bank' and general_vals['account_type'] in ('liability_credit_card', 'asset_cash'):
            return None

        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            values = eval_dict[column_group_key]
            raw_amount = float(values.get('amount_currency') or 0.0)
            split_amounts = self._atlax_split_amount(raw_amount)
            if values['journal_type'] == 'bank':
                not_receivable_with_partner = values['partner_name'] and values['account_type'] not in ('asset_receivable', 'liability_payable')
                account_name = '%s %s' % (values['account_code'], '' if values['partner_name'] else values['account_name'])
                account_name_col = {
                    'name': account_name,
                    'class': 'o_account_report_line_ellipsis' + (' color-blue' if not_receivable_with_partner else ''),
                    'name_right': values.get('partner_name'),
                    'style': 'text-align:left;',
                    'template': 'account_reports.cell_template_journal_audit_report',
                }
            else:
                account_name_col = {
                    'name': '%s %s' % (values['account_code'], values['account_name']),
                    'class': 'o_account_report_line_ellipsis',
                    'style': 'text-align:left;',
                }

            columns.extend([
                account_name_col,
                {'name': values['name'], 'class': 'o_account_report_line_ellipsis', 'style': 'text-align:left;'},
                self._atlax_make_cell(split_amounts['debit'], currency),
                self._atlax_make_cell(split_amounts['credit'], currency),
            ] + self._get_move_line_additional_col(column_group_options, False, values, is_unreconciled_payment))

        return {
            'id': report._get_generic_line_id('account.move.line', general_vals['move_line_id'], parent_line_id=parent_key),
            'name': self._get_aml_line_name(options, journal, line_index, eval_dict, is_unreconciled_payment),
            'level': 3,
            'parent_id': parent_key,
            'columns': columns,
            'class': 'o_account_reports_ja_name_muted',
            'atlax_currency_id': currency.id,
        }