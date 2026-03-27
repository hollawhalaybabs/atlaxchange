from odoo import fields, models


class AccountReport(models.Model):
    _inherit = "account.report"

    atlax_custom_report = fields.Boolean(
        string="Atlax Custom Report",
        default=False,
        copy=False,
        help="Marks reports owned by the Atlax wallet reporting layer.",
    )
    atlax_wallet_scope = fields.Boolean(
        string="Wallet Scope",
        default=False,
        copy=False,
        help="Restrict this report to wallet-sync journal entries only.",
    )
    atlax_currency_filter = fields.Boolean(
        string="Wallet Currency Filter",
        default=False,
        copy=False,
        help="Expose an Atlax wallet currency selector on the report.",
    )

    def _get_options_initializers_forced_sequence_map(self):
        sequence_map = super()._get_options_initializers_forced_sequence_map()
        sequence_map[self._init_options_atlax_currency] = 250
        return sequence_map

    def _init_options_all_entries(self, options, previous_options=None):
        super()._init_options_all_entries(options, previous_options=previous_options)
        if self.atlax_custom_report and self.filter_show_draft and not previous_options:
            options['all_entries'] = True

    def _init_options_atlax_currency(self, options, previous_options=None):
        self.ensure_one()
        if not (self.atlax_custom_report and self.atlax_currency_filter):
            return

        domain = [
            ('company_id', 'in', self.get_report_company_ids(options)),
            ('currency_id', '!=', False),
        ]
        if self.atlax_wallet_scope:
            domain.append(('move_id.is_wallet_sync_move', '=', True))

        currency_groups = self.env['account.move.line'].read_group(domain, ['currency_id'], ['currency_id'])
        currency_ids = sorted({group['currency_id'][0] for group in currency_groups if group.get('currency_id')})
        currencies = self.env['res.currency'].browse(currency_ids)

        options['atlax_available_currencies'] = [
            {
                'id': currency.id,
                'name': currency.name,
                'symbol': currency.symbol or currency.name,
            }
            for currency in currencies
        ]

        previous_currency_id = False
        if previous_options and previous_options.get('atlax_currency_id'):
            try:
                previous_currency_id = int(previous_options['atlax_currency_id'])
            except (TypeError, ValueError):
                previous_currency_id = False

        selected_currency = currencies.filtered(lambda currency: currency.id == previous_currency_id)[:1] or currencies[:1]
        options['atlax_currency_id'] = selected_currency.id if selected_currency else False
        options['atlax_selected_currency'] = selected_currency and {
            'id': selected_currency.id,
            'name': selected_currency.name,
            'symbol': selected_currency.symbol or selected_currency.name,
        } or False

    def _get_options_domain(self, options, date_scope):
        domain = super()._get_options_domain(options, date_scope)
        if self.atlax_custom_report and self.atlax_wallet_scope:
            domain.append(('move_id.is_wallet_sync_move', '=', True))
        if self.atlax_custom_report and options.get('atlax_currency_id'):
            domain.append(('currency_id', '=', int(options['atlax_currency_id'])))
        return domain

    def _atlax_get_report_currency(self, options):
        self.ensure_one()
        currency_id = options.get('atlax_currency_id')
        if not currency_id:
            return self.env['res.currency']
        try:
            currency_id = int(currency_id)
        except (TypeError, ValueError):
            return self.env['res.currency']
        return self.env['res.currency'].browse(currency_id).exists()

    def _format_lines_for_display(self, lines, options):
        lines = super()._format_lines_for_display(lines, options)

        if not self.atlax_custom_report:
            return lines

        report_currency = self._atlax_get_report_currency(options)
        if not report_currency:
            return lines

        currency_model = self.env['res.currency']
        for line in lines:
            line_currency = currency_model.browse(line.get('atlax_currency_id')).exists() if line.get('atlax_currency_id') else report_currency
            for index, column in enumerate(options.get('columns', [])):
                if column.get('figure_type') != 'monetary':
                    continue
                if index >= len(line.get('columns', [])):
                    continue

                cell = line['columns'][index]
                if cell.get('no_format') is None:
                    continue
                if cell.get('atlax_skip_currency_format'):
                    continue

                cell_currency = currency_model.browse(cell.get('atlax_currency_id')).exists() if cell.get('atlax_currency_id') else line_currency
                blank_if_zero = cell.get('atlax_blank_if_zero')
                if blank_if_zero is None:
                    blank_if_zero = column.get('blank_if_zero', False)

                cell['name'] = self.format_value(
                    cell['no_format'],
                    currency=cell_currency,
                    blank_if_zero=blank_if_zero,
                    figure_type='monetary',
                )

        return lines