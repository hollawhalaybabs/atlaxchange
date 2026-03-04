# -*- coding: utf-8 -*-

import base64
import io
import re
import zipfile

from odoo import http
from odoo.http import request


def _safe_filename(name: str) -> str:
    name = (name or "").strip() or "document"
    name = re.sub(r"[\\/\x00-\x1f\x7f]+", "_", name)
    return name[:180]


class KYBDocumentsController(http.Controller):

    @http.route(
        ["/compliance_kyb_onboarding/kyb/<int:review_id>/documents.zip"],
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def download_kyb_documents_zip(self, review_id, **kw):
        review = request.env["compliance.kyb.review"].browse(review_id)
        if not review.exists():
            return request.not_found()

        # Access check (will raise if user can't read)
        review.check_access_rights("read")
        review.check_access_rule("read")

        attachments = request.env["ir.attachment"].search([
            ("res_model", "=", "compliance.kyb.review"),
            ("res_id", "=", review.id),
        ])

        # Also include attachments linked to requirement lines (in case future logic stores them differently)
        for line in review.requirement_line_ids:
            attachments |= line.attachment_ids

        attachments = attachments.exists()
        if not attachments:
            body = b"No documents attached."
            return request.make_response(body, headers=[("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])

        buffer = io.BytesIO()
        used_names = set()

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for att in attachments:
                filename = _safe_filename(att.name)
                if not filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt')):
                    # Keep original name; don't guess extensions. This just prevents empty names.
                    filename = filename or "document"

                candidate = filename
                counter = 1
                while candidate in used_names:
                    counter += 1
                    candidate = f"{filename.rsplit('.', 1)[0]}_{counter}.{filename.rsplit('.', 1)[1]}" if "." in filename else f"{filename}_{counter}"
                used_names.add(candidate)

                datas_b64 = att.datas
                if not datas_b64:
                    continue

                try:
                    content = base64.b64decode(datas_b64)
                except Exception:
                    continue

                zf.writestr(candidate, content)

        zip_bytes = buffer.getvalue()
        download_name = f"KYB_{_safe_filename(review.name)}_documents.zip"

        headers = [
            ("Content-Type", "application/zip"),
            ("Content-Disposition", f'attachment; filename="{download_name}"'),
            ("Content-Length", str(len(zip_bytes))),
        ]
        return request.make_response(zip_bytes, headers=headers)
