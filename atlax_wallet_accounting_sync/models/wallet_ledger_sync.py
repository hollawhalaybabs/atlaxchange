import logging

from datetime import timedelta

from odoo import api, fields, models, _


_logger = logging.getLogger(__name__)


class WalletLedgerSync(models.AbstractModel):
    """Cron entrypoint for posting aggregated wallet mirror moves by day/currency."""

    _name = "wallet.ledger.sync"
    _description = "Wallet Ledger Accounting Sync"

    @api.model
    def _get_cron_batch_limit(self):
        """Number of posting dates to process per cron run."""

        ICP = self.env["ir.config_parameter"].sudo()
        val = (ICP.get_param("atlax_wallet_accounting_sync.cron_batch_limit", "100") or "100").strip()
        try:
            return max(1, int(val))
        except Exception:
            return 100

    @api.model
    def _get_processing_date(self):
        ICP = self.env["ir.config_parameter"].sudo()
        val = (ICP.get_param("atlax_wallet_accounting_sync.cron_days_back", "1") or "1").strip()
        try:
            days_back = max(0, int(val))
        except Exception:
            days_back = 1
        return fields.Date.context_today(self) - timedelta(days=days_back)

    @api.model
    def cron_post_daily_aggregates(self):
        service = self.env["wallet.posting.service"].sudo()
        return service.post_all_outstanding_daily_aggregates(
            company=self.env.company,
            max_dates=self._get_cron_batch_limit(),
        )

    @api.model
    def cron_post_wallet_transactions(self):
        """Backward-compatible alias for older cron/server-action code.

        Some existing databases still have the cron/action code stored as
        `model.cron_post_wallet_transactions()` from the pre-refactor module.
        Keep this shim so those stale records continue to work until the DB
        record is updated.
        """

        _logger.warning(
            "wallet.ledger.sync.cron_post_wallet_transactions() is deprecated; redirecting to cron_post_daily_aggregates()."
        )
        return self.cron_post_daily_aggregates()

    @api.model
    def cron_post_historical_aggregates(self):
        service = self.env["wallet.posting.service"].sudo()
        return service.post_historical_aggregates(company=self.env.company)
