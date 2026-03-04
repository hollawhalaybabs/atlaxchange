# -*- coding: utf-8 -*-
import base64
from odoo import http, fields
from odoo.http import request

class KYBOnboardingController(http.Controller):

    @http.route(['/onboarding/<string:token>'], type='http', auth='public', methods=['GET'])
    def onboarding_form(self, token, **kw):
        review = request.env['compliance.kyb.review'].sudo().search([('access_token', '=', token), ('is_link_active', '=', True)], limit=1)
        if not review:
            return request.render('compliance_kyb_onboarding.onboarding_invalid', {})
        # Show / hide risk section
        show_risk = request.env['ir.config_parameter'].sudo().get_param('compliance_kyb_onboarding.show_risk_public', 'False') == 'True'
        lines = review.requirement_line_ids.filtered(lambda l: l.template_id.show_on_public_form and (show_risk or l.template_id.section != 'risk'))
        # group by section for the template
        sections = {}
        for l in lines.sorted(lambda x: (x.sequence, x.id)):
            sections.setdefault(l.template_id.section, []).append(l)
        return request.render('compliance_kyb_onboarding.onboarding_form', {
            'review': review,
            'sections': sections,
        })

    @http.route(['/onboarding/<string:token>'], type='http', auth='public', methods=['POST'], csrf=True)
    def onboarding_submit(self, token, **post):
        review = request.env['compliance.kyb.review'].sudo().search([('access_token', '=', token), ('is_link_active', '=', True)], limit=1)
        if not review:
            return request.render('compliance_kyb_onboarding.onboarding_invalid', {})

        # Basic company/contact info
        vals = {
            'company_name': post.get('company_name') or review.company_name,
            'contact_name': post.get('contact_name'),
            'contact_role': post.get('contact_role'),
            'contact_email': post.get('contact_email'),
            'contact_phone': post.get('contact_phone'),
            'submitted_by_email': post.get('contact_email') or post.get('submitted_by_email'),
            'submitted_on': fields.Datetime.now(),
        }
        review.write({k:v for k,v in vals.items() if v})

        # Handle file uploads per requirement line:
        # input name pattern: file_line_<line_id>
        attachments = request.httprequest.files
        IrAttachment = request.env['ir.attachment'].sudo()
        for line in review.requirement_line_ids:
            key = f'file_line_{line.id}'
            if key in attachments:
                file_storage = attachments.getlist(key) if hasattr(attachments, 'getlist') else [attachments[key]]
                att_ids = []
                for fs in file_storage:
                    if not fs or not getattr(fs, 'filename', None):
                        continue
                    content = fs.read()
                    att = IrAttachment.create({
                        'name': fs.filename,
                        'datas': base64.b64encode(content),
                        'res_model': 'compliance.kyb.review',
                        'res_id': review.id,
                        'mimetype': fs.mimetype,
                    })
                    att_ids.append(att.id)
                if att_ids:
                    line.write({
                        'attachment_ids': [(4, i) for i in att_ids],
                        'provided': True,
                    })

        return request.render('compliance_kyb_onboarding.onboarding_thank_you', {'review': review})
