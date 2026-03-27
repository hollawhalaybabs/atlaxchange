# -*- coding: utf-8 -*-

import base64
from datetime import datetime, time
from io import BytesIO

import xlsxwriter

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ComplianceKYBReportWizard(models.TransientModel):
    _name = "compliance.kyb.report.wizard"
    _description = "Compliance KYB Report Wizard"

    date_from = fields.Date(string="Start Date", required=True, default=fields.Date.context_today)
    date_to = fields.Date(string="End Date", required=True, default=fields.Date.context_today)
    date_basis = fields.Selection(
        selection=[
            ("create_date", "Created On"),
            ("submitted_on", "Submitted On"),
            ("verified_on", "Verified On"),
        ],
        string="Period Based On",
        required=True,
        default="create_date",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Review State",
    )
    assigned_to = fields.Many2one("hr.employee", string="Assigned To")
    report_format = fields.Selection(
        selection=[("pdf", "PDF"), ("xlsx", "Excel")],
        string="Report Format",
        required=True,
        default="pdf",
    )
    output_file = fields.Binary(string="Generated File", readonly=True)
    output_filename = fields.Char(string="Filename", readonly=True)

    @api.constrains("date_from", "date_to")
    def _check_date_range(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise UserError(_("Start Date cannot be after End Date."))

    def _get_period_bounds(self):
        self.ensure_one()
        start_dt = datetime.combine(self.date_from, time.min)
        end_dt = datetime.combine(self.date_to, time.max)
        return fields.Datetime.to_string(start_dt), fields.Datetime.to_string(end_dt)

    def _get_report_domain(self):
        self.ensure_one()
        date_from, date_to = self._get_period_bounds()
        domain = [
            (self.date_basis, ">=", date_from),
            (self.date_basis, "<=", date_to),
        ]
        if self.state:
            domain.append(("state", "=", self.state))
        if self.assigned_to:
            domain.append(("assigned_to", "=", self.assigned_to.id))
        return domain

    def _get_reviews(self):
        self.ensure_one()
        return self.env["compliance.kyb.review"].search(self._get_report_domain(), order="create_date desc, id desc")

    def _get_selection_label(self, field_name, value):
        if not value:
            return ""
        selection = dict(self.env["compliance.kyb.review"]._fields[field_name].selection)
        return selection.get(value, value)

    def _document_status(self, documents):
        if not documents:
            return _("Not Added")
        if all(document.state == "approved" for document in documents):
            return _("Approved")
        return _("Pending")

    def _prepare_report_data(self):
        self.ensure_one()
        reviews = self._get_reviews()
        rows = []
        summary = {
            "total_reviews": len(reviews),
            "draft_count": 0,
            "in_review_count": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 0,
            "missing_requirement_total": 0,
            "pending_nda_count": 0,
            "pending_sla_count": 0,
        }

        for review in reviews:
            state_label = self._get_selection_label("state", review.state)
            risk_label = self._get_selection_label("risk_assessment", review.risk_assessment)
            type_label = self._get_selection_label("type", review.type)
            nda_status = self._document_status(review.nda_document_ids)
            sla_status = self._document_status(review.sla_document_ids)
            missing_count = review.missing_requirement_count

            if review.state == "draft":
                summary["draft_count"] += 1
            elif review.state == "in_review":
                summary["in_review_count"] += 1
            elif review.state == "approved":
                summary["approved_count"] += 1
            elif review.state == "rejected":
                summary["rejected_count"] += 1

            if review.risk_assessment == "high":
                summary["high_risk_count"] += 1
            elif review.risk_assessment == "medium":
                summary["medium_risk_count"] += 1
            elif review.risk_assessment == "low":
                summary["low_risk_count"] += 1

            summary["missing_requirement_total"] += missing_count
            if nda_status == _("Pending"):
                summary["pending_nda_count"] += 1
            if sla_status == _("Pending"):
                summary["pending_sla_count"] += 1

            rows.append({
                "reference": review.name,
                "company_name": review.company_name or "",
                "trade_name": review.trade_name or "",
                "partnership_type": type_label,
                "country": review.country_id.name or "",
                "assigned_to": review.assigned_to.name or "",
                "state": state_label,
                "risk_assessment": risk_label,
                "submitted_on": fields.Datetime.to_string(review.submitted_on) if review.submitted_on else "",
                "verified_on": fields.Datetime.to_string(review.verified_on) if review.verified_on else "",
                "missing_requirement_count": missing_count,
                "nda_status": nda_status,
                "sla_status": sla_status,
                "primary_email": review.contact_email or "",
            })

        return {
            "wizard": self,
            "reviews": reviews,
            "rows": rows,
            "summary": summary,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "date_basis_label": dict(self._fields["date_basis"].selection).get(self.date_basis),
            "state_filter_label": dict(self._fields["state"].selection).get(self.state) if self.state else _("All States"),
            "assigned_to_name": self.assigned_to.name or _("All Assignees"),
        }

    def action_generate_report(self):
        self.ensure_one()
        if self.report_format == "pdf":
            return self.env.ref("compliance_kyb_onboarding.action_report_kyb_review_pdf").report_action(self)
        return self.action_export_xlsx()

    def action_export_xlsx(self):
        self.ensure_one()
        report_data = self._prepare_report_data()
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        summary_sheet = workbook.add_worksheet("Summary")
        detail_sheet = workbook.add_worksheet("Details")

        title_format = workbook.add_format({"bold": True, "font_size": 14})
        header_format = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        cell_format = workbook.add_format({"border": 1})

        summary_sheet.set_column("A:A", 28)
        summary_sheet.set_column("B:B", 18)
        detail_sheet.set_column("A:M", 20)

        row = 0
        summary_sheet.write(row, 0, _("KYB General Report"), title_format)
        row += 2
        summary_sheet.write(row, 0, _("Period"), header_format)
        summary_sheet.write(row, 1, f"{report_data['date_from']} to {report_data['date_to']}", cell_format)
        row += 1
        summary_sheet.write(row, 0, _("Period Based On"), header_format)
        summary_sheet.write(row, 1, report_data["date_basis_label"], cell_format)
        row += 1
        summary_sheet.write(row, 0, _("State Filter"), header_format)
        summary_sheet.write(row, 1, report_data["state_filter_label"], cell_format)
        row += 1
        summary_sheet.write(row, 0, _("Assigned To"), header_format)
        summary_sheet.write(row, 1, report_data["assigned_to_name"], cell_format)
        row += 2

        summary_rows = [
            (_("Total Reviews"), report_data["summary"]["total_reviews"]),
            (_("Draft"), report_data["summary"]["draft_count"]),
            (_("In Review"), report_data["summary"]["in_review_count"]),
            (_("Approved"), report_data["summary"]["approved_count"]),
            (_("Rejected"), report_data["summary"]["rejected_count"]),
            (_("High Risk"), report_data["summary"]["high_risk_count"]),
            (_("Medium Risk"), report_data["summary"]["medium_risk_count"]),
            (_("Low Risk"), report_data["summary"]["low_risk_count"]),
            (_("Missing Requirements"), report_data["summary"]["missing_requirement_total"]),
            (_("Pending NDA"), report_data["summary"]["pending_nda_count"]),
            (_("Pending SLA"), report_data["summary"]["pending_sla_count"]),
        ]
        for label, value in summary_rows:
            summary_sheet.write(row, 0, label, header_format)
            summary_sheet.write(row, 1, value, cell_format)
            row += 1

        headers = [
            _("Reference"),
            _("Business Name"),
            _("Trade Name"),
            _("Partnership Type"),
            _("Country"),
            _("Assigned To"),
            _("State"),
            _("Risk"),
            _("Submitted On"),
            _("Verified On"),
            _("Missing Requirements"),
            _("NDA Status"),
            _("SLA Status"),
            _("Primary Email"),
        ]
        for col, header in enumerate(headers):
            detail_sheet.write(0, col, header, header_format)

        for row_index, row_data in enumerate(report_data["rows"], start=1):
            detail_sheet.write(row_index, 0, row_data["reference"], cell_format)
            detail_sheet.write(row_index, 1, row_data["company_name"], cell_format)
            detail_sheet.write(row_index, 2, row_data["trade_name"], cell_format)
            detail_sheet.write(row_index, 3, row_data["partnership_type"], cell_format)
            detail_sheet.write(row_index, 4, row_data["country"], cell_format)
            detail_sheet.write(row_index, 5, row_data["assigned_to"], cell_format)
            detail_sheet.write(row_index, 6, row_data["state"], cell_format)
            detail_sheet.write(row_index, 7, row_data["risk_assessment"], cell_format)
            detail_sheet.write(row_index, 8, row_data["submitted_on"], cell_format)
            detail_sheet.write(row_index, 9, row_data["verified_on"], cell_format)
            detail_sheet.write(row_index, 10, row_data["missing_requirement_count"], cell_format)
            detail_sheet.write(row_index, 11, row_data["nda_status"], cell_format)
            detail_sheet.write(row_index, 12, row_data["sla_status"], cell_format)
            detail_sheet.write(row_index, 13, row_data["primary_email"], cell_format)

        workbook.close()
        output.seek(0)
        file_content = output.read()
        output.close()

        filename = f"kyb_general_report_{self.date_from}_{self.date_to}.xlsx"
        self.write({
            "output_file": base64.b64encode(file_content),
            "output_filename": filename,
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/?model={self._name}&id={self.id}&field=output_file&download=true&filename={filename}",
            "target": "self",
        }