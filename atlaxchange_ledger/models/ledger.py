# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import requests
from datetime import datetime
from requests.exceptions import ConnectTimeout, ReadTimeout
import logging
from odoo.exceptions import UserError, ValidationError
import csv
from io import StringIO
from odoo.http import request
import threading
from odoo import SUPERUSER_ID, api as odoo_api, registry as registry_get
import math
import itertools
import json
import time

_logger = logging.getLogger(__name__)

class AtlaxchangeLedger(models.Model):
    _name = 'atlaxchange.ledger'
    _description = 'Atlaxchange Client Ledger History'
    _order = 'datetime desc'
    _rec_name = 'transaction_reference'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    datetime = fields.Datetime(string='Date')
    transaction_reference = fields.Char(string='Reference', index=True)
    bank = fields.Char(string='Bank')
    bank_code = fields.Char(string='Bank Code')
    beneficiary = fields.Char(string='Beneficiary')
    customer_name = fields.Char(string='Customer Name', store=True)
    wallet = fields.Many2one('supported.currency', string='Wallet')
    amount = fields.Float(string='Amount', store=True, digits=(16, 2))
    total_amount = fields.Float(string='Dest. Amount', digits=(16, 2))
    fee = fields.Float(string='Fee')
    conversion_rate = fields.Float(string='Rate')
    destination_currency = fields.Many2one('supported.currency', string='Destination Currency')  # updated
    transfer_direction = fields.Selection([
        ('debit', 'Debit'),
        ('credit', 'Credit')
    ], string='Type')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed')
    ], string='Status', default='pending')
    partner_id = fields.Many2one('res.partner', string='Partner')
    beneficiary_acct = fields.Char(string='Beneficiary Account')
    session_id = fields.Char(string='Session ID')
    error_message = fields.Text(string='Error Message')
    env_source = fields.Selection([
        ('production', 'Production'),
        ('staging', 'Sandbox')
    ], string='Env', readonly=True, help="Environment source from Atlax API when the transaction was fetched.")


    def action_initiate_reprocess(self):
        """Initiate a reprocess batch from selected ledger lines.

        Rules:
        - Only 'debit' transactions
        - Status must be 'processing'
        """
        if not self:
            raise UserError(_("No ledger records selected for reprocess."))

        # Filter: only debit + processing
        valid_ledgers = self.filtered(lambda r: r.transfer_direction == 'debit' and r.status in ('processing',))
        invalid_ledgers = self - valid_ledgers

        if invalid_ledgers:
            refs = ', '.join(filter(None, invalid_ledgers.mapped('transaction_reference')))
            raise UserError(_(
                "Reprocessing can only be initiated for transactions of type 'debit' with status 'processing'. "
                "Invalid selection: %s"
            ) % (refs or _('No reference')))

        if not valid_ledgers:
            raise UserError(_("No valid transactions found for reprocess."))

        # Build lines payload
        reprocess_lines = [
            (0, 0, {
                'reference': rec.transaction_reference,
                'customer_name': rec.customer_name or '',
                'wallet': rec.wallet.id if rec.wallet else False,
                'amount': float(rec.amount or 0.0),
                'destination_currency': rec.destination_currency.id if rec.destination_currency else False,
                'total_amount': float(rec.total_amount or 0.0),
            })
            for rec in valid_ledgers
            if rec.transaction_reference  # ensure reference exists
        ]

        if not reprocess_lines:
            raise UserError(_("No valid transactions found for reprocess."))

        # Create the batch and return its form view
        reprocess = self.env['atlaxchange.reprocess'].create({
            'reprocess_line_ids': reprocess_lines,
            # If your model enforces NOT NULL on reason, uncomment:
            # 'reason': 'Reprocess requested from ledger',
        })

        return {
            'name': 'Reprocess',
            'type': 'ir.actions.act_window',
            'res_model': 'atlaxchange.reprocess',
            'res_id': reprocess.id,
            'view_mode': 'form',
            'target': 'current',
        }
        
        
        
    def action_initiate_reversal(self):
        """Create a atlaxchange.reversal record from selected ledger lines.

        Only ledger records with status == 'failed' are allowed to be reversed.
        """
        if not self:
            raise UserError("No ledger records selected for reversal.")

        # Only allow records that are in 'failed' status
        failed_ledgers = self.filtered(lambda r: r.status == 'failed')
        invalid_ledgers = self - failed_ledgers
        if invalid_ledgers:
            refs = ', '.join(filter(None, invalid_ledgers.mapped('transaction_reference')))
            raise UserError(
                "Reversal can only be initiated for transactions with status 'failed'. "
                "Invalid selection: %s" % (refs or 'No reference')
            )

        reversal_lines = []
        for rec in failed_ledgers:
            ref = getattr(rec, 'transaction_reference', False) or getattr(rec, 'reference', False)
            if not ref:
                continue
            reversal_lines.append((0, 0, {
                'reference': ref,
                'customer_name': rec.customer_name or '',
                'wallet': rec.wallet.id if getattr(rec, 'wallet', False) else False,
                'amount': float(getattr(rec, 'amount', 0.0) or 0.0),
                'destination_currency': getattr(rec, 'destination_currency', False) and getattr(rec.destination_currency, 'id') or False,
                'total_amount': float(getattr(rec, 'total_amount', 0.0) or 0.0),
            }))

        if not reversal_lines:
            raise UserError("No valid transactions found for reversal.")

        reversal = self.env['atlaxchange.reversal'].create({
            'reversal_line_ids': reversal_lines,
            'reason': 'Transaction failed',  # <-- Provide a default reason
        })

        return {
            'name': 'Reversal',
            'type': 'ir.actions.act_window',
            'res_model': 'atlaxchange.reversal',
            'res_id': reversal.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # NEW: helper to robustly extract "next cursor" from payload/headers
    def _extract_cursors(self, response, payload):
        """
        Extract both 'after' and 'before' cursors from common locations.
        Returns a dict:
        {
            'after': (value_or_None, source_str_or_None),
            'before': (value_or_None, source_str_or_None),
        }
        """
        after_val = before_val = None
        after_src = before_src = None

        def set_if(val, src, kind):
            nonlocal after_val, after_src, before_val, before_src
            if kind == 'after' and val and not after_val:
                after_val, after_src = str(val), src
            if kind == 'before' and val and not before_val:
                before_val, before_src = str(val), src

        data = payload.get('data') if isinstance(payload, dict) else {}
        if isinstance(data, dict):
            cur = data.get('cursor')
            if isinstance(cur, dict):
                set_if(cur.get('after'), 'data.cursor.after', 'after')
                set_if(cur.get('next'), 'data.cursor.next', 'after')           # treat 'next' as after
                set_if(cur.get('next_cursor'), 'data.cursor.next_cursor', 'after')
                set_if(cur.get('before'), 'data.cursor.before', 'before')
            # some APIs put cursor keys directly under data
            set_if(data.get('next_cursor'), 'data.next_cursor', 'after')
            set_if(data.get('after'), 'data.after', 'after')
            set_if(data.get('before'), 'data.before', 'before')

        cur_top = payload.get('cursor') if isinstance(payload, dict) else None
        if isinstance(cur_top, dict):
            set_if(cur_top.get('after'), 'cursor.after', 'after')
            set_if(cur_top.get('next'), 'cursor.next', 'after')
            set_if(cur_top.get('next_cursor'), 'cursor.next_cursor', 'after')
            set_if(cur_top.get('before'), 'cursor.before', 'before')

        # top-level
        if isinstance(payload, dict):
            set_if(payload.get('next_cursor'), 'payload.next_cursor', 'after')
            set_if(payload.get('after'), 'payload.after', 'after')
            set_if(payload.get('before'), 'payload.before', 'before')

        # headers (e.g., X-Next-Cursor or X-Prev-Cursor)
        headers = getattr(response, 'headers', {}) or {}
        if 'X-Next-Cursor' in headers and headers['X-Next-Cursor']:
            set_if(headers['X-Next-Cursor'], 'header:X-Next-Cursor', 'after')
        if 'Next-Cursor' in headers and headers['Next-Cursor']:
            set_if(headers['Next-Cursor'], 'header:Next-Cursor', 'after')
        if 'x-next-cursor' in headers and headers['x-next-cursor']:
            set_if(headers['x-next-cursor'], 'header:x-next-cursor', 'after')
        # possible previous/backward header
        for key in ('X-Prev-Cursor', 'Prev-Cursor', 'x-prev-cursor'):
            if key in headers and headers[key]:
                set_if(headers[key], f'header:{key}', 'before')

        return {
            'after': (after_val, after_src),
            'before': (before_val, before_src),
        }

    # Optional admin convenience: clear stored cursor so we can backfill
    @api.model
    def reset_history_cursor(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('atlaxchange_ledger.history_last_cursor', '')
        return True

    @api.model
    def fetch_ledger_history(
        self,
        target_count=None,
        max_seconds=None,
        max_pages=None,
        per_request_timeout=None,
        reset_cursor=False,
        start_cursor=None,
        direction='auto',
        commit_each_page=False,
        page_size=None,
        page_size_param=None,
        after_param=None,     # NEW: name of "after" query param (e.g., 'after', 'cursor', 'next')
        before_param=None,    # NEW: name of "before" query param (e.g., 'before', 'cursor', 'prev')
    ):
        ICP = self.env['ir.config_parameter'].sudo()
        client = self.env['atlax.api.client']
        url = client.url('/v1/transactions/history')
        cfg = client.get_api_config()

        # Defaults
        if target_count is None:
            target_count = int(ICP.get_param('atlaxchange_ledger.history_target', 500))
        if max_seconds is None:
            max_seconds = int(ICP.get_param('atlaxchange_ledger.history_timeout', 8))
        if max_pages is None:
            max_pages = int(ICP.get_param('atlaxchange_ledger.history_max_pages', 50))
        if per_request_timeout is None:
            per_request_timeout = int(ICP.get_param('atlaxchange_ledger.history_request_timeout', 10))

        ps_param = (page_size_param or ICP.get_param('atlaxchange_ledger.page_size_param', 'limit')).strip() or 'limit'
        try:
            ps_value = int(page_size if page_size is not None else ICP.get_param('atlaxchange_ledger.page_size', 1000))
        except Exception:
            ps_value = 1000
        ps_value = max(1, min(1000, ps_value))

        # NEW: cursor param names
        after_qp = (after_param or ICP.get_param('atlaxchange_ledger.after_param', 'after')).strip() or 'after'
        before_qp = (before_param or ICP.get_param('atlaxchange_ledger.before_param', 'before')).strip() or 'before'

        start = time.monotonic()
        _logger.info(
            "History fetch starting: direction=%s, target_count=%s, max_seconds=%s, max_pages=%s, timeout=%s, reset_cursor=%s, start_cursor=%s, commit_each_page=%s, %s=%s, after_param=%s, before_param=%s",
            direction, target_count, max_seconds, max_pages, per_request_timeout, reset_cursor, bool(start_cursor), commit_each_page, ps_param, ps_value, after_qp, before_qp
        )

        if not cfg.get('api_key') or not cfg.get('api_secret'):
            now = fields.Datetime.now()
            stats = {
                'processed': 0, 'created': 0, 'updated': 0, 'pages': 0,
                'last_cursor': None, 'time': now.isoformat(),
                'partial': True, 'reason': 'Missing API credentials',
                'direction': direction,
            }
            ICP.set_param('atlaxchange_ledger.history_last_stats', json.dumps(stats))
            return stats

        headers = client.build_headers()

        key_after = 'atlaxchange_ledger.history_last_cursor_after'
        key_before = 'atlaxchange_ledger.history_last_cursor_before'
        stored_after = ICP.get_param(key_after) or None
        stored_before = ICP.get_param(key_before) or None

        next_after = start_cursor if (start_cursor and direction in ('auto', 'forward')) else (None if reset_cursor else stored_after)
        next_before = start_cursor if (start_cursor and direction in ('auto', 'backward')) else (None if reset_cursor else stored_before)

        processed_count = created_count = updated_count = pages_processed = 0
        partial = False
        reason = None
        last_advanced_cursor = None  # NEW: only report if we advanced

        def chunked(iterable, size):
            it = iter(iterable)
            while True:
                batch = list(itertools.islice(it, size))
                if not batch:
                    return
                yield batch

        seen_after = set(filter(None, [next_after]))
        seen_before = set(filter(None, [next_before]))

        def elapsed_exceeded():
            return (time.monotonic() - start) >= max_seconds

        while True:
            if elapsed_exceeded():
                partial = True; reason = 'Time budget exceeded'; break
            if pages_processed >= max_pages:
                partial = True; reason = 'Max pages reached'; break

            params = {ps_param: ps_value}
            using = f"{ps_param}={ps_value}"
            if direction == 'forward':
                if next_after:
                    params[after_qp] = next_after
                    using += f", {after_qp}={next_after}"
            elif direction == 'backward':
                if next_before:
                    params[before_qp] = next_before
                    using += f", {before_qp}={next_before}"
            else:
                if next_after:
                    params[after_qp] = next_after
                    using += f", {after_qp}={next_after}"
                elif next_before:
                    params[before_qp] = next_before
                    using += f", {before_qp}={next_before}"

            attempt = 0
            while True:
                try:
                    response = requests.get(url, headers=headers, params=params, timeout=per_request_timeout)
                    break
                except (ConnectTimeout, ReadTimeout) as e:
                    attempt += 1
                    if attempt >= 2:
                        reason = f"API timeout after retries: {e.__class__.__name__}"
                        partial = True
                        response = None
                        break
                    time.sleep(0.8 * attempt)

            if response is None:
                break

            if response.status_code != 200:
                _logger.warning("History fetch: unexpected status %s (params=%s); stopping.", response.status_code, params)
                reason = f"HTTP {response.status_code}"
                partial = True
                break

            try:
                payload = response.json() or {}
            except Exception:
                _logger.warning("History fetch: invalid JSON (params=%s); stopping.", params)
                reason = "Invalid JSON"
                partial = True
                break

            transactions = payload.get('data', {}).get('transactions', [])
            cursors = self._extract_cursors(response, payload)
            (after_val, after_src) = cursors['after']
            (before_val, before_src) = cursors['before']
            pages_processed += 1

            _logger.info(
                "History fetch page %s: txns=%s, params=%s, next_after=%s (from %s), next_before=%s (from %s)",
                pages_processed, len(transactions or []), using,
                after_val, after_src or 'n/a',
                before_val, before_src or 'n/a'
            )

            if not transactions:
                if after_val:
                    ICP.set_param(key_after, after_val); next_after = after_val
                if before_val:
                    ICP.set_param(key_before, before_val); next_before = before_val
                break

            refs = [t.get('reference') for t in transactions if t.get('reference')]
            if not refs:
                if after_val:
                    ICP.set_param(key_after, after_val); next_after = after_val
                if before_val:
                    ICP.set_param(key_before, before_val); next_before = before_val
                reason = "No references in page"; partial = True; break

            # Currency cache for this page
            src_codes = {t.get('currency_code') for t in transactions if t.get('currency_code')}
            dst_codes = {t.get('destination_currency') for t in transactions if t.get('destination_currency')}
            all_codes = list({*src_codes, *dst_codes})
            cur_map = {}
            if all_codes:
                cur_recs = self.env['supported.currency'].search([('currency_code', 'in', all_codes)])
                cur_map = {c.currency_code: c.id for c in cur_recs}

            existing_recs = self.search([('transaction_reference', 'in', refs)])
            existing_map = {r.transaction_reference: r for r in existing_recs}

            new_vals, to_update = [], []
            for rec in transactions:
                ref = rec.get('reference')
                if not ref:
                    continue

                status_val = rec.get('status', 'pending')
                if status_val not in dict(self._fields['status'].selection):
                    status_val = 'pending'

                created_at = rec.get('created_at')
                try:
                    dt_val = datetime.utcfromtimestamp(int(created_at)) if created_at is not None else fields.Datetime.now()
                except Exception:
                    dt_val = fields.Datetime.now()

                vals = {
                    'datetime': dt_val,
                    'bank': rec.get('bank_name'),
                    'bank_code': rec.get('bank_code'),
                    'beneficiary': rec.get('beneficiary_name'),
                    'customer_name': rec.get('customer_name', 'N/A'),
                    'transaction_reference': ref,
                    'amount': abs((rec.get('amount') or 0) / 100),
                    'total_amount': abs((rec.get('total_amount') or 0) / 100),
                    'fee': (rec.get('fee') or 0) / 100,
                    'conversion_rate': rec.get('conversion_rate', 0),
                    'destination_currency': cur_map.get(rec.get('destination_currency')) or False,
                    'status': status_val,
                    'transfer_direction': rec.get('direction'),
                    'wallet': cur_map.get(rec.get('currency_code')) or False,
                    'beneficiary_acct': rec.get('beneficiary_acct', ''),
                    'session_id': rec.get('session_id', ''),
                    'error_message': rec.get('error_message', ''),
                    'env_source': cfg.get('env'),
                }

                if ref in existing_map:
                    rec_to_update = existing_map[ref]
                    upd = {
                        'status': vals['status'],
                        'beneficiary_acct': vals['beneficiary_acct'],
                        'session_id': vals['session_id'],
                        'error_message': vals['error_message'],
                        'transfer_direction': vals['transfer_direction'],
                    }
                    if any(getattr(rec_to_update, k) != v for k, v in upd.items()):
                        to_update.append((rec_to_update, upd))
                else:
                    new_vals.append(vals)

            for batch in chunked(new_vals, 500):
                self.create(batch)
                created_count += len(batch)
            for rec_to_update, upd in to_update:
                rec_to_update.write(upd)
                updated_count += 1

            processed_count += len(transactions)
            if commit_each_page:
                try: self.env.cr.commit()
                except Exception: _logger.exception("Commit failed after page %s", pages_processed)

            # Advance cursor with auto-fallback
            advanced = False
            if direction in ('forward', 'auto'):
                if after_val:
                    if after_val in seen_after:
                        _logger.warning("History fetch: 'after' cursor repeated (%s), stopping.", after_val)
                        partial = True; reason = 'Cursor repeated (after)'; break
                    ICP.set_param(key_after, after_val); next_after = after_val
                    seen_after.add(after_val); advanced = True
                    last_advanced_cursor = after_val
                elif direction == 'auto' and before_val:
                    if before_val in seen_before:
                        _logger.warning("History fetch: 'before' cursor repeated (%s), stopping.", before_val)
                        partial = True; reason = 'Cursor repeated (before)'; break
                    ICP.set_param(key_before, before_val); next_before = before_val
                    seen_before.add(before_val); advanced = True
                    last_advanced_cursor = before_val
            elif direction == 'backward':
                if before_val:
                    if before_val in seen_before:
                        _logger.warning("History fetch: 'before' cursor repeated (%s), stopping.", before_val)
                        partial = True; reason = 'Cursor repeated (before)'; break
                    ICP.set_param(key_before, before_val); next_before = before_val
                    seen_before.add(before_val); advanced = True
                    last_advanced_cursor = before_val

            if not advanced:
                # EXTRA DIAGNOSTIC on failure
                try:
                    data = payload.get('data', {})
                    cur_debug = data.get('cursor') if isinstance(data, dict) else None
                    _logger.warning("History fetch: no usable next cursor; payload keys=%s, data.cursor=%s", list(payload.keys()), cur_debug)
                except Exception:
                    pass
                partial = True; reason = 'No next cursor from API'; break

            if processed_count >= target_count:
                break
            if elapsed_exceeded():
                partial = True; reason = 'Time budget exceeded'; break

        now = fields.Datetime.now()
        stats = {
            'processed': processed_count,
            'created': created_count,
            'updated': updated_count,
            'pages': pages_processed,
            'last_cursor': last_advanced_cursor,  # NEW: only the cursor we actually advanced to
            'time': now.isoformat(),
            'partial': partial,
            'reason': reason,
            'direction': direction,
        }
        try:
            ICP.set_param('atlaxchange_ledger.history_last_stats', json.dumps(stats))
        except Exception:
            _logger.exception("Failed to persist last fetch stats")
        _logger.info("Ledger fetch stats: %s", stats)
        return stats

    @api.model
    def cron_fetch_forward(self):
        return self.fetch_ledger_history(
            target_count=int(self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.cron_forward_target', 4000)),
            max_seconds=int(self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.cron_forward_secs', 20)),
            direction='forward',
            commit_each_page=True,
            page_size=int(self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.page_size', 1000)),
            page_size_param=self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.page_size_param', 'limit'),
        )

    @api.model
    def cron_backfill_backward(self):
        return self.fetch_ledger_history(
            target_count=int(self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.cron_backfill_target', 8000)),
            max_seconds=int(self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.cron_backfill_secs', 60)),
            direction='backward',
            commit_each_page=True,
            page_size=int(self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.page_size', 1000)),
            page_size_param=self.env['ir.config_parameter'].sudo().get_param('atlaxchange_ledger.page_size_param', 'limit'),
        )

    @api.model
    def fetch_ledger_history_enqueue(self, sync=False, popup=False, target_count=None, max_seconds=None,
                                     reset_cursor=False, start_cursor=None, direction='auto', commit_each_page=False,
                                     page_size=None, page_size_param=None, after_param=None, before_param=None):
        if sync:
            stats = self.fetch_ledger_history(
                target_count=target_count,
                max_seconds=max_seconds,
                reset_cursor=reset_cursor,
                start_cursor=start_cursor,
                direction=direction,
                commit_each_page=commit_each_page,
                page_size=page_size,
                page_size_param=page_size_param,
                after_param=after_param,
                before_param=before_param,
            )
            if popup:
                msg = _("Ledger fetch completed. Processed: %(p)s, Created: %(c)s, Updated: %(u)s, Pages: %(g)s%(partial)s") % {
                    'p': stats.get('processed', 0), 'c': stats.get('created', 0),
                    'u': stats.get('updated', 0), 'g': stats.get('pages', 0),
                    'partial': " (partial: %s)" % stats.get('reason') if stats.get('partial') else "",
                }
                raise ValidationError(msg)
            return stats

        db_name = self.env.cr.dbname
        def _worker(dbname, tcount, tbudget, treset, tstart, tdir, tcommit, tps, tpsp, taft, tbef):
            try:
                _logger.info("Background fetch_ledger_history: worker starting for db=%s", dbname)
                with registry_get(dbname).cursor() as cr:
                    env = odoo_api.Environment(cr, SUPERUSER_ID, {})
                    stats = env['atlaxchange.ledger'].fetch_ledger_history(
                        target_count=tcount, max_seconds=tbudget, reset_cursor=treset, start_cursor=tstart,
                        direction=tdir, commit_each_page=tcommit, page_size=tps, page_size_param=tpsp,
                        after_param=taft, before_param=tbef
                    )
                    _logger.info("Background fetch_ledger_history: done. Stats=%s", stats)
                    try:
                        cr.commit()
                    except Exception:
                        _logger.exception("Failed to explicit commit in background worker for db=%s", dbname)
                _logger.info("Background fetch_ledger_history: worker finished for db=%s", dbname)
            except Exception as e:
                _logger.exception("Background fetch_ledger_history failed for db=%s: %s", dbname, e)

        threading.Thread(target=_worker, args=(
            db_name, target_count, max_seconds, reset_cursor, start_cursor, direction, commit_each_page,
            page_size, page_size_param, after_param, before_param
        ), daemon=False).start()
        return {'scheduled': True}

