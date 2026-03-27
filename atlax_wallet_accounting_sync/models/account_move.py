from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    is_wallet_sync_move = fields.Boolean(
        string="Wallet Sync Move",
        readonly=True,
        copy=False,
        index=True,
        help="Technical flag used to display wallet mirror amounts with the line currency symbol in journal items.",
    )
    wallet_posting_type = fields.Selection(
        [
            ("funding", "Funding Aggregate"),
            ("wallet_debit", "Wallet Debit Aggregate"),
            ("destination_settlement", "Destination Settlement Aggregate"),
        ],
        string="Wallet Posting Type",
        readonly=True,
        copy=False,
        index=True,
        help="Operational classification of a wallet-sync journal entry.",
    )
