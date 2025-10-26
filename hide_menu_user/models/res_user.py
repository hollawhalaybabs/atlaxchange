# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2021-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################

from odoo import models, fields, api


class HideMenuUser(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        """
        Else the menu will be still hidden even after removing from the list
        """
        self.clear_caches()
        return super(HideMenuUser, self).create(vals_list)

    def write(self, vals):
        """
        Else the menu will be still hidden even after removing from the list
        """
        # Capture original menus per user (only if hide_menu_ids is being changed)
        original_menus_map = {}
        if 'hide_menu_ids' in vals:
            for user in self:
                original_menus_map[user.id] = set(user.hide_menu_ids.ids)

        res = super(HideMenuUser, self).write(vals)

        Menu = self.env['ir.ui.menu']
        updating_hide = 'hide_menu_ids' in vals

        for user in self:
            # Ensure every selected hidden menu contains the user in restrict_user_ids
            if user.hide_menu_ids:
                user.hide_menu_ids.write({'restrict_user_ids': [(4, user.id)]})

            if updating_hide:
                # Menus previously linked but now removed should no longer restrict this user
                old_ids = original_menus_map.get(user.id, set())
                current_ids = set(user.hide_menu_ids.ids)
                removed_ids = old_ids - current_ids
                if removed_ids:
                    menus_to_clean = Menu.browse(list(removed_ids)).exists()
                    for menu in menus_to_clean:
                        menu.write({'restrict_user_ids': [(3, user.id)]})

        self.clear_caches()
        return res

    def _get_is_admin(self):
        """
        The Hide specific menu tab will be hidden for the Admin user form.
        Else once the menu is hidden, it will be difficult to re-enable it.
        """
        for rec in self:
            rec.is_admin = False
            if rec.id == self.env.ref('base.user_admin').id:
                rec.is_admin = True

    hide_menu_ids = fields.Many2many('ir.ui.menu', string="Menu", store=True,
                                     help='Select menu items that needs to be '
                                          'hidden to this user ')
    is_admin = fields.Boolean(compute=_get_is_admin)


class RestrictMenu(models.Model):
    _inherit = 'ir.ui.menu'

    restrict_user_ids = fields.Many2many('res.users')
