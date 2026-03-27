# -*- coding: utf-8 -*-

from odoo import models


class ComplianceKYBReviewReport(models.AbstractModel):
    _name = "report.compliance_kyb_onboarding.report_kyb_review_pdf"
    _description = "Compliance KYB Review PDF Report"

    def _get_report_values(self, docids, data=None):
        docs = self.env["compliance.kyb.report.wizard"].browse(docids)
        wizard = docs[:1]
        report_data = wizard._prepare_report_data() if wizard else {}
        return {
            "doc_ids": docs.ids,
            "doc_model": "compliance.kyb.report.wizard",
            "docs": docs,
            "company": self.env.company,
            "report_data": report_data,
        }