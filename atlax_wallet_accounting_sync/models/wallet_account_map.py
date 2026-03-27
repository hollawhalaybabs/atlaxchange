import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class WalletAccountMap(models.Model):
    """Account mapping for wallet mirroring.

    This model is the configuration backbone for the sync:
    - For wallet funding (direction=credit): mapping is source-currency only.
    - For payouts (direction=debit): mapping is source + destination currency.

    The mapping determines which accounts/journals to use when generating draft
    journal entries in Odoo.
    """

    _name = "wallet.account.map"
    _description = "Wallet Account Mapping"
    _order = "company_id, source_currency_id, destination_currency_id, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    source_currency_id = fields.Many2one(
        "supported.currency",
        string="Source Currency",
        required=True,
        index=True,
    )
    destination_currency_id = fields.Many2one(
        "supported.currency",
        string="Destination Currency",
        help="Leave empty for source-only mappings (wallet funding).",
        index=True,
    )

    wallet_liability_account_id = fields.Many2one(
        "account.account",
        string="Wallet Liability Account",
        help="Customer wallet liability account for the source currency.",
    )
    payout_clearing_account_id = fields.Many2one(
        "account.account",
        string="Payout Clearing Account",
        help="Payout clearing liability account for the destination currency.",
    )
    bank_settlement_account_id = fields.Many2one(
        "account.account",
        string="Bank / Settlement Account",
        help="Settlement/bank account to mirror wallet funding receipts.",
    )

    fee_income_account_id = fields.Many2one(
        "account.account",
        string="Fee Income Account",
        help="Income account for transfer/withdrawal fees.",
    )
    fx_position_account_id = fields.Many2one(
        "account.account",
        string="FX Position Account",
        help="Source-currency internal FX/position account used for aggregated payout wallet-side principal credits.",
    )
    fx_adjustment_account_id = fields.Many2one(
        "account.account",
        string="FX Adjustment Account",
        help="Legacy field kept for compatibility. Daily aggregate postings no longer rely on FX adjustment lines.",
    )

    funding_journal_id = fields.Many2one(
        "account.journal",
        string="Funding Journal",
        help="Journal used for wallet funding (credit) entries.",
    )
    payout_journal_id = fields.Many2one(
        "account.journal",
        string="Payout Journal",
        help="Journal used for payout (debit) entries.",
    )
    treasury_journal_id = fields.Many2one(
        "account.journal",
        string="Treasury Journal",
        help="Reserved for later treasury postings (not used in Phase 1).",
    )
    fx_journal_id = fields.Many2one(
        "account.journal",
        string="FX Journal",
        help="Reserved for later FX postings (not used in Phase 1).",
    )

    _sql_constraints = [
        (
            "wallet_account_map_unique",
            "unique(source_currency_id, destination_currency_id, company_id)",
            "Only one mapping is allowed per (source currency, destination currency, company).",
        )
    ]

    @api.constrains("source_currency_id", "destination_currency_id", "company_id")
    def _check_unique_source_only_mapping(self):
        """PostgreSQL unique constraints allow multiple NULLs; enforce source-only uniqueness."""

        for rec in self:
            if not rec.source_currency_id or not rec.company_id:
                continue

            domain = [
                ("id", "!=", rec.id),
                ("company_id", "=", rec.company_id.id),
                ("source_currency_id", "=", rec.source_currency_id.id),
            ]

            # Explicitly include False destination in the domain.
            if rec.destination_currency_id:
                domain.append(("destination_currency_id", "=", rec.destination_currency_id.id))
            else:
                domain.append(("destination_currency_id", "=", False))

            if self.search_count(domain):
                raise ValidationError(
                    _(
                        "Only one mapping is allowed per (source currency, destination currency, company). "
                        "Please archive/modify the existing mapping instead of creating a duplicate."
                    )
                )

    @api.constrains(
        "bank_settlement_account_id",
        "wallet_liability_account_id",
        "destination_currency_id",
        "payout_clearing_account_id",
        "fee_income_account_id",
        "fx_position_account_id",
    )
    def _check_required_accounts_for_usage(self):
        """Validate source-only funding mappings vs source+destination payout mappings.

        - Funding mappings (source only) need settlement + wallet liability.
                - Same-currency payout mappings need payout clearing and fee income.
                - Cross-currency payout mappings also need FX position so wallet-side
                    principal is posted separately from destination settlement.
        """

        for rec in self:
            if not rec.source_currency_id:
                continue

            missing = []
            if not rec.bank_settlement_account_id:
                missing.append(_("Bank / Settlement Account"))
            if not rec.wallet_liability_account_id:
                missing.append(_("Wallet Liability Account"))

            if rec.destination_currency_id:
                same_currency_pair = rec.source_currency_id.currency_code == rec.destination_currency_id.currency_code
                if not rec.payout_clearing_account_id:
                    missing.append(_("Payout Clearing Account"))
                if not rec.fee_income_account_id:
                    missing.append(_("Fee Income Account"))
                if not same_currency_pair and not rec.fx_position_account_id:
                    missing.append(_("FX Position Account"))

            if missing:
                raise ValidationError(
                    _("The following fields are required for this mapping: %s") % ", ".join(missing)
                )
