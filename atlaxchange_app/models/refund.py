from odoo import models, fields, api

class Refund(models.Model):
    _name = 'atlaxchange.refund'
    _description = 'Refund/Reversal Process'

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
    approver_id = fields.Many2one('res.users', string="Approver", readonly=True)
    approval_level = fields.Selection([
        ('hoo', 'HOO'),
        ('hot_t', 'HOT&T'),
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

    def _set_approval_level(self):
        if self.amount < 5000000:
            self.approval_level = 'hoo'
        elif 5000000 <= self.amount <= 50000000:
            self.approval_level = 'hot_t'
        elif self.amount > 50000000:
            self.approval_level = 'coo'

    def action_approve(self):
        self.state = 'approved'
        self.approver_id = self.env.user
        for line in self.refund_line_ids:
            line.ledger_id.status = 'reversed'

    def action_reject(self):
        self.state = 'rejected'

    @api.depends('approval_level')
    def _compute_is_approver(self):
        for record in self:
            if record.approval_level == 'hoo':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_hoo')
            elif record.approval_level == 'hot_t':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_hot')
            elif record.approval_level == 'coo':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_coo')
            elif record.approval_level == 'ceo':
                record.is_approver = self.env.user.has_group('atlaxchange_app.group_ceo')
            else:
                record.is_approver = False


class RefundLine(models.Model):
    _name = 'atlaxchange.refund.line'
    _description = 'Refund Line'

    refund_id = fields.Many2one('atlaxchange.refund', string="Refund", ondelete='cascade')
    ledger_id = fields.Many2one('atlaxchange.ledger', string="Ledger Entry", required=True)
    amount = fields.Float(string="Amount", required=True)
    reference = fields.Char(string='Reference')
