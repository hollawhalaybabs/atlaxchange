from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    wallet_sync_move = fields.Boolean(
        related="move_id.is_wallet_sync_move",
        string="Wallet Sync Move",
        store=True,
        index=True,
        readonly=True,
    )
    wallet_posting_type = fields.Selection(
        related="move_id.wallet_posting_type",
        string="Wallet Posting Type",
        store=True,
        index=True,
        readonly=True,
    )

    wallet_display_currency_id = fields.Many2one(
        "res.currency",
        string="Wallet Display Currency",
        compute="_compute_wallet_display_fields",
    )
    wallet_display_debit = fields.Monetary(
        string="Debit",
        currency_field="wallet_display_currency_id",
        compute="_compute_wallet_display_fields",
    )
    wallet_display_credit = fields.Monetary(
        string="Credit",
        currency_field="wallet_display_currency_id",
        compute="_compute_wallet_display_fields",
    )
    wallet_display_balance = fields.Monetary(
        string="Net Amount",
        currency_field="wallet_display_currency_id",
        compute="_compute_wallet_display_fields",
    )

    @api.depends(
        "move_id.is_wallet_sync_move",
        "currency_id",
        "account_id.currency_id",
        "company_currency_id",
        "amount_currency",
        "debit",
        "credit",
    )
    def _compute_wallet_display_fields(self):
        for line in self:
            if line.move_id.is_wallet_sync_move:
                line.wallet_display_currency_id = line.currency_id or line.account_id.currency_id or line.company_currency_id
            else:
                line.wallet_display_currency_id = line.company_currency_id

            if line.move_id.is_wallet_sync_move and line.currency_id:
                line.wallet_display_debit = line.amount_currency if line.amount_currency > 0.0 else 0.0
                line.wallet_display_credit = -line.amount_currency if line.amount_currency < 0.0 else 0.0
                line.wallet_display_balance = line.amount_currency or 0.0
            else:
                line.wallet_display_debit = line.debit or 0.0
                line.wallet_display_credit = line.credit or 0.0
                line.wallet_display_balance = line.balance or 0.0
