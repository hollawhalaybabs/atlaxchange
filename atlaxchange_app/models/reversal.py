from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging

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

    def action_reverse(self):
        """Send batch reversal request to AdminReverseTransactions endpoint."""
        references = [line.reference for line in self.reversal_line_ids if line.reference]
        if not references:
            raise UserError("No references found to reverse.")
        if not self.reason:
            raise UserError("Reason is required to perform reversal.")

        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')
        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Please configure them in System Parameters."))

        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        api_url = "https://api.atlaxchange.com/api/v1/admin/ledger/transactions/reverse"
        payload = {"references": references, "reason": self.reason}
        try:
            response = requests.patch(api_url, json=payload, headers=headers, timeout=30)
            if response.status_code in (200, 201):
                self.state = 'done'
                self.message_post(body="Reversal request sent successfully.")
            else:
                raise UserError(f"Reversal failed: Status {response.status_code} - {response.text or response.content}")
        except Exception as e:
            _logger.error("Error sending reversal request: %s | References: %s", str(e), references)
            raise UserError(f"Error sending reversal request: {str(e)}")


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