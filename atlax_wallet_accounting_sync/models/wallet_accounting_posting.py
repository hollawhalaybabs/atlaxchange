import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class WalletAccountingPosting(models.Model):
    """Posting log / idempotency protection.

    This model is the audit trail for every aggregated mirror posting that is
    created from one or more ledger rows. It prevents duplicated processing by
    retaining the exact ledger set included in each aggregated move.

    Interpretation:
    - state=draft: log created but move not created yet (or in-progress).
    - state=posted: draft journal entry created successfully.
    - state=skipped: intentionally skipped (optional).
    - state=error: failed validation / missing config / missing partner.
    """

    _name = "wallet.accounting.posting"
    _description = "Wallet Accounting Posting Log"
    _order = "posting_date desc, posted_at desc, id desc"

    name = fields.Char(index=True)
    aggregation_key = fields.Char(index=True, copy=False)
    posting_type = fields.Selection(
        [
            ("funding", "Funding Aggregate"),
            ("wallet_debit", "Wallet Debit Aggregate"),
            ("destination_settlement", "Destination Settlement Aggregate"),
        ],
        index=True,
    )
    posting_date = fields.Date(index=True)

    transaction_reference = fields.Char(required=True, index=True)
    transaction_direction = fields.Selection(
        [
            ("credit", "Wallet Funding (credit)"),
            ("debit", "Customer Payout (debit)"),
        ],
        required=True,
        index=True,
    )

    ledger_record_id = fields.Many2one(
        "atlaxchange.ledger",
        string="Ledger Record",
        index=True,
        ondelete="set null",
    )
    journal_entry_id = fields.Many2one(
        "account.move",
        string="Journal Entry",
        index=True,
        ondelete="set null",
    )

    posted_at = fields.Datetime(index=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("posted", "Posted"),
            ("skipped", "Skipped"),
            ("error", "Error"),
        ],
        required=True,
        default="draft",
        index=True,
    )
    error_message = fields.Text()

    source_currency_id = fields.Many2one("supported.currency", index=True)
    destination_currency_id = fields.Many2one("supported.currency", index=True)

    principal_amount = fields.Float(string="Principal Amount")
    fee_amount = fields.Float(string="Fee Amount")
    destination_amount = fields.Float(string="Destination Amount")
    customer_rate = fields.Float(string="Customer Rate")

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    ledger_ids = fields.Many2many(
        "atlaxchange.ledger",
        "wallet_accounting_posting_ledger_rel",
        "posting_id",
        "ledger_id",
        string="Ledger Rows",
    )
    ledger_count = fields.Integer(string="Ledger Count", default=0, readonly=True)

    _sql_constraints = [
        (
            "wallet_accounting_posting_unique",
            "unique(transaction_reference, transaction_direction)",
            "A posting log already exists for this transaction reference and direction.",
        ),
        (
            "wallet_accounting_posting_aggregation_key_unique",
            "unique(aggregation_key)",
            "A posting log already exists for this aggregate key.",
        )
    ]

    def action_open_journal_entry(self):
        self.ensure_one()
        if not self.journal_entry_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Journal Entry"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.journal_entry_id.id,
            "target": "current",
        }

    def action_retry(self):
        self.ensure_one()

        if self.state != "error":
            return False

        if not self.ledger_ids:
            raise UserError(_("No ledger rows are linked to this posting log; cannot retry."))

        service = self.env["wallet.posting.service"].sudo()
        service.retry_posting_log(self)

        if self.journal_entry_id:
            return self.action_open_journal_entry()
        return False

    def action_rebuild_journal_entry(self):
        self.ensure_one()

        if not self.ledger_ids:
            raise UserError(_("No ledger rows are linked to this posting log; cannot rebuild."))

        move = self.journal_entry_id.exists() if self.journal_entry_id else self.env["account.move"]
        if move:
            if move.state != "draft":
                raise UserError(_("Only draft wallet journal entries can be rebuilt automatically."))
            move.unlink()

        service = self.env["wallet.posting.service"].sudo()
        service.retry_posting_log(self)

        if self.journal_entry_id:
            return self.action_open_journal_entry()
        return False
