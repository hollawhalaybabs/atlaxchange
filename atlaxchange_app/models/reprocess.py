from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging

_logger = logging.getLogger(__name__)

class reprocess(models.Model):
    _name = 'atlaxchange.reprocess'
    _description = 'reprocess/Reversal Process'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default='New')
    reprocess_line_ids = fields.One2many('atlaxchange.reprocess.line', 'reprocess_id', string="reprocess Lines")
    amount = fields.Float(string="Total Amount", compute="_compute_total_amount", store=True, readonly=True)
    reason = fields.Text(string="Reason")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approval', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('done', 'Done'),
        ('rejected', 'Rejected')
    ], string="Status", default='draft', readonly=True)
    approver_ids = fields.Many2many(
        'res.users',
        'reprocess_approver_rel',
        'reprocess_id',
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

    @api.depends('reprocess_line_ids.total_amount')
    def _compute_total_amount(self):
        for record in self:
            record.amount = sum(line.total_amount for line in record.reprocess_line_ids)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('atlaxchange.reprocess') or 'New'
        return super(reprocess, self).create(vals)

    def action_submit_for_approval(self):
        self.state = 'approval'
        self._set_approval_level()
        # Set approvers based on approval_level
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
        # Only allow if current user is in approver_ids
        if self.env.user not in self.approver_ids:
            raise UserError("Only an assigned approver can approve this reprocess.")
        self.state = 'approved'
        # Optionally, add the user to approver_ids if not already present
        if self.env.user.id not in self.approver_ids.ids:
            self.approver_ids = [(4, self.env.user.id)]
        self.message_post(body="Reprocess approved successfully.")


    def action_reject(self):
        # Only allow if current user is in approver_ids
        if self.env.user not in self.approver_ids:
            raise UserError("Only an assigned approver can reject this reprocess.")
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

    def action_reprocess(self):
        references = [line.reference for line in self.reprocess_line_ids if line.reference]
        if not references:
            raise UserError("No references found to reprocess.")

        # Fetch API key and secret from system parameters
        api_key = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_key')
        api_secret = self.env['ir.config_parameter'].sudo().get_param('fetch_users_api.api_secret')

        if not api_key or not api_secret:
            raise UserError(_("API key or secret is missing. Please configure them in System Parameters."))

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-API-SECRET": api_secret
        }

        api_url = "https://api.atlaxchange.com/api/v1/admin/payments/reprocess"
        payload = {"references": references}
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                self.state = 'done'
                self.message_post(body="Reprocess request sent successfully.")
            else:
                raise UserError(f"Reprocess failed: {response.text or response.content}")
        except Exception as e:
            _logger.error(f"Error sending reprocess request: {str(e)} | References: {references}")
            raise UserError(f"Error sending reprocess request: {str(e)}")


class reprocessLine(models.Model):
    _name = 'atlaxchange.reprocess.line'
    _description = 'reprocess Line'

    reprocess_id = fields.Many2one('atlaxchange.reprocess', string="reprocess", ondelete='cascade')
    reference = fields.Char(string='Reference')
    customer_name = fields.Char(string='Customer Name', store=True)
    wallet = fields.Many2one('supported.currency', string='Wallet')
    amount = fields.Float(string="Amount", required=True)
    destination_currency = fields.Many2one('supported.currency', string='Destination Currency')
    total_amount = fields.Float(string='Dest. Amount', digits=(16, 2))
