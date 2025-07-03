from odoo import models, fields, api, _
from odoo.exceptions import UserError

class Refund(models.Model):
    _name = 'atlaxchange.refund'
    _description = 'Refund/Reversal Process'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default='New')
    refund_line_ids = fields.One2many('atlaxchange.refund.line', 'refund_id', string="Refund Lines")
    amount = fields.Float(string="Total Amount", compute="_compute_total_amount", store=True, readonly=True)
    reason = fields.Text(string="Reason", required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approval', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string="Status", default='draft', readonly=True)
    approver_ids = fields.Many2many(
        'res.users',
        'refund_approver_rel',
        'refund_id',
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

    @api.depends('refund_line_ids.amount')
    def _compute_total_amount(self):
        for record in self:
            record.amount = sum(line.amount for line in record.refund_line_ids)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('atlaxchange.refund') or 'New'
        return super(Refund, self).create(vals)

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
        if self.amount < 2000:
            self.approval_level = 'hoo'
        elif self.amount <= 50000:
            self.approval_level = 'coo'
        elif self.amount > 50000:
            self.approval_level = 'ceo'

    def action_approve(self):
        # Only allow if current user is in approver_ids
        if self.env.user not in self.approver_ids:
            raise UserError("Only an assigned approver can approve this refund.")
        self.state = 'approved'
        # Optionally, add the user to approver_ids if not already present
        if self.env.user.id not in self.approver_ids.ids:
            self.approver_ids = [(4, self.env.user.id)]
        for line in self.refund_line_ids:
            line.ledger_id.status = 'reversed'

    def action_reject(self):
        # Only allow if current user is in approver_ids
        if self.env.user not in self.approver_ids:
            raise UserError("Only an assigned approver can reject this refund.")
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


class RefundLine(models.Model):
    _name = 'atlaxchange.refund.line'
    _description = 'Refund Line'

    refund_id = fields.Many2one('atlaxchange.refund', string="Refund", ondelete='cascade')
    ledger_id = fields.Many2one('atlaxchange.ledger', string="Ledger Entry", required=True)
    amount = fields.Float(string="Amount", required=True)
    reference = fields.Char(string='Reference')
