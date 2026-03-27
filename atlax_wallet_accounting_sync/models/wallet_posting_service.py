import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero


_logger = logging.getLogger(__name__)


class WalletPostingService(models.AbstractModel):
    """Aggregate-first posting service for mirrored wallet transactions.

    Separation of responsibilities:
    - Funding (`direction=credit`) posts only the wallet funding leg in the
      source currency.
        - Payout wallet-side postings reduce customer wallet exposure in the source
            currency and credit either payout clearing (same-currency payouts) or
            Atlax's source-currency FX position / principal holding account
            (cross-currency payouts), plus fee income.
        - Payout destination settlement postings record the destination-currency
            settlement leg separately between payout clearing and bank settlement,
            with a reversed bank leg for same-currency payouts that settle through a
            normal asset account.

    This separation keeps customer wallet liability reporting aligned with the
    source wallet currency while keeping destination settlement operationally
    separate.
    """

    _name = "wallet.posting.service"
    _description = "Wallet Posting Service"

    # ------------------------------------------------------------------
    # Basic helpers
    # ------------------------------------------------------------------

    def _normalize_status(self, status):
        return (status or "").strip().lower()

    def _is_success_status(self, status):
        return self._normalize_status(status) == "success"

    def _currency_code(self, supported_currency):
        return (supported_currency.currency_code or "").strip().upper() if supported_currency else False

    def _is_same_currency_pair(self, source_currency, destination_currency):
        source_code = self._currency_code(source_currency)
        destination_code = self._currency_code(destination_currency)
        return bool(source_code and destination_code and source_code == destination_code)

    def _is_same_currency_ledger(self, ledger):
        return self._is_same_currency_pair(ledger.wallet, ledger.destination_currency)

    def _bank_settlement_is_asset(self, account):
        return bool(account and (account.account_type or "").startswith("asset"))

    def _infer_posting_variant(self, posting_type, ledgers):
        if posting_type not in ("wallet_debit", "destination_settlement") or not ledgers:
            return False

        variants = {"same_currency" if self._is_same_currency_ledger(ledger) else "cross_currency" for ledger in ledgers}
        if len(variants) > 1:
            raise UserError(
                _(
                    "Cannot build a single %(type)s aggregate from mixed same-currency and cross-currency ledger rows."
                )
                % {"type": posting_type}
            )
        return next(iter(variants), False)

    def _get_res_currency_from_supported(self, supported_currency):
        code = self._currency_code(supported_currency)
        if not code:
            return False
        return self.env["res.currency"].with_context(active_test=False).search([("name", "=", code)], limit=1)

    def _day_bounds(self, posting_date):
        posting_date = fields.Date.to_date(posting_date)
        start_dt = datetime.combine(posting_date, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)
        return fields.Datetime.to_string(start_dt), fields.Datetime.to_string(end_dt)

    def _get_move_date(self, posting_date, ledgers):
        if posting_date:
            return fields.Date.to_date(posting_date)
        if ledgers:
            first_dt = ledgers.sorted(lambda l: (l.datetime or fields.Datetime.now(), l.id))[0].datetime
            if first_dt:
                return fields.Date.to_date(first_dt)
        return fields.Date.context_today(self)

    def _fee_is_minor_units(self):
        ICP = self.env["ir.config_parameter"].sudo()
        val = (ICP.get_param("atlax_wallet_accounting_sync.fee_in_minor_units", "0") or "0").strip()
        return val in ("1", "true", "True", "yes", "y")

    def _normalize_amounts(self, ledger):
        principal_amount = abs(float(ledger.amount or 0.0))
        fee_amount = abs(float(ledger.fee or 0.0))
        destination_amount = abs(float(ledger.total_amount or 0.0))

        if self._fee_is_minor_units():
            fee_amount = fee_amount / 100.0

        return {
            "principal_amount": principal_amount,
            "fee_amount": fee_amount,
            "destination_amount": destination_amount,
        }

    def _normalize_partner_lookup_value(self, value):
        return " ".join((value or "").split()).strip()

    def _partner_lookup_fields(self, allow_company_name=True):
        field_names = ["name", "display_name"]
        if allow_company_name:
            field_names.extend(["company_name", "commercial_company_name"])
        return field_names

    def _partner_lookup_values(self, partner, allow_company_name=True):
        values = set()
        for field_name in self._partner_lookup_fields(allow_company_name=allow_company_name):
            normalized = self._normalize_partner_lookup_value(getattr(partner, field_name, False))
            if normalized:
                values.add(normalized.casefold())
        return values

    def _pick_unique_partner(self, partners, filters):
        for partner_filter in filters:
            filtered_partners = partner_filter(partners)
            if len(filtered_partners) == 1:
                return filtered_partners[0]
        return False

    def _is_atlax_customer_partner(self, partner):
        return bool(partner and partner.is_atlax_customer)

    def _prefer_unique_customer_partner(self, partners):
        return self._pick_unique_partner(
            partners,
            [
                lambda partner_recs: partner_recs.filtered(
                    lambda partner: partner.is_atlax_customer and (partner.business_id or partner.external_user_id)
                ),
                lambda partner_recs: partner_recs.filtered("is_atlax_customer"),
            ],
        )

    def _find_partner_by_name(self, name, *, allow_company_name=True, role_label="Partner", prefer_atlax_customer=False, require_atlax_customer=False):
        normalized_name = self._normalize_partner_lookup_value(name)
        if not normalized_name:
            raise UserError(_("%s name is missing.") % role_label)

        Partner = self.env["res.partner"].with_context(active_test=False).sudo()
        candidate_ids = set()
        search_terms = [normalized_name]
        search_terms.extend(token for token in normalized_name.split() if len(token) >= 3)

        for field_name in self._partner_lookup_fields(allow_company_name=allow_company_name):
            for search_term in dict.fromkeys(search_terms):
                candidate_ids.update(Partner.search([(field_name, "ilike", search_term)], limit=20).ids)

        partners = Partner.browse(sorted(candidate_ids)).filtered(
            lambda partner: normalized_name.casefold() in self._partner_lookup_values(
                partner,
                allow_company_name=allow_company_name,
            )
        )

        active_partners = partners.filtered("active")
        if len(active_partners) == 1:
            if require_atlax_customer and not self._is_atlax_customer_partner(active_partners[0]):
                raise UserError(_("%s not found as an Atlax customer for '%s'.") % (role_label, normalized_name))
            return active_partners[0]
        if len(active_partners) > 1:
            partners = active_partners

        if require_atlax_customer:
            partners = partners.filtered("is_atlax_customer")
            if len(partners) == 1:
                return partners[0]
            if len(partners) > 1:
                preferred_partner = self._prefer_unique_customer_partner(partners)
                if preferred_partner:
                    return preferred_partner
                raise UserError(_("%s Atlax customer match is ambiguous for '%s'.") % (role_label, normalized_name))

        if prefer_atlax_customer and len(partners) > 1:
            preferred_partner = self._prefer_unique_customer_partner(partners)
            if preferred_partner:
                return preferred_partner

        if len(partners) == 1:
            return partners[0]
        if len(partners) > 1:
            raise UserError(_("%s match is ambiguous for '%s'.") % (role_label, normalized_name))

        checked_fields = _("name") + _(", display_name")
        if allow_company_name:
            checked_fields += _(", company_name, commercial_company_name")
        if require_atlax_customer:
            raise UserError(_("%s not found as an Atlax customer for '%s' (checked %s).") % (role_label, normalized_name, checked_fields))
        raise UserError(_("%s not found for '%s' (checked %s).") % (role_label, normalized_name, checked_fields))

    def _get_customer_partner(self, ledger, cache=None):
        if ledger.partner_id:
            if not self._is_atlax_customer_partner(ledger.partner_id):
                raise UserError(_("Customer partner '%s' is not marked as an Atlax customer.") % (ledger.partner_id.display_name,))
            return ledger.partner_id

        key = self._normalize_partner_lookup_value(ledger.customer_name).casefold()
        if cache is not None and key in cache:
            return cache[key]

        partner = self._find_partner_by_name(
            ledger.customer_name,
            allow_company_name=True,
            role_label=_("Customer partner"),
            prefer_atlax_customer=True,
            require_atlax_customer=True,
        )
        if cache is not None:
            cache[key] = partner
        return partner

    def _is_postable_customer_ledger(self, ledger, cache=None):
        try:
            self._get_customer_partner(ledger, cache=cache)
        except UserError as exc:
            _logger.info(
                "Skipping wallet posting candidate %s because no Atlax customer partner is eligible: %s",
                ledger.transaction_reference or ledger.id,
                exc,
            )
            return False
        return True

    def _get_provider_partner(self, ledger, cache=None):
        key = self._normalize_partner_lookup_value(ledger.service_name).casefold()
        if cache is not None and key in cache:
            return cache[key]

        partner = self._find_partner_by_name(ledger.service_name, allow_company_name=False, role_label=_("Provider partner"))
        if cache is not None:
            cache[key] = partner
        return partner

    def _aggregate_partner_amounts(self, ledgers, *, role, amount_getter):
        totals = defaultdict(float)
        partner_cache = {}
        partner_records = {}

        for ledger in ledgers:
            if role == "customer":
                partner = self._get_customer_partner(ledger, cache=partner_cache)
            else:
                partner = self._get_provider_partner(ledger, cache=partner_cache)

            amount = float(amount_getter(ledger) or 0.0)
            if float_is_zero(amount, precision_digits=6):
                continue

            totals[partner.id] += amount
            partner_records[partner.id] = partner

        return [(partner_records[pid], totals[pid]) for pid in sorted(totals.keys())]

    def _to_company_amount(self, amount, line_currency, company, date):
        """Convert the line amount into company currency for official accounting.

        Wallet moves still keep the original foreign amount in
        `amount_currency`, while `debit` / `credit` remain in company currency
        so standard Odoo reports stay mathematically correct.
        """

        amount = float(amount or 0.0)
        if float_is_zero(amount, precision_digits=6):
            return 0.0

        currency = line_currency or company.currency_id
        posting_date = fields.Date.to_date(date) if date else fields.Date.context_today(self)
        if currency == company.currency_id:
            return amount

        return currency._convert(amount, company.currency_id, company, posting_date)

    def _line_vals(self, company, *, name, account, debit=0.0, credit=0.0, partner=None, currency=None, amount_currency=None):
        vals = {
            "name": name,
            "account_id": account.id,
            "debit": float(debit or 0.0),
            "credit": float(credit or 0.0),
        }
        if partner:
            vals["partner_id"] = partner.id

        if currency:
            vals["currency_id"] = currency.id
            if amount_currency is not None:
                vals["amount_currency"] = float(amount_currency)
        return vals

    def _get_journal_by_code(self, code, company):
        return self.env["account.journal"].search(
            [("code", "=", code), ("company_id", "=", company.id)],
            limit=1,
        )

    def _posting_has_live_move(self, posting):
        return bool(posting.journal_entry_id and posting.journal_entry_id.exists())

    # ------------------------------------------------------------------
    # Candidate selection / idempotency
    # ------------------------------------------------------------------

    def _get_unposted_ledgers(self, *, direction, posting_type, posting_date=None):
        Ledger = self.env["atlaxchange.ledger"].sudo()
        Posting = self.env["wallet.accounting.posting"].sudo()

        domain = [
            ("status", "=", "success"),
            ("transfer_direction", "=", direction),
            ("transaction_reference", "!=", False),
            ("wallet", "!=", False),
        ]
        if direction == "debit":
            domain.append(("destination_currency", "!=", False))

        if posting_date:
            start_dt, end_dt = self._day_bounds(posting_date)
            domain.extend([
                ("datetime", ">=", start_dt),
                ("datetime", "<", end_dt),
            ])

        candidates = Ledger.search(domain, order="datetime asc, id asc")
        if not candidates:
            return candidates

        existing_logs = Posting.search([
            ("posting_type", "=", posting_type),
            ("ledger_ids", "in", candidates.ids),
        ])
        live_logs = existing_logs.filtered(lambda posting: self._posting_has_live_move(posting))
        logged_ids = set(live_logs.mapped("ledger_ids").ids)
        eligible_candidates = candidates.filtered(lambda rec: rec.id not in logged_ids)
        customer_cache = {}
        return eligible_candidates.filtered(lambda rec: self._is_postable_customer_ledger(rec, cache=customer_cache))

    def _get_outstanding_posting_dates(self):
        dates = set()
        posting_specs = [
            ("credit", "funding"),
            ("debit", "wallet_debit"),
            ("debit", "destination_settlement"),
        ]
        for direction, posting_type in posting_specs:
            for ledger in self._get_unposted_ledgers(direction=direction, posting_type=posting_type):
                if ledger.datetime:
                    dates.add(fields.Date.to_date(ledger.datetime))
        return sorted(dates)

    def _group_ledgers_by_source_currency(self, ledgers):
        Ledger = self.env["atlaxchange.ledger"]
        groups = defaultdict(lambda: Ledger)
        for ledger in ledgers:
            code = self._currency_code(ledger.wallet)
            if code:
                groups[code] |= ledger
        return groups

    def _group_ledgers_by_wallet_debit_bucket(self, ledgers):
        Ledger = self.env["atlaxchange.ledger"]
        groups = defaultdict(lambda: Ledger)
        for ledger in ledgers:
            source_code = self._currency_code(ledger.wallet)
            if not source_code:
                continue
            bucket = "same_currency" if self._is_same_currency_ledger(ledger) else "cross_currency"
            groups[(source_code, bucket)] |= ledger
        return groups

    def _group_ledgers_by_destination_currency(self, ledgers):
        Ledger = self.env["atlaxchange.ledger"]
        groups = defaultdict(lambda: Ledger)
        for ledger in ledgers:
            code = self._currency_code(ledger.destination_currency)
            if code:
                groups[code] |= ledger
        return groups

    def _group_ledgers_by_destination_settlement_bucket(self, ledgers):
        Ledger = self.env["atlaxchange.ledger"]
        groups = defaultdict(lambda: Ledger)
        for ledger in ledgers:
            destination_code = self._currency_code(ledger.destination_currency)
            if not destination_code:
                continue
            bucket = "same_currency" if self._is_same_currency_ledger(ledger) else "cross_currency"
            groups[(destination_code, bucket)] |= ledger
        return groups

    # ------------------------------------------------------------------
    # Mapping resolution
    # ------------------------------------------------------------------

    def _get_funding_mapping(self, source_code, company):
        Mapping = self.env["wallet.account.map"].sudo()
        mappings = Mapping.search([
            ("active", "=", True),
            ("company_id", "=", company.id),
            ("source_currency_id.currency_code", "=", source_code),
            ("destination_currency_id", "=", False),
        ])
        if not mappings:
            raise UserError(
                _("No funding mapping found for company=%(c)s, source=%(s)s, destination=%(d)s")
                % {"c": company.display_name, "s": source_code or "-", "d": "(source-only)"}
            )
        if len(mappings) > 1:
            raise UserError(
                _("Multiple source-only funding mappings found for company=%(c)s, source=%(s)s. Please archive duplicates.")
                % {"c": company.display_name, "s": source_code or "-"}
            )
        return mappings[0]

    def _get_wallet_debit_mapping(self, source_code, company, same_currency=False):
        Mapping = self.env["wallet.account.map"].sudo()
        default_journal = self._get_journal_by_code("PAY", company)
        domain = [
            ("active", "=", True),
            ("company_id", "=", company.id),
            ("source_currency_id.currency_code", "=", source_code),
            ("destination_currency_id", "!=", False),
        ]
        if same_currency:
            domain.append(("destination_currency_id.currency_code", "=", source_code))
        else:
            domain.append(("destination_currency_id.currency_code", "!=", source_code))

        mappings = Mapping.search(domain)
        if not mappings:
            mapping_kind = _("same-currency") if same_currency else _("cross-currency")
            raise UserError(
                _("No %(kind)s wallet-debit mapping found for company=%(c)s, source=%(s)s")
                % {"kind": mapping_kind, "c": company.display_name, "s": source_code or "-"}
            )

        if same_currency:
            signatures = {
                (
                    rec.wallet_liability_account_id.id,
                    rec.payout_clearing_account_id.id,
                    rec.fee_income_account_id.id,
                    (rec.payout_journal_id or default_journal).id if (rec.payout_journal_id or default_journal) else 0,
                )
                for rec in mappings
            }
        else:
            signatures = {
                (
                    rec.wallet_liability_account_id.id,
                    rec.fx_position_account_id.id,
                    rec.fee_income_account_id.id,
                    (rec.payout_journal_id or default_journal).id if (rec.payout_journal_id or default_journal) else 0,
                )
                for rec in mappings
            }

        if len(signatures) > 1:
            if same_currency:
                message = _(
                    "Multiple same-currency payout mappings for source=%(s)s define different wallet-side accounts/journals. "
                    "Align wallet liability, payout clearing, fee income, and payout journal before aggregating by source currency."
                )
            else:
                message = _(
                    "Multiple cross-currency payout mappings for source=%(s)s define different wallet-side accounts/journals. "
                    "Align wallet liability, FX position, fee income, and payout journal before aggregating by source currency."
                )
            raise UserError(message % {"s": source_code or "-"})
        return mappings[0]

    def _get_destination_settlement_mapping(self, destination_code, company, same_currency=False):
        Mapping = self.env["wallet.account.map"].sudo()
        default_try = self._get_journal_by_code("TRY", company)
        default_pay = self._get_journal_by_code("PAY", company)

        domain = [
            ("active", "=", True),
            ("company_id", "=", company.id),
            ("destination_currency_id.currency_code", "=", destination_code),
        ]
        if same_currency:
            domain.append(("source_currency_id.currency_code", "=", destination_code))
        else:
            domain.append(("source_currency_id.currency_code", "!=", destination_code))

        mappings = Mapping.search(domain)
        if not mappings:
            mapping_kind = _("same-currency") if same_currency else _("cross-currency")
            raise UserError(
                _("No %(kind)s destination settlement mapping found for company=%(c)s, destination=%(d)s")
                % {"kind": mapping_kind, "c": company.display_name, "d": destination_code or "-"}
            )

        signatures = {
            (
                rec.bank_settlement_account_id.id,
                rec.payout_clearing_account_id.id,
                (rec.treasury_journal_id or rec.payout_journal_id or default_try or default_pay).id
                if (rec.treasury_journal_id or rec.payout_journal_id or default_try or default_pay)
                else 0,
            )
            for rec in mappings
        }
        if len(signatures) > 1:
            mapping_kind = _("same-currency") if same_currency else _("cross-currency")
            raise UserError(
                _(
                    "Multiple %(kind)s payout mappings for destination=%(d)s define different settlement accounts/journals. "
                    "Align destination settlement configuration before aggregating by destination currency."
                )
                % {"kind": mapping_kind, "d": destination_code or "-"}
            )
        return mappings[0]

    # ------------------------------------------------------------------
    # Posting log helpers
    # ------------------------------------------------------------------

    def _posting_direction(self, posting_type):
        return "credit" if posting_type == "funding" else "debit"

    def _build_posting_name(self, posting_type, posting_date=None, source_code=None, destination_code=None, historical=False, posting_variant=None):
        labels = {
            "funding": _("Funding Aggregate"),
            "wallet_debit": _("Wallet Debit Aggregate"),
            "destination_settlement": _("Destination Settlement Aggregate"),
        }
        variant_labels = {
            "same_currency": _("Same Currency"),
            "cross_currency": _("Cross Currency"),
        }
        date_label = _("Historical") if historical or not posting_date else fields.Date.to_string(posting_date)
        currency_label = source_code or destination_code or _("N/A")
        if posting_variant:
            return _("%(label)s - %(variant)s - %(date)s - %(cur)s") % {
                "label": labels.get(posting_type, posting_type),
                "variant": variant_labels.get(posting_variant, posting_variant),
                "date": date_label,
                "cur": currency_label,
            }
        return _("%(label)s - %(date)s - %(cur)s") % {
            "label": labels.get(posting_type, posting_type),
            "date": date_label,
            "cur": currency_label,
        }

    def _build_aggregation_key(self, posting_type, ledgers, company, posting_date=None, source_code=None, destination_code=None, historical=False, posting_variant=None):
        raw = ",".join(str(ledger_id) for ledger_id in sorted(ledgers.ids))
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        date_label = "historical" if historical or not posting_date else fields.Date.to_string(posting_date)
        return "|".join(
            [
                str(company.id),
                posting_type,
                posting_variant or "-",
                date_label,
                source_code or "-",
                destination_code or "-",
                digest,
            ]
        )

    def _summarize_ledgers(self, ledgers, posting_type):
        principal_total = 0.0
        fee_total = 0.0
        destination_total = 0.0
        for ledger in ledgers:
            amounts = self._normalize_amounts(ledger)
            principal_total += amounts["principal_amount"]
            fee_total += amounts["fee_amount"]
            if posting_type != "funding":
                destination_total += amounts["destination_amount"]
        return {
            "principal_amount": principal_total,
            "fee_amount": fee_total,
            "destination_amount": destination_total,
        }

    def _prepare_posting_log_vals(self, posting_type, ledgers, company, posting_date=None, source_currency=None, destination_currency=None, historical=False, posting_variant=None):
        source_code = self._currency_code(source_currency)
        destination_code = self._currency_code(destination_currency)
        totals = self._summarize_ledgers(ledgers, posting_type)
        aggregation_key = self._build_aggregation_key(
            posting_type,
            ledgers,
            company,
            posting_date=posting_date,
            source_code=source_code,
            destination_code=destination_code,
            historical=historical,
            posting_variant=posting_variant,
        )
        return {
            "name": self._build_posting_name(
                posting_type,
                posting_date=posting_date,
                source_code=source_code,
                destination_code=destination_code,
                historical=historical,
                posting_variant=posting_variant,
            ),
            "aggregation_key": aggregation_key,
            "posting_type": posting_type,
            "posting_date": posting_date or False,
            "transaction_reference": aggregation_key,
            "transaction_direction": self._posting_direction(posting_type),
            "ledger_record_id": ledgers[:1].id if len(ledgers) == 1 else False,
            "ledger_ids": [(6, 0, ledgers.ids)],
            "ledger_count": len(ledgers),
            "source_currency_id": source_currency.id if source_currency else False,
            "destination_currency_id": destination_currency.id if destination_currency else False,
            "principal_amount": totals["principal_amount"],
            "fee_amount": totals["fee_amount"],
            "destination_amount": totals["destination_amount"],
            "company_id": company.id,
            "state": "draft",
            "error_message": False,
            "journal_entry_id": False,
            "posted_at": False,
        }

    def _mark_error(self, posting, message):
        posting.sudo().write(
            {
                "state": "error",
                "error_message": message,
                "posted_at": fields.Datetime.now(),
                "journal_entry_id": False,
            }
        )

    def _mark_posted(self, posting, move):
        posting.sudo().write(
            {
                "state": "posted",
                "journal_entry_id": move.id,
                "posted_at": fields.Datetime.now(),
                "error_message": False,
            }
        )

    # ------------------------------------------------------------------
    # Move builders
    # ------------------------------------------------------------------

    def _build_funding_move_vals(self, ledgers, mapping, company, posting_date=None, historical=False):
        source_currency = mapping.source_currency_id
        res_currency = self._get_res_currency_from_supported(source_currency)
        if not res_currency:
            raise UserError(_("Unable to resolve res.currency for funding source currency %s.") % (self._currency_code(source_currency) or ""))

        move_date = self._get_move_date(posting_date, ledgers)
        principal_total = sum(self._normalize_amounts(ledger)["principal_amount"] for ledger in ledgers)
        if float_is_zero(principal_total, precision_digits=6):
            raise UserError(_("Funding aggregate total is zero for %s.") % (self._currency_code(source_currency) or ""))

        journal = mapping.funding_journal_id or self._get_journal_by_code("WLT", company) or mapping.treasury_journal_id
        if not journal:
            raise UserError(_("Funding journal not configured (mapping.funding_journal_id or journal code WLT)."))

        source_code = self._currency_code(source_currency)
        ref = self._build_posting_name("funding", posting_date=posting_date, source_code=source_code, historical=historical)
        company_total = self._to_company_amount(principal_total, res_currency, company, move_date)

        partner_totals = self._aggregate_partner_amounts(
            ledgers,
            role="customer",
            amount_getter=lambda ledger: self._normalize_amounts(ledger)["principal_amount"],
        )
        if not partner_totals:
            raise UserError(_("No customer partner totals were derived for funding aggregate %s.") % source_code)

        lines = [self._line_vals(
            company,
            name=_("Funding aggregate: bank settlement"),
            account=mapping.bank_settlement_account_id,
            debit=company_total,
            credit=0.0,
            currency=res_currency,
            amount_currency=principal_total,
        )]

        for partner, partner_amount in partner_totals:
            lines.append(
                self._line_vals(
                    company,
                    name=_("Funding aggregate: customer wallet liability"),
                    account=mapping.wallet_liability_account_id,
                    debit=0.0,
                    credit=self._to_company_amount(partner_amount, res_currency, company, move_date),
                    partner=partner,
                    currency=res_currency,
                    amount_currency=-partner_amount,
                )
            )

        return {
            "move_type": "entry",
            "journal_id": journal.id,
            "date": move_date,
            "ref": ref,
            "narration": _(
                "Aggregated wallet funding in source currency. Debit bank settlement and credit customer wallet liability for %(count)s ledger rows."
            )
            % {"count": len(ledgers)},
            "company_id": company.id,
            "line_ids": [(0, 0, line) for line in lines],
        }

    def _build_wallet_debit_move_vals(self, ledgers, mapping, company, posting_date=None, historical=False):
        source_currency = ledgers[:1].wallet or mapping.source_currency_id
        res_currency = self._get_res_currency_from_supported(source_currency)
        if not res_currency:
            raise UserError(_("Unable to resolve res.currency for payout source currency %s.") % (self._currency_code(source_currency) or ""))
        same_currency = self._is_same_currency_pair(source_currency, mapping.destination_currency_id or ledgers[:1].destination_currency)

        move_date = self._get_move_date(posting_date, ledgers)
        principal_total = 0.0
        fee_total = 0.0
        for ledger in ledgers:
            amounts = self._normalize_amounts(ledger)
            principal_total += amounts["principal_amount"]
            fee_total += amounts["fee_amount"]

        wallet_total = principal_total + fee_total
        if float_is_zero(wallet_total, precision_digits=6):
            raise UserError(_("Wallet-side debit aggregate total is zero for %s.") % (self._currency_code(source_currency) or ""))

        journal = mapping.payout_journal_id or self._get_journal_by_code("PAY", company) or self._get_journal_by_code("WLT", company)
        if not journal:
            raise UserError(_("Payout wallet-side journal not configured (mapping.payout_journal_id or journal code PAY/WLT)."))

        principal_account = mapping.payout_clearing_account_id if same_currency else mapping.fx_position_account_id
        if not principal_account:
            if same_currency:
                raise UserError(_("Payout Clearing Account is required for same-currency payout wallet-side aggregation."))
            raise UserError(_("FX Position Account is required for payout wallet-side aggregation."))

        principal_company_total = self._to_company_amount(principal_total, res_currency, company, move_date)
        fee_company_total = self._to_company_amount(fee_total, res_currency, company, move_date) if not float_is_zero(fee_total, precision_digits=6) else 0.0

        source_code = self._currency_code(source_currency)
        ref = self._build_posting_name(
            "wallet_debit",
            posting_date=posting_date,
            source_code=source_code,
            historical=historical,
            posting_variant="same_currency" if same_currency else "cross_currency",
        )

        principal_partner_totals = self._aggregate_partner_amounts(
            ledgers,
            role="customer",
            amount_getter=lambda ledger: self._normalize_amounts(ledger)["principal_amount"],
        )
        fee_partner_totals = self._aggregate_partner_amounts(
            ledgers,
            role="customer",
            amount_getter=lambda ledger: self._normalize_amounts(ledger)["fee_amount"],
        )

        if not principal_partner_totals and not fee_partner_totals:
            raise UserError(_("No customer partner totals were derived for wallet debit aggregate %s.") % source_code)

        lines = []
        for partner, partner_amount in principal_partner_totals:
            lines.append(
                self._line_vals(
                    company,
                    name=_("Wallet debit aggregate: customer wallet principal"),
                    account=mapping.wallet_liability_account_id,
                    debit=self._to_company_amount(partner_amount, res_currency, company, move_date),
                    credit=0.0,
                    partner=partner,
                    currency=res_currency,
                    amount_currency=partner_amount,
                )
            )

        for partner, partner_amount in fee_partner_totals:
            lines.append(
                self._line_vals(
                    company,
                    name=_("Wallet debit aggregate: customer wallet fee"),
                    account=mapping.wallet_liability_account_id,
                    debit=self._to_company_amount(partner_amount, res_currency, company, move_date),
                    credit=0.0,
                    partner=partner,
                    currency=res_currency,
                    amount_currency=partner_amount,
                )
            )

        lines.extend([
            self._line_vals(
                company,
                name=_("Wallet debit aggregate: payout clearing") if same_currency else _("Wallet debit aggregate: FX position / principal holding"),
                account=principal_account,
                debit=0.0,
                credit=principal_company_total,
                currency=res_currency,
                amount_currency=-principal_total,
            ),
        ])

        if not float_is_zero(fee_total, precision_digits=6):
            lines.append(
                self._line_vals(
                    company,
                    name=_("Wallet debit aggregate: fee income"),
                    account=mapping.fee_income_account_id,
                    debit=0.0,
                    credit=fee_company_total,
                    currency=res_currency,
                    amount_currency=-fee_total,
                )
            )

        return {
            "move_type": "entry",
            "journal_id": journal.id,
            "date": move_date,
            "ref": ref,
            "narration": _(
                "Aggregated %(kind)s payout wallet-side move in source currency. Debit customer wallet liability and credit %(principal_target)s plus fee income for %(count)s ledger rows."
            )
            % {
                "kind": _("same-currency") if same_currency else _("cross-currency"),
                "principal_target": _("payout clearing") if same_currency else _("Atlax FX position"),
                "count": len(ledgers),
            },
            "company_id": company.id,
            "line_ids": [(0, 0, line) for line in lines],
        }

    def _build_destination_settlement_move_vals(self, ledgers, mapping, company, posting_date=None, historical=False):
        destination_currency = ledgers[:1].destination_currency or mapping.destination_currency_id
        res_currency = self._get_res_currency_from_supported(destination_currency)
        if not res_currency:
            raise UserError(_("Unable to resolve res.currency for payout destination currency %s.") % (self._currency_code(destination_currency) or ""))
        same_currency = self._is_same_currency_pair(mapping.source_currency_id or ledgers[:1].wallet, destination_currency)

        move_date = self._get_move_date(posting_date, ledgers)
        destination_total = sum(self._normalize_amounts(ledger)["destination_amount"] for ledger in ledgers)
        if float_is_zero(destination_total, precision_digits=6):
            raise UserError(_("Destination settlement aggregate total is zero for %s.") % (self._currency_code(destination_currency) or ""))

        journal = mapping.treasury_journal_id or mapping.payout_journal_id or self._get_journal_by_code("TRY", company) or self._get_journal_by_code("PAY", company)
        if not journal:
            raise UserError(_("Settlement journal not configured (mapping.treasury_journal_id / payout_journal_id or journal code TRY/PAY)."))

        company_total = self._to_company_amount(destination_total, res_currency, company, move_date)
        destination_code = self._currency_code(destination_currency)
        ref = self._build_posting_name(
            "destination_settlement",
            posting_date=posting_date,
            destination_code=destination_code,
            historical=historical,
            posting_variant="same_currency" if same_currency else "cross_currency",
        )

        provider_totals = self._aggregate_partner_amounts(
            ledgers,
            role="provider",
            amount_getter=lambda ledger: self._normalize_amounts(ledger)["destination_amount"],
        )
        if not provider_totals:
            raise UserError(_("No provider partner totals were derived for destination settlement aggregate %s.") % destination_code)

        reverse_same_currency_settlement = same_currency and self._bank_settlement_is_asset(mapping.bank_settlement_account_id)

        if reverse_same_currency_settlement:
            lines = []
            for partner, partner_amount in provider_totals:
                lines.append(
                    self._line_vals(
                        company,
                        name=_("Destination settlement aggregate: payout clearing"),
                        account=mapping.payout_clearing_account_id,
                        debit=self._to_company_amount(partner_amount, res_currency, company, move_date),
                        credit=0.0,
                        partner=partner,
                        currency=res_currency,
                        amount_currency=partner_amount,
                    )
                )

            lines.append(self._line_vals(
                company,
                name=_("Destination settlement aggregate: bank settlement"),
                account=mapping.bank_settlement_account_id,
                debit=0.0,
                credit=company_total,
                currency=res_currency,
                amount_currency=-destination_total,
            ))
        else:
            lines = [self._line_vals(
                company,
                name=_("Destination settlement aggregate: bank settlement"),
                account=mapping.bank_settlement_account_id,
                debit=company_total,
                credit=0.0,
                currency=res_currency,
                amount_currency=destination_total,
            )]

            for partner, partner_amount in provider_totals:
                lines.append(
                    self._line_vals(
                        company,
                        name=_("Destination settlement aggregate: payout clearing"),
                        account=mapping.payout_clearing_account_id,
                        debit=0.0,
                        credit=self._to_company_amount(partner_amount, res_currency, company, move_date),
                        partner=partner,
                        currency=res_currency,
                        amount_currency=-partner_amount,
                    )
                )

        return {
            "move_type": "entry",
            "journal_id": journal.id,
            "date": move_date,
            "ref": ref,
            "narration": _(
                "Aggregated %(kind)s payout settlement move in destination currency. %(entry_shape)s for %(count)s ledger rows."
            )
            % {
                "kind": _("same-currency") if same_currency else _("cross-currency"),
                "entry_shape": _("Debit payout clearing and credit bank settlement") if reverse_same_currency_settlement else _("Debit bank settlement and credit payout clearing"),
                "count": len(ledgers),
            },
            "company_id": company.id,
            "line_ids": [(0, 0, line) for line in lines],
        }

    # ------------------------------------------------------------------
    # Dispatch / posting
    # ------------------------------------------------------------------

    def _build_move_vals_for_group(self, posting_type, ledgers, company, posting_date=None, historical=False, posting_variant=None):
        if posting_type == "funding":
            source_code = self._currency_code(ledgers[:1].wallet)
            mapping = self._get_funding_mapping(source_code, company)
            return mapping, self._build_funding_move_vals(ledgers, mapping, company, posting_date=posting_date, historical=historical)

        if posting_type == "wallet_debit":
            source_code = self._currency_code(ledgers[:1].wallet)
            same_currency = posting_variant == "same_currency"
            mapping = self._get_wallet_debit_mapping(source_code, company, same_currency=same_currency)
            return mapping, self._build_wallet_debit_move_vals(ledgers, mapping, company, posting_date=posting_date, historical=historical)

        if posting_type == "destination_settlement":
            destination_code = self._currency_code(ledgers[:1].destination_currency)
            same_currency = posting_variant == "same_currency"
            mapping = self._get_destination_settlement_mapping(destination_code, company, same_currency=same_currency)
            return mapping, self._build_destination_settlement_move_vals(ledgers, mapping, company, posting_date=posting_date, historical=historical)

        raise UserError(_("Unsupported posting type: %s") % posting_type)

    def _post_group(self, posting_type, ledgers, company, posting_date=None, historical=False, existing_posting=None, posting_variant=None):
        Posting = self.env["wallet.accounting.posting"].sudo()
        ledgers = ledgers.sorted(lambda rec: (rec.datetime or fields.Datetime.now(), rec.id))
        if not ledgers:
            return Posting

        posting_variant = posting_variant or self._infer_posting_variant(posting_type, ledgers)

        source_currency = False
        destination_currency = False

        if posting_type in ("funding", "wallet_debit"):
            source_currency = ledgers[:1].wallet
        if posting_type == "destination_settlement":
            destination_currency = ledgers[:1].destination_currency

        if posting_type == "wallet_debit" and posting_variant == "same_currency":
            destination_currency = ledgers[:1].destination_currency
        if posting_type == "destination_settlement" and posting_variant == "same_currency":
            source_currency = ledgers[:1].wallet

        vals = self._prepare_posting_log_vals(
            posting_type,
            ledgers,
            company,
            posting_date=posting_date,
            source_currency=source_currency,
            destination_currency=destination_currency,
            historical=historical,
            posting_variant=posting_variant,
        )

        if not existing_posting:
            existing_posting = Posting.search([("aggregation_key", "=", vals["aggregation_key"])], limit=1)

        if existing_posting:
            posting = existing_posting.sudo()
            if self._posting_has_live_move(posting):
                return posting
            posting.write(vals)
        else:
            posting = Posting.create(vals)

        try:
            mapping, move_vals = self._build_move_vals_for_group(
                posting_type,
                ledgers,
                company,
                posting_date=posting_date,
                historical=historical,
                posting_variant=posting_variant,
            )

            posting.write(
                {
                    "source_currency_id": vals["source_currency_id"] or (mapping.source_currency_id.id if posting_type in ("funding", "wallet_debit") else False),
                    "destination_currency_id": vals["destination_currency_id"] or (mapping.destination_currency_id.id if posting_type == "destination_settlement" else False),
                }
            )

            move_vals["is_wallet_sync_move"] = True
            move_vals["wallet_posting_type"] = posting_type
            move = self.env["account.move"].sudo().with_company(company).create(move_vals)
            self._mark_posted(posting, move)
            return posting
        except Exception as exc:
            _logger.exception("Wallet aggregate posting failed (%s, key=%s)", posting_type, posting.aggregation_key)
            self._mark_error(posting, str(exc))
            return posting

    # ------------------------------------------------------------------
    # Public aggregation API
    # ------------------------------------------------------------------

    @api.model
    def post_funding_aggregations(self, posting_date=None, company=None, historical=False):
        company = company or self.env.company
        candidates = self._get_unposted_ledgers(
            direction="credit",
            posting_type="funding",
            posting_date=None if historical else posting_date,
        )
        groups = self._group_ledgers_by_source_currency(candidates)
        postings = self.env["wallet.accounting.posting"]
        for source_code in sorted(groups.keys()):
            postings |= self._post_group(
                "funding",
                groups[source_code],
                company,
                posting_date=None if historical else posting_date,
                historical=historical,
            )
        return postings

    @api.model
    def post_wallet_debit_aggregations(self, posting_date=None, company=None, historical=False):
        company = company or self.env.company
        candidates = self._get_unposted_ledgers(
            direction="debit",
            posting_type="wallet_debit",
            posting_date=None if historical else posting_date,
        )
        groups = self._group_ledgers_by_wallet_debit_bucket(candidates)
        postings = self.env["wallet.accounting.posting"]
        for source_code, posting_variant in sorted(groups.keys()):
            postings |= self._post_group(
                "wallet_debit",
                groups[(source_code, posting_variant)],
                company,
                posting_date=None if historical else posting_date,
                historical=historical,
                posting_variant=posting_variant,
            )
        return postings

    @api.model
    def post_destination_settlement_aggregations(self, posting_date=None, company=None, historical=False):
        company = company or self.env.company
        candidates = self._get_unposted_ledgers(
            direction="debit",
            posting_type="destination_settlement",
            posting_date=None if historical else posting_date,
        )
        groups = self._group_ledgers_by_destination_settlement_bucket(candidates)
        postings = self.env["wallet.accounting.posting"]
        for destination_code, posting_variant in sorted(groups.keys()):
            postings |= self._post_group(
                "destination_settlement",
                groups[(destination_code, posting_variant)],
                company,
                posting_date=None if historical else posting_date,
                historical=historical,
                posting_variant=posting_variant,
            )
        return postings

    @api.model
    def post_daily_aggregates(self, posting_date=None, company=None):
        company = company or self.env.company
        posting_date = fields.Date.to_date(posting_date or fields.Date.context_today(self))

        funding = self.post_funding_aggregations(posting_date=posting_date, company=company)
        wallet = self.post_wallet_debit_aggregations(posting_date=posting_date, company=company)
        settlement = self.post_destination_settlement_aggregations(posting_date=posting_date, company=company)

        return {
            "posting_date": fields.Date.to_string(posting_date),
            "funding_postings": len(funding),
            "wallet_debit_postings": len(wallet),
            "destination_settlement_postings": len(settlement),
            "total_postings": len(funding) + len(wallet) + len(settlement),
        }

    @api.model
    def post_all_outstanding_daily_aggregates(self, company=None, max_dates=None):
        company = company or self.env.company

        all_dates = self._get_outstanding_posting_dates()
        if not all_dates:
            return {
                "dates_processed": 0,
                "remaining_dates": 0,
                "funding_postings": 0,
                "wallet_debit_postings": 0,
                "destination_settlement_postings": 0,
                "total_postings": 0,
            }

        if max_dates:
            dates = all_dates[:max_dates]
        else:
            dates = all_dates

        summary = {
            "dates_processed": 0,
            "remaining_dates": max(0, len(all_dates) - len(dates)),
            "funding_postings": 0,
            "wallet_debit_postings": 0,
            "destination_settlement_postings": 0,
            "total_postings": 0,
        }

        for posting_date in dates:
            result = self.post_daily_aggregates(posting_date=posting_date, company=company)
            summary["dates_processed"] += 1
            summary["funding_postings"] += result["funding_postings"]
            summary["wallet_debit_postings"] += result["wallet_debit_postings"]
            summary["destination_settlement_postings"] += result["destination_settlement_postings"]
            summary["total_postings"] += result["total_postings"]

        return summary

    @api.model
    def post_historical_aggregates(self, company=None):
        company = company or self.env.company

        funding = self.post_funding_aggregations(company=company, historical=True)
        wallet = self.post_wallet_debit_aggregations(company=company, historical=True)
        settlement = self.post_destination_settlement_aggregations(company=company, historical=True)

        return {
            "posting_date": False,
            "funding_postings": len(funding),
            "wallet_debit_postings": len(wallet),
            "destination_settlement_postings": len(settlement),
            "total_postings": len(funding) + len(wallet) + len(settlement),
        }

    @api.model
    def retry_posting_log(self, posting):
        posting.ensure_one()

        if not posting.ledger_ids:
            raise UserError(_("No ledger rows are linked to this posting log; cannot retry."))
        if not posting.posting_type:
            raise UserError(_("Posting type is missing on this posting log; cannot retry."))

        posting.sudo().write(
            {
                "state": "draft",
                "error_message": False,
                "posted_at": False,
                "journal_entry_id": False,
            }
        )
        return self._post_group(
            posting.posting_type,
            posting.ledger_ids.sudo(),
            posting.company_id,
            posting_date=posting.posting_date,
            historical=not bool(posting.posting_date),
            existing_posting=posting,
            posting_variant=self._infer_posting_variant(posting.posting_type, posting.ledger_ids),
        )
