from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class AtlaxBDTag(models.Model):
    _name = "atlax.bd.tag"
    _description = "BD Tag"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer(string="Color")


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    bd_opportunity_id = fields.Many2one(
        "atlax.bd.opportunity",
        string="BD Opportunity",
        index=True,
        ondelete="set null",
    )


class AtlaxBusinessOpportunity(models.Model):
    _name = "atlax.bd.opportunity"
    _description = "Business Development Opportunity"
    _order = "name, datetime desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Business Name", required=True, tracking=True)
    trade_name = fields.Char(string="Trade Name", required=True, tracking=True)
    type = fields.Selection(
            selection=[
            ("customer_imto", "Customer (IMTO)"),
            ("payout_provider", "Payout Provider"),
            ("liquidity_provider", "Liquidity Provider"),
            ("bank", "Bank"),
            ("crypto_provider", "Crypto Provider"),
            ("msb_provider", "MSB Provider"),
        ],
        string="Partnership Type",
        required=True,
        tracking=True,
    )
    # vendor_type = fields.Selection(
    #     selection=[
    #         ("payout", "Payout"),
    #         ("collection", "Collection"),
    #         ("payout_collection", "Payout and Collection"),
    #     ],
    #     string="Vendor Type",
    #     tracking=True,
    # )

    email = fields.Char(string="Email", required=True, tracking=True)
    country_id = fields.Many2one(
        "res.country",
        string="Country of Location",
        tracking=True,
    )
    website = fields.Char(string="Website")
    datetime = fields.Datetime(
        string="Datetime",
        default=fields.Datetime.now,
        readonly=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("proposal_sent", "Proposal Sent"),
            ("nda_sent", "NDA Sent/Received"),
            ("commercial_discussion", "Commercial Discussion"),
            ("kyb_review", "KYB Approved"),
            ("contract_signoff", "SLA Signoff"),
            ("onhold", "On Hold"),
            ("done", "Done"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        group_expand="_group_expand_state",
    )

    settlement_currency_id = fields.Many2one(
        "supported.currency",
        string="Settlement Currency",
    )

    kyb_status = fields.Selection(
        selection=[
            ("in_process", "In-process"),
            ("completed", "Completed"),
        ],
        string="KYB Status",
    )

    funding_type = fields.Selection(
        selection=[
            ("pre_funding", "Pre-funding"),
            ("post_funding", "Post funding"),
        ],
        string="Funding Type"
    )

    remark = fields.Text(string="Remark/Note")

    nda_sent_received_attachment_ids = fields.Many2many(
        "ir.attachment",
        "atlax_bd_nda_sent_received_attachment_rel",
        "bd_id",
        "attachment_id",
        string="NDA Sent/Received Document",
        help="Upload NDA sent/received documents for this BD opportunity.",
    )

    fee_ids = fields.One2many(
        "atlax.bd.fee",
        "bd_id",
        string="Fees",
    )

    assign_staff_id = fields.Many2one(
        "hr.employee",
        string="Assign Staff",
        required=True,
        default=lambda self: self.env["hr.employee"].search([("user_id", "=", self.env.uid)], limit=1),
    )

    helpdesk_ticket_count = fields.Integer(
        string="Helpdesk Tickets",
        compute="_compute_helpdesk_ticket_count",
    )

    tag_ids = fields.Many2many(
        "atlax.bd.tag",
        "atlax_bd_opportunity_tag_rel",
        "bd_opportunity_id",
        "tag_id",
        string="Tags",
        tracking=True,
    )

    # -----------------------------
    # Internal email helpers
    # -----------------------------
    def _employee_email(self, employee):
        """Return best-effort internal email for an hr.employee record."""
        if not employee:
            return False
        return (employee.work_email or employee.user_id.email or employee.user_id.partner_id.email or "").strip() or False

    def _group_user_emails(self, group_xmlids):
        """Collect unique emails for all users in given res.groups xmlids."""
        emails = set()
        for xmlid in (group_xmlids or []):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if not group:
                continue
            for user in group.users:
                email = (user.email or user.partner_id.email or "").strip()
                if email:
                    emails.add(email)
        return sorted(emails)

    def _email_groups_for_action(self, action_name):
        """
        Central mapping: action method name -> list of group xmlids to notify.
        Adjust here to match your internal process/ownership.
        """
        mapping = {
            "action_set_draft": [
                "atlaxchange_app.group_business_dev_manager",
                "atlaxchange_app.group_business_dev_officer"
            ],
            "action_proposal_sent": [
                "atlaxchange_app.group_business_dev_manager",
                "atlaxchange_app.group_business_dev_officer"
            ],
            "action_nda_sent": [
                "atlaxchange_app.group_compliance_officer",
                "atlaxchange_app.group_compliance_manager",
            ],
            "action_set_commercial_discussion": [
                "atlaxchange_app.group_business_dev_manager",
                "atlaxchange_app.group_business_dev_officer",
                "atlaxchange_app.group_coo",
            ],
            "action_set_kyb_review": [
                "atlaxchange_app.group_compliance_officer",
                "atlaxchange_app.group_compliance_manager",
            ],
            "action_set_onhold": [
                "atlaxchange_app.group_business_dev_manager",
                "atlaxchange_app.group_business_dev_officer",
                "atlaxchange_app.group_compliance_manager",
            ],
            "action_set_done": [
                "atlaxchange_app.group_business_dev_manager",
                "atlaxchange_app.group_business_dev_officer",
                "atlaxchange_app.group_coo",
                "atlaxchange_app.group_ceo",
            ],
            "action_send_reminder_email": [
                "atlaxchange_app.group_business_dev_manager",
                "atlaxchange_app.group_business_dev_officer",
            ],
        }
        return mapping.get(action_name, [])

    def _internal_recipient_emails(self, action_name, include_assigned_staff=True):
        """Compute internal recipient email addresses for an action."""
        self.ensure_one()

        emails = set(self._group_user_emails(self._email_groups_for_action(action_name)))

        if include_assigned_staff:
            staff_email = self._employee_email(self.assign_staff_id)
            if staff_email:
                emails.add(staff_email)

        return sorted(e for e in emails if e)

    def _send_internal_template_email(self, template_xmlid, action_name, include_assigned_staff=True):
        """Send template email to internal staff without opening the compose wizard."""
        self.ensure_one()

        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            raise UserError(_("Email template not found: %s") % template_xmlid)

        emails = self._internal_recipient_emails(action_name, include_assigned_staff=include_assigned_staff)
        if not emails:
            raise UserError(_("No internal recipients found to notify."))

        email_values = {
            "email_to": ", ".join(emails),
        }

        template.send_mail(self.id, force_send=True, email_values=email_values)
        return True

    # -----------------------------
    # State transition helpers (+ automatic internal email)
    # -----------------------------
    def action_set_draft(self):
        for rec in self:
            rec.state = "draft"
            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_reminder",
                "action_set_draft",
                include_assigned_staff=True,
            )
        return True

    def action_proposal_sent(self):
        for rec in self:
            rec.state = "proposal_sent"
            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_status_proposal_sent",
                "action_proposal_sent",
                include_assigned_staff=True,
            )
        return True

    def action_nda_sent(self):
        for rec in self:
            rec.state = "nda_sent"
            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_status_nda_sent",
                "action_nda_sent",
                include_assigned_staff=True,
            )
        return True

    def action_set_commercial_discussion(self):
        for rec in self:
            rec.state = "commercial_discussion"
            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_status_commercial_discussion",
                "action_set_commercial_discussion",
                include_assigned_staff=True,
            )
        return True

    def action_set_kyb_review(self):
        for rec in self:
            rec.state = "kyb_review"

            rec.env["compliance.kyb.review"].create({
                "bd_model": rec._name,
                "bd_res_id": rec.id,
                "company_name": rec.name,
                "trade_name": rec.trade_name,
                "type": rec.type,
                "country_id": rec.country_id.id,
                "contact_email": rec.email,
            })

            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_status_kyb_review",
                "action_set_kyb_review",
                include_assigned_staff=True,
            )
        return True

    def action_set_onhold(self):
        for rec in self:
            rec.state = "onhold"
            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_status_onhold",
                "action_set_onhold",
                include_assigned_staff=True,
            )
        return True

    def action_set_done(self):
        for rec in self:
            rec.state = "done"
            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_status_done",
                "action_set_done",
                include_assigned_staff=True,
            )
        return True

    def action_send_reminder_email(self):
        for rec in self:
            rec._send_internal_template_email(
                "atlax_business_development.email_template_bd_reminder",
                "action_send_reminder_email",
                include_assigned_staff=True,
            )
        return True

    @api.constrains("state", "settlement_currency_id", "fee_ids")
    def _check_state_requirements(self):
        for rec in self:
            if rec.state == "commercial_discussion":
                if not rec.settlement_currency_id:
                    raise ValidationError(_("Settlement Currency is required at Commercial Discussion state."))
                if not rec.fee_ids:
                    raise ValidationError(_("At least one Fee line is required at Commercial Discussion state."))

    def _compute_helpdesk_ticket_count(self):
        Ticket = self.env["helpdesk.ticket"]
        for rec in self:
            rec.helpdesk_ticket_count = Ticket.search_count([("bd_opportunity_id", "=", rec.id)])

    def action_open_helpdesk_tickets(self):
        self.ensure_one()
        action = self.env.ref("helpdesk.helpdesk_ticket_action_main_tree", raise_if_not_found=False)
        if action:
            action = action.read()[0]
        else:
            action = {
                "type": "ir.actions.act_window",
                "name": _("Helpdesk Tickets"),
                "res_model": "helpdesk.ticket",
                "view_mode": "tree,form",
            }

        action["domain"] = [("bd_opportunity_id", "=", self.id)]
        action["context"] = dict(self.env.context, default_bd_opportunity_id=self.id)
        return action

    @api.model
    def _group_expand_state(self, states, domain, order):
        selection = self._fields["state"].selection
        if callable(selection):
            selection = selection(self)
        return [value for value, _label in (selection or [])]

    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        res = super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)

        groupby_list = groupby
        if isinstance(groupby, str):
            groupby_list = [g.strip() for g in groupby.split(',') if g.strip()]

        if groupby_list and groupby_list[0].split(":")[0] == "state":
            selection = self._fields["state"].selection
            if callable(selection):
                selection = selection(self)
            selection = selection or []

            groups_by_state = {g.get("state"): g for g in res}
            ordered_res = []

            for value, _label in selection:
                group = groups_by_state.get(value)
                if group:
                    ordered_res.append(group)
                else:
                    ordered_res.append(
                        {
                            "state": value,
                            "__count": 0,
                            "__domain": list(domain) + [("state", "=", value)],
                        }
                    )

            # Preserve any unexpected groups (e.g. False) at the end.
            for group in res:
                if group.get("state") not in {v for v, _l in selection}:
                    ordered_res.append(group)

            res = ordered_res

        return res


class AtlaxBusinessFee(models.Model):
    _name = "atlax.bd.fee"
    _description = "Business Development Fee"

    bd_id = fields.Many2one(
        "atlax.bd.opportunity",
        string="Opportunity",
        ondelete="cascade",
    )
    source_currency_id = fields.Many2one(
        "supported.currency",
        string="Source Currency",
        required=True,
    )
    target_currency_id = fields.Many2one(
        "supported.currency",
        string="Target Currency",
        required=True,
    )
    corridor = fields.Char(
        string="Corridor",
        compute="_compute_corridor",
        store=True,
    )
    fee_amount = fields.Float(string="Fee Amount")

    @api.depends("source_currency_id", "target_currency_id")
    def _compute_corridor(self):
        for rec in self:
            if rec.source_currency_id and rec.target_currency_id:
                rec.corridor = "%s/%s" % (
                    rec.source_currency_id.currency_code,
                    rec.target_currency_id.currency_code,
                )
            else:
                rec.corridor = False
