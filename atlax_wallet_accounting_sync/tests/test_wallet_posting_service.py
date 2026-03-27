# -*- coding: utf-8 -*-

from odoo import fields
from odoo.tests.common import SavepointCase, tagged


@tagged("post_install", "-at_install")
class TestWalletPostingService(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.company
        cls.posting_date = fields.Date.context_today(cls.company)

        # Use company currency as source currency to keep source-side company amounts deterministic.
        cls.source_res_currency = cls.company.currency_id
        source_code = cls.source_res_currency.name

        candidate_codes = ["NGN", "USD", "EUR", "GBP", "GHS", "KES", "CAD"]
        destination_res_currency = cls.env["res.currency"].with_context(active_test=False).search(
            [
                ("name", "in", candidate_codes),
                ("name", "!=", source_code),
            ],
            limit=1,
        )
        if not destination_res_currency:
            destination_res_currency = cls.env["res.currency"].with_context(active_test=False).create(
                {
                    "name": "NGN",
                    "symbol": "₦",
                    "rounding": 0.01,
                    "active": True,
                }
            )
        elif not destination_res_currency.active:
            destination_res_currency.active = True
        cls.destination_res_currency = destination_res_currency

        cls.supported_src = cls.env["supported.currency"].create(
            {
                "currency_code": source_code,
                "name": f"Supported {source_code}",
                "symbol": source_code,
                "status": True,
            }
        )
        cls.supported_dst = cls.env["supported.currency"].create(
            {
                "currency_code": cls.destination_res_currency.name,
                "name": f"Supported {cls.destination_res_currency.name}",
                "symbol": cls.destination_res_currency.symbol or cls.destination_res_currency.name,
                "status": True,
            }
        )
        cls.supported_foreign_src = cls.supported_dst

        cls.customer_partner = cls.env["res.partner"].create(
            {
                "name": "Customer A",
                "is_atlax_customer": True,
                "business_id": "TWS-CUST-A",
            }
        )
        cls.provider_partner = cls.env["res.partner"].create({"name": "Provider A"})
        cls.non_atlax_partner = cls.env["res.partner"].create({"name": "Customer B"})

        Account = cls.env["account.account"]
        cls.acc_bank_src = Account.create(
            {
                "name": "TWS Bank Settlement Source",
                "code": "TWSBSRC",
                "account_type": "asset_cash",
                "company_id": cls.company.id,
            }
        )
        cls.acc_bank_dst = Account.create(
            {
                "name": "TWS Bank Settlement Destination",
                "code": "TWSBDST",
                "account_type": "asset_cash",
                "company_id": cls.company.id,
            }
        )
        cls.acc_bank_same = Account.create(
            {
                "name": "TWS Bank Settlement Same Currency",
                "code": "TWSBSAM",
                "account_type": "asset_cash",
                "company_id": cls.company.id,
            }
        )
        cls.acc_wallet_liability = Account.create(
            {
                "name": "TWS Customer Wallet Liability",
                "code": "TWSWAL",
                "account_type": "liability_current",
                "company_id": cls.company.id,
                "reconcile": True,
            }
        )
        cls.acc_payout_clearing = Account.create(
            {
                "name": "TWS Payout Clearing",
                "code": "TWSPCLR",
                "account_type": "liability_current",
                "company_id": cls.company.id,
                "reconcile": True,
            }
        )
        cls.acc_fee_income = Account.create(
            {
                "name": "TWS Fee Income",
                "code": "TWSFEE",
                "account_type": "income",
                "company_id": cls.company.id,
            }
        )
        cls.acc_fx_position = Account.create(
            {
                "name": "TWS FX Position",
                "code": "TWSFXP",
                "account_type": "asset_current",
                "company_id": cls.company.id,
                "reconcile": True,
            }
        )

        Journal = cls.env["account.journal"]
        cls.journal_wlt = Journal.create(
            {
                "name": "TWS Wallet Ops",
                "code": "TWL1",
                "type": "general",
                "company_id": cls.company.id,
            }
        )
        cls.journal_pay = Journal.create(
            {
                "name": "TWS Payout Ops",
                "code": "TPY1",
                "type": "general",
                "company_id": cls.company.id,
            }
        )
        cls.journal_try = Journal.create(
            {
                "name": "TWS Treasury",
                "code": "TTR1",
                "type": "general",
                "company_id": cls.company.id,
            }
        )

        Mapping = cls.env["wallet.account.map"]
        cls.funding_mapping = Mapping.create(
            {
                "name": f"Funding {source_code}",
                "company_id": cls.company.id,
                "source_currency_id": cls.supported_src.id,
                "destination_currency_id": False,
                "bank_settlement_account_id": cls.acc_bank_src.id,
                "wallet_liability_account_id": cls.acc_wallet_liability.id,
                "funding_journal_id": cls.journal_wlt.id,
            }
        )
        cls.payout_mapping = Mapping.create(
            {
                "name": f"Payout {source_code}->{cls.supported_dst.currency_code}",
                "company_id": cls.company.id,
                "source_currency_id": cls.supported_src.id,
                "destination_currency_id": cls.supported_dst.id,
                "bank_settlement_account_id": cls.acc_bank_dst.id,
                "wallet_liability_account_id": cls.acc_wallet_liability.id,
                "payout_clearing_account_id": cls.acc_payout_clearing.id,
                "fee_income_account_id": cls.acc_fee_income.id,
                "fx_position_account_id": cls.acc_fx_position.id,
                "payout_journal_id": cls.journal_pay.id,
                "treasury_journal_id": cls.journal_try.id,
            }
        )
        cls.same_currency_payout_mapping = Mapping.create(
            {
                "name": f"Payout {source_code}->{source_code}",
                "company_id": cls.company.id,
                "source_currency_id": cls.supported_src.id,
                "destination_currency_id": cls.supported_src.id,
                "bank_settlement_account_id": cls.acc_bank_same.id,
                "wallet_liability_account_id": cls.acc_wallet_liability.id,
                "payout_clearing_account_id": cls.acc_payout_clearing.id,
                "fee_income_account_id": cls.acc_fee_income.id,
                "payout_journal_id": cls.journal_pay.id,
                "treasury_journal_id": cls.journal_try.id,
            }
        )

    def _datetime_on_posting_date(self, hour):
        return f"{self.posting_date} {hour:02d}:00:00"

    def _create_funding_ledger(self, reference, amount, customer_name="Customer A", partner=None):
        return self.env["atlaxchange.ledger"].create(
            {
                "datetime": self._datetime_on_posting_date(10),
                "transaction_reference": reference,
                "customer_name": customer_name,
                "partner_id": partner.id if partner else False,
                "wallet": self.supported_src.id,
                "amount": amount,
                "total_amount": amount,
                "fee": 0.0,
                "status": "success",
                "transfer_direction": "credit",
            }
        )

    def _create_payout_ledger(self, reference, amount, fee, destination_amount, wallet=None, destination_currency=None, hour=11, customer_name="Customer A", partner=None):
        wallet = wallet or self.supported_src
        destination_currency = destination_currency or self.supported_dst
        return self.env["atlaxchange.ledger"].create(
            {
                "datetime": self._datetime_on_posting_date(hour),
                "transaction_reference": reference,
                "customer_name": customer_name,
                "partner_id": partner.id if partner else False,
                "service_name": "Provider A",
                "wallet": wallet.id,
                "amount": amount,
                "fee": fee,
                "conversion_rate": 1.0,
                "destination_currency": destination_currency.id,
                "total_amount": destination_amount,
                "status": "success",
                "transfer_direction": "debit",
            }
        )

    def _ensure_foreign_to_source_payout_mapping(self):
        mapping = self.env["wallet.account.map"].search(
            [
                ("company_id", "=", self.company.id),
                ("source_currency_id", "=", self.supported_foreign_src.id),
                ("destination_currency_id", "=", self.supported_src.id),
            ],
            limit=1,
        )
        if mapping:
            return mapping

        return self.env["wallet.account.map"].create(
            {
                "name": f"Payout {self.supported_foreign_src.currency_code}->{self.supported_src.currency_code}",
                "company_id": self.company.id,
                "source_currency_id": self.supported_foreign_src.id,
                "destination_currency_id": self.supported_src.id,
                "bank_settlement_account_id": self.acc_bank_same.id,
                "wallet_liability_account_id": self.acc_wallet_liability.id,
                "payout_clearing_account_id": self.acc_payout_clearing.id,
                "fee_income_account_id": self.acc_fee_income.id,
                "fx_position_account_id": self.acc_fx_position.id,
                "payout_journal_id": self.journal_pay.id,
                "treasury_journal_id": self.journal_try.id,
            }
        )

    def test_funding_aggregate_daily_by_source_currency(self):
        self._create_funding_ledger("FUND-001", 100.0)
        self._create_funding_ledger("FUND-002", 40.0)

        postings = self.env["wallet.posting.service"].post_funding_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 1)

        posting = postings[0]
        self.assertEqual(posting.posting_type, "funding")
        self.assertEqual(posting.ledger_count, 2)
        self.assertEqual(posting.state, "posted")

        move = posting.journal_entry_id
        bank_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_bank_src)
        wallet_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_wallet_liability)
        self.assertEqual(len(bank_line), 1)
        self.assertEqual(len(wallet_line), 1)
        self.assertAlmostEqual(bank_line.debit, 140.0, places=2)
        self.assertAlmostEqual(wallet_line.credit, 140.0, places=2)
        self.assertEqual(wallet_line.partner_id, self.customer_partner)

    def test_non_atlax_customer_ledgers_are_excluded_from_posting(self):
        self._create_funding_ledger("FUND-SKIP-001", 25.0, customer_name="Customer B", partner=self.non_atlax_partner)

        postings = self.env["wallet.posting.service"].post_funding_aggregations(posting_date=self.posting_date)

        self.assertFalse(postings)
        self.assertFalse(
            self.env["wallet.accounting.posting"].search([
                ("ledger_ids.transaction_reference", "=", "FUND-SKIP-001"),
            ])
        )

    def test_wallet_debit_aggregate_by_source_currency(self):
        self._create_payout_ledger("PAY-001", 10.0, 1.0, 10000.0)
        self._create_payout_ledger("PAY-002", 20.0, 2.0, 20000.0)

        postings = self.env["wallet.posting.service"].post_wallet_debit_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 1)

        posting = postings[0]
        self.assertEqual(posting.posting_type, "wallet_debit")
        self.assertEqual(posting.state, "posted")

        move = posting.journal_entry_id
        wallet_lines = move.line_ids.filtered(lambda line: line.account_id == self.acc_wallet_liability)
        principal_wallet_line = wallet_lines.filtered(lambda line: "principal" in (line.name or "").lower())
        fee_wallet_line = wallet_lines.filtered(lambda line: "fee" in (line.name or "").lower())
        fx_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_fx_position)
        fee_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_fee_income)

        self.assertEqual(len(wallet_lines), 2)
        self.assertEqual(len(principal_wallet_line), 1)
        self.assertEqual(len(fee_wallet_line), 1)
        self.assertEqual(len(fx_line), 1)
        self.assertEqual(len(fee_line), 1)
        self.assertAlmostEqual(principal_wallet_line.debit, 30.0, places=2)
        self.assertAlmostEqual(fee_wallet_line.debit, 3.0, places=2)
        self.assertAlmostEqual(fx_line.credit, 30.0, places=2)
        self.assertAlmostEqual(fee_line.credit, 3.0, places=2)
        self.assertEqual(principal_wallet_line.partner_id, self.customer_partner)
        self.assertEqual(fee_wallet_line.partner_id, self.customer_partner)
        self.assertTrue(move.is_wallet_sync_move)
        self.assertEqual(move.wallet_posting_type, "wallet_debit")
        self.assertTrue(all(line.wallet_sync_move for line in move.line_ids))
        self.assertTrue(all(line.wallet_posting_type == "wallet_debit" for line in move.line_ids))

    def test_same_currency_wallet_debit_uses_payout_clearing(self):
        self._create_payout_ledger("PAY-SAME-001", 10.0, 1.0, 10.0, destination_currency=self.supported_src, hour=12)
        self._create_payout_ledger("PAY-SAME-002", 20.0, 2.0, 20.0, destination_currency=self.supported_src, hour=13)

        postings = self.env["wallet.posting.service"].post_wallet_debit_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 1)

        posting = postings[0]
        self.assertEqual(posting.posting_type, "wallet_debit")
        self.assertEqual(posting.destination_currency_id, self.supported_src)
        self.assertIn("same_currency", posting.aggregation_key)

        move = posting.journal_entry_id
        wallet_lines = move.line_ids.filtered(lambda line: line.account_id == self.acc_wallet_liability)
        principal_wallet_line = wallet_lines.filtered(lambda line: "principal" in (line.name or "").lower())
        fee_wallet_line = wallet_lines.filtered(lambda line: "fee" in (line.name or "").lower())
        clearing_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_payout_clearing)
        fx_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_fx_position)
        fee_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_fee_income)

        self.assertEqual(len(principal_wallet_line), 1)
        self.assertEqual(len(fee_wallet_line), 1)
        self.assertEqual(len(clearing_line), 1)
        self.assertEqual(len(fx_line), 0)
        self.assertEqual(len(fee_line), 1)
        self.assertAlmostEqual(principal_wallet_line.debit, 30.0, places=2)
        self.assertAlmostEqual(fee_wallet_line.debit, 3.0, places=2)
        self.assertAlmostEqual(clearing_line.credit, 30.0, places=2)
        self.assertAlmostEqual(fee_line.credit, 3.0, places=2)

    def test_customer_lookup_prefers_unique_atlax_customer(self):
        company_partner = self.env["res.partner"].create(
            {
                "name": "Riz Remit Limited",
                "is_company": True,
            }
        )
        atlax_customer = self.env["res.partner"].create(
            {
                "name": "Muhammad Rizwan Javeed",
                "company_name": "Riz Remit Limited ",
                "parent_id": company_partner.id,
                "is_atlax_customer": True,
                "business_id": "56738ffb-b5ce-41a7-b6b1-f3da52eaa784",
                "external_user_id": "01c03ba1-c3eb-4b35-a653-4dad95ee3ad4",
            }
        )

        partner = self.env["wallet.posting.service"]._find_partner_by_name(
            "Riz Remit Limited",
            allow_company_name=True,
            role_label="Customer partner",
            prefer_atlax_customer=True,
        )

        self.assertEqual(partner, atlax_customer)

    def test_wallet_debit_splits_same_and_cross_currency_groups(self):
        self._create_payout_ledger("PAY-MIX-SAME", 10.0, 1.0, 10.0, destination_currency=self.supported_src, hour=14)
        self._create_payout_ledger("PAY-MIX-CROSS", 20.0, 2.0, 20000.0, destination_currency=self.supported_dst, hour=15)

        postings = self.env["wallet.posting.service"].post_wallet_debit_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 2)

        same_posting = postings.filtered(lambda rec: rec.destination_currency_id == self.supported_src)
        cross_posting = postings - same_posting

        self.assertEqual(len(same_posting), 1)
        self.assertEqual(len(cross_posting), 1)
        self.assertIn("same_currency", same_posting.aggregation_key)
        self.assertIn("cross_currency", cross_posting.aggregation_key)
        self.assertTrue(same_posting.journal_entry_id.line_ids.filtered(lambda line: line.account_id == self.acc_payout_clearing))
        self.assertTrue(cross_posting.journal_entry_id.line_ids.filtered(lambda line: line.account_id == self.acc_fx_position))

    def test_destination_settlement_aggregate_by_destination_currency(self):
        self._create_payout_ledger("SET-001", 10.0, 1.0, 10000.0)
        self._create_payout_ledger("SET-002", 20.0, 2.0, 20000.0)

        postings = self.env["wallet.posting.service"].post_destination_settlement_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 1)

        posting = postings[0]
        self.assertEqual(posting.posting_type, "destination_settlement")
        self.assertEqual(posting.destination_amount, 30000.0)
        self.assertEqual(posting.state, "posted")

        move = posting.journal_entry_id
        bank_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_bank_dst)
        clearing_line = move.line_ids.filtered(lambda line: line.account_id == self.acc_payout_clearing)
        self.assertEqual(len(bank_line), 1)
        self.assertEqual(len(clearing_line), 1)

        self.assertEqual(bank_line.currency_id, self.destination_res_currency)
        self.assertEqual(clearing_line.currency_id, self.destination_res_currency)
        self.assertAlmostEqual(bank_line.amount_currency, 30000.0, places=2)
        self.assertAlmostEqual(clearing_line.amount_currency, -30000.0, places=2)
        self.assertEqual(clearing_line.partner_id, self.provider_partner)

    def test_partner_ledger_includes_payout_partner(self):
        self._create_payout_ledger("SET-PL-001", 10.0, 1.0, 10000.0)

        postings = self.env["wallet.posting.service"].post_destination_settlement_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 1)

        report = self.env.ref("atlax_wallet_accounting_sync.atlax_partner_ledger_report")
        options = report._get_options({"report_id": report.id})
        handler = self.env["atlax.partner.ledger.report.handler"]

        partner_lines, totals_by_column_group, dummy_partner_values = handler._build_partner_lines(report, options)

        self.assertTrue(any(line["name"] == self.provider_partner.name for line in partner_lines))
        self.assertTrue(any(values.get("credit") for values in totals_by_column_group.values()))

    def test_destination_settlement_splits_same_and_cross_currency_groups(self):
        self._ensure_foreign_to_source_payout_mapping()
        self._create_payout_ledger("SET-MIX-SAME", 10.0, 1.0, 10.0, destination_currency=self.supported_src, hour=16)
        self._create_payout_ledger(
            "SET-MIX-CROSS",
            20.0,
            2.0,
            20.0,
            wallet=self.supported_foreign_src,
            destination_currency=self.supported_src,
            hour=17,
        )

        postings = self.env["wallet.posting.service"].post_destination_settlement_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 2)

        same_posting = postings.filtered(lambda rec: rec.source_currency_id == self.supported_src)
        cross_posting = postings - same_posting
        self.assertEqual(len(same_posting), 1)
        self.assertEqual(len(cross_posting), 1)
        self.assertIn("same_currency", same_posting.aggregation_key)
        self.assertIn("cross_currency", cross_posting.aggregation_key)

        same_move = same_posting.journal_entry_id
        same_bank_line = same_move.line_ids.filtered(lambda line: line.account_id == self.acc_bank_same)
        same_clearing_line = same_move.line_ids.filtered(lambda line: line.account_id == self.acc_payout_clearing)
        self.assertEqual(len(same_bank_line), 1)
        self.assertEqual(len(same_clearing_line), 1)
        self.assertAlmostEqual(same_bank_line.credit, 10.0, places=2)
        self.assertAlmostEqual(same_clearing_line.debit, 10.0, places=2)
        self.assertEqual(same_clearing_line.partner_id, self.provider_partner)

        cross_move = cross_posting.journal_entry_id
        cross_bank_line = cross_move.line_ids.filtered(lambda line: line.account_id == self.acc_bank_same)
        cross_clearing_line = cross_move.line_ids.filtered(lambda line: line.account_id == self.acc_payout_clearing)
        self.assertEqual(len(cross_bank_line), 1)
        self.assertEqual(len(cross_clearing_line), 1)
        self.assertAlmostEqual(cross_bank_line.debit, 20.0, places=2)
        self.assertAlmostEqual(cross_clearing_line.credit, 20.0, places=2)
        self.assertEqual(cross_clearing_line.partner_id, self.provider_partner)

    def test_aggregate_idempotency_skips_already_logged_rows(self):
        self._create_funding_ledger("FUND-IDEMP", 25.0)

        service = self.env["wallet.posting.service"]
        first = service.post_funding_aggregations(posting_date=self.posting_date)
        second = service.post_funding_aggregations(posting_date=self.posting_date)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)
        self.assertEqual(
            self.env["wallet.accounting.posting"].search_count(
                [("posting_type", "=", "funding"), ("posting_date", "=", self.posting_date)]
            ),
            1,
        )

    def test_retry_error_posting_after_mapping_fix(self):
        gbp_res_currency = self.env["res.currency"].with_context(active_test=False).search([("name", "=", "GBP")], limit=1)
        if gbp_res_currency and not gbp_res_currency.active:
            gbp_res_currency.active = True

        supported_gbp = self.env["supported.currency"].create(
            {
                "currency_code": "GBP",
                "name": "Supported GBP",
                "symbol": "£",
                "status": True,
            }
        )

        ledger = self.env["atlaxchange.ledger"].create(
            {
                "datetime": self._datetime_on_posting_date(12),
                "transaction_reference": "FUND-GBP-ERR",
                "customer_name": "Customer A",
                "wallet": supported_gbp.id,
                "amount": 55.0,
                "total_amount": 55.0,
                "fee": 0.0,
                "status": "success",
                "transfer_direction": "credit",
            }
        )

        postings = self.env["wallet.posting.service"].post_funding_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 1)
        posting = postings[0]
        self.assertEqual(posting.state, "error")
        self.assertIn(ledger, posting.ledger_ids)

        self.env["wallet.account.map"].create(
            {
                "name": "Funding GBP",
                "company_id": self.company.id,
                "source_currency_id": supported_gbp.id,
                "destination_currency_id": False,
                "bank_settlement_account_id": self.acc_bank_src.id,
                "wallet_liability_account_id": self.acc_wallet_liability.id,
                "funding_journal_id": self.journal_wlt.id,
            }
        )

        posting.action_retry()
        posting = self.env["wallet.accounting.posting"].browse(posting.id)
        self.assertEqual(posting.state, "posted")
        self.assertTrue(posting.journal_entry_id)

    def test_deleted_journal_entry_can_be_recreated(self):
        self._create_funding_ledger("FUND-DEL-001", 12.5)

        service = self.env["wallet.posting.service"]
        postings = service.post_funding_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(postings), 1)
        posting = postings[0]
        move = posting.journal_entry_id
        self.assertTrue(move)

        move.unlink()
        posting.invalidate_recordset()
        self.assertFalse(posting.journal_entry_id)

        rerun = service.post_funding_aggregations(posting_date=self.posting_date)
        self.assertEqual(len(rerun), 1)
        posting = self.env["wallet.accounting.posting"].browse(posting.id)
        self.assertEqual(posting.state, "posted")
        self.assertTrue(posting.journal_entry_id)

    def test_foreign_currency_source_amount_uses_company_currency_and_keeps_wallet_display(self):
        if self.supported_foreign_src == self.supported_src:
            return

        foreign_wallet_liability = self.env["account.account"].create(
            {
                "name": "TWS Foreign Wallet Liability",
                "code": "TWSFWL",
                "account_type": "liability_current",
                "company_id": self.company.id,
                "reconcile": True,
                "currency_id": self.destination_res_currency.id,
            }
        )
        foreign_bank = self.env["account.account"].create(
            {
                "name": "TWS Foreign Bank Settlement",
                "code": "TWSFBS",
                "account_type": "asset_cash",
                "company_id": self.company.id,
                "currency_id": self.destination_res_currency.id,
            }
        )
        self.env["wallet.account.map"].create(
            {
                "name": f"Funding {self.supported_foreign_src.currency_code}",
                "company_id": self.company.id,
                "source_currency_id": self.supported_foreign_src.id,
                "destination_currency_id": False,
                "bank_settlement_account_id": foreign_bank.id,
                "wallet_liability_account_id": foreign_wallet_liability.id,
                "funding_journal_id": self.journal_wlt.id,
            }
        )

        self.env["atlaxchange.ledger"].create(
            {
                "datetime": self._datetime_on_posting_date(13),
                "transaction_reference": "FUND-FOREIGN-001",
                "customer_name": "Customer A",
                "wallet": self.supported_foreign_src.id,
                "amount": 0.08,
                "total_amount": 0.08,
                "fee": 0.0,
                "status": "success",
                "transfer_direction": "credit",
            }
        )

        posting = self.env["wallet.posting.service"].post_funding_aggregations(posting_date=self.posting_date).filtered(
            lambda rec: rec.source_currency_id == self.supported_foreign_src
        )
        self.assertEqual(len(posting), 1)
        move = posting.journal_entry_id

        bank_line = move.line_ids.filtered(lambda line: line.account_id == foreign_bank)
        wallet_line = move.line_ids.filtered(lambda line: line.account_id == foreign_wallet_liability)
        self.assertEqual(len(bank_line), 1)
        self.assertEqual(len(wallet_line), 1)

        expected_company_amount = self.destination_res_currency._convert(
            0.08,
            self.company.currency_id,
            self.company,
            self.posting_date,
        )

        self.assertAlmostEqual(bank_line.debit, expected_company_amount, places=2)
        self.assertAlmostEqual(wallet_line.credit, expected_company_amount, places=2)
        self.assertEqual(bank_line.currency_id, self.destination_res_currency)
        self.assertEqual(wallet_line.currency_id, self.destination_res_currency)
        self.assertAlmostEqual(bank_line.amount_currency, 0.08, places=2)
        self.assertAlmostEqual(wallet_line.amount_currency, -0.08, places=2)
        self.assertAlmostEqual(bank_line.wallet_display_debit, 0.08, places=2)
        self.assertAlmostEqual(bank_line.wallet_display_credit, 0.0, places=2)
        self.assertAlmostEqual(wallet_line.wallet_display_debit, 0.0, places=2)
        self.assertAlmostEqual(wallet_line.wallet_display_credit, 0.08, places=2)
        self.assertEqual(bank_line.wallet_display_currency_id, self.destination_res_currency)
        self.assertEqual(wallet_line.wallet_display_currency_id, self.destination_res_currency)

    def test_daily_cron_posts_all_three_aggregate_types(self):
        self.env["ir.config_parameter"].sudo().set_param("atlax_wallet_accounting_sync.cron_days_back", "0")
        self._create_funding_ledger("CRON-FUND-001", 75.0)
        self._create_payout_ledger("CRON-PAY-001", 15.0, 1.5, 15000.0)

        result = self.env["wallet.ledger.sync"].cron_post_daily_aggregates()
        self.assertGreaterEqual(result["dates_processed"], 1)
        self.assertEqual(result["funding_postings"], 1)
        self.assertEqual(result["wallet_debit_postings"], 1)
        self.assertEqual(result["destination_settlement_postings"], 1)
        self.assertEqual(result["total_postings"], 3)
