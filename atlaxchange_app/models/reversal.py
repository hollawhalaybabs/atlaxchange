from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging
import json  # added

_logger = logging.getLogger(__name__)

class reversal(models.Model):
    _name = 'atlaxchange.reversal'
    _description = 'Reversal Process'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default='New')
    reversal_line_ids = fields.One2many('atlaxchange.reversal.line', 'reversal_id', string="Reversal Lines")
    amount = fields.Float(string="Total Amount", compute="_compute_total_amount", store=True, readonly=True)
    reason = fields.Text(string="Reason", required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approval', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('done', 'Done'),
        ('rejected', 'Rejected')
    ], string="Status", default='draft', readonly=True)
    approver_ids = fields.Many2many(
        'res.users',
        'reversal_approver_rel',
        'reversal_id',
        'user_id',
        string="Approvers",
        readonly=True,
        domain=[('share', '=', False)]
    )
    approval_level = fields.Selection([
        ('hoo', 'HOO'),
        ('coo', 'COO'),
        ('ceo', 'CEO')
    ], string="Approval Level", readonly=True)
    is_approver = fields.Boolean(compute="_compute_is_approver")

    @api.depends('reversal_line_ids.total_amount')
    def _compute_total_amount(self):
        for record in self:
            record.amount = sum(line.total_amount for line in record.reversal_line_ids)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('atlaxchange.reversal') or 'New'
        return super(reversal, self).create(vals)

    def action_submit_for_approval(self):
        self.state = 'approval'
        self._set_approval_level()
        group_xmlid = {
            'hoo': 'atlaxchange_app.group_hoo',
            'coo': 'atlaxchange_app.group_coo',
            'ceo': 'atlaxchange_app.group_ceo',
        }.get(self.approval_level)
        if group_xmlid:
            group = self.env.ref(group_xmlid)
            users = self.env['res.users'].search([('groups_id', 'in', group.id)])
            self.approver_ids = [(6, 0, users.ids)]

    def _set_approval_level(self):
        if self.amount < 1000000:
            self.approval_level = 'hoo'
        elif self.amount <= 50000000:
            self.approval_level = 'coo'
        elif self.amount > 50000000:
            self.approval_level = 'ceo'

    def action_approve(self):
        if self.env.user not in self.approver_ids:
            raise UserError("Only an assigned approver can approve this reversal.")
        self.state = 'approved'
        if self.env.user.id not in self.approver_ids.ids:
            self.approver_ids = [(4, self.env.user.id)]
        self.message_post(body="Reversal approved successfully.")

    def action_reject(self):
        if self.env.user not in self.approver_ids:
            raise UserError("Only an assigned approver can reject this reversal.")
        self.state = 'rejected'

    @api.depends('approval_level')
    def _compute_is_approver(self):
        for record in self:
            group_xmlid = {
                'hoo': 'atlaxchange_app.group_hoo',
                'coo': 'atlaxchange_app.group_coo',
                'ceo': 'atlaxchange_app.group_ceo',
            }.get(record.approval_level)
            if group_xmlid:
                group = self.env.ref(group_xmlid)
                record.is_approver = self.env.user in self.env['res.users'].search([('groups_id', 'in', group.id)])
            else:
                record.is_approver = False

    # Helper: validate references locally before hitting the API
    def _prevalidate_references(self, references):
        """Return (valid_refs, invalid_details).
        invalid_details is a list of (reference, reason), where reason is 'missing' or the current local status.
        Allowed statuses for reversal are constrained to 'failed' to avoid remote 'status not allowed' errors.
        """
        if not references:
            return [], []

        ledger_model = self.env['atlaxchange.ledger']
        # FIX: search by the correct field on ledger model
        ledgers = ledger_model.search([('transaction_reference', 'in', references)])
        found_by_ref = {rec.transaction_reference: rec for rec in ledgers}

        allowed_statuses = {'failed'}  # adjust if other statuses are allowed by the remote
        valid_refs = []
        invalid_details = []

        for ref in references:
            rec = found_by_ref.get(ref)
            if not rec:
                invalid_details.append((ref, 'missing'))  # not found locally
                continue
            if rec.status not in allowed_statuses:
                invalid_details.append((ref, rec.status))
                continue
            valid_refs.append(ref)

        return valid_refs, invalid_details

    # Helper: parse error JSON from API if present
    def _parse_error_payload(self, response):
        """Attempt to parse response JSON and extract meaningful details."""
        try:
            data = response.json()
        except Exception:
            try:
                data = json.loads(response.text or '{}')
            except Exception:
                return {}

        out = {}
        if isinstance(data, dict):
            out['message'] = data.get('message')
            out['errors'] = data.get('errors')
            out['data'] = data.get('data')
            out['status'] = data.get('status')
            out['timestamp'] = data.get('timestamp')
        return out

    def action_reverse(self):
        """Send batch reversal request to AdminReverseTransactions endpoint with pre-validation and detailed errors."""
        for record in self:
            references = [line.reference for line in record.reversal_line_ids if line.reference]
            if not references:
                raise UserError(_("No references found to reverse."))
            if not record.reason:
                raise UserError(_("Reason is required to perform reversal."))

            # Pre-validate locally to avoid remote 404 for status-not-allowed/missing refs
            valid_refs, invalids = record._prevalidate_references(references)
            if invalids:
                # Build a friendly message listing invalid refs and why
                lines = []
                for ref, why in invalids:
                    if why == 'missing':
                        lines.append(f"- {ref}: not found locally in ledger")
                    else:
                        lines.append(f"- {ref}: local status '{why}' is not reversible")
                detail = "\n".join(lines)
                raise UserError(
                    _("Some references cannot be reversed due to local validation:\n%s\n\nOnly 'failed' transactions are allowed for reversal.")
                    % detail
                )

            if not valid_refs:
                raise UserError(_("No valid references to reverse after validation."))

            client = self.env['atlax.api.client']
            headers = client.build_headers()
            if not headers.get('X-API-KEY') or not headers.get('X-API-SECRET'):
                raise UserError(_("API key or secret is missing. Configure env or system parameters."))

            api_url = client.url('/v1/admin/ledger/transactions/reverse')
            payload = {"references": valid_refs, "reason": record.reason}

            try:
                response = requests.patch(api_url, json=payload, headers=headers, timeout=30)
                if response.status_code in (200, 201):
                    record.state = 'done'
                    record.message_post(
                        body=_("Reversal request sent successfully for %s references.") % len(valid_refs)
                    )
                else:
                    # Try to parse the response for clearer details
                    parsed = record._parse_error_payload(response)
                    base_msg = f"Reversal failed: Status {response.status_code}"
                    extra = []

                    # Help surface the common 404 case with better context
                    if response.status_code == 404:
                        extra.append("Not Found from remote service.")
                        # Show attempted references (trimmed) and their local statuses for quick diagnosis
                        extra.append(f"Attempted references: {', '.join(valid_refs[:20])}" + ("..." if len(valid_refs) > 20 else ""))
                        ledger_recs = self.env['atlaxchange.ledger'].search([('transaction_reference', 'in', valid_refs)])
                        status_pairs = [f"{r.transaction_reference}={r.status or 'n/a'}" for r in ledger_recs][:20]
                        if status_pairs:
                            extra.append("Local statuses: " + ", ".join(status_pairs) + ("..." if len(ledger_recs) > 20 else ""))

                    # Include message/errors/data fields if present
                    if parsed.get('message'):
                        extra.append(f"message: {parsed['message']}")
                    if parsed.get('errors'):
                        extra.append(f"errors: {parsed['errors']}")
                    if parsed.get('data'):
                        extra.append(f"data: {parsed['data']}")

                    detail = " - ".join(extra) if extra else (response.text or response.content)
                    _logger.warning("Reversal API error | %s | payload=%s | response=%s", base_msg, payload, detail)
                    raise UserError(f"{base_msg} - {detail}")
            except UserError:
                # re-raise custom errors untouched
                raise
            except Exception as e:
                _logger.error("Error sending reversal request: %s | References: %s", str(e), valid_refs)
                raise UserError(_("Error sending reversal request: %s") % str(e))


class reversalLine(models.Model):
    _name = 'atlaxchange.reversal.line'
    _description = 'Reversal Line'

    reversal_id = fields.Many2one('atlaxchange.reversal', string="Reversal", ondelete='cascade')
    reference = fields.Char(string='Reference')
    customer_name = fields.Char(string='Customer Name', store=True)
    wallet = fields.Many2one('supported.currency', string='Wallet')
    amount = fields.Float(string="Amount", required=True)
    destination_currency = fields.Many2one('supported.currency', string='Destination Currency')
    total_amount = fields.Float(string='Dest. Amount', digits=(16, 2))