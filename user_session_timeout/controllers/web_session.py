from odoo import http
import time
from odoo.http import request
from odoo.addons.web.controllers.main import Session as WebSession


class Session(WebSession):
    @http.route("/web/session/authenticate", type="json", auth="none")
    def authenticate(self, db, login, password, base_location=None):
        # Delegate to core authentication
        res = super().authenticate(db, login, password, base_location=base_location)

        # On successful login, enforce single active session per user
        uid = res.get("uid")
        if uid:
            # Current session SID
            current_sid = request.session.sid

            # Persist last activity right away for server-side timeout
            request.session["last_activity_ts"] = request.session.get(
                "last_activity_ts"
            ) or int(time.time())

            user = request.env["res.users"].sudo().browse(uid)
            if user.exists():
                previous_sid = user.active_session_sid
                # If there is a previous session for this user, drop it
                if previous_sid and previous_sid != current_sid:
                    try:
                        http.root.session_store.delete(previous_sid)
                    except Exception:
                        # Best effort: if backend doesn't support delete, ignore
                        pass
                # Store the new active session sid
                user.write({"active_session_sid": current_sid})

        return res

    @http.route("/web/session/destroy", type="json", auth="user")
    def destroy(self):
        # Clear user's active session on explicit logout
        try:
            sid = request.session.sid
            user = request.env.user.sudo()
            if getattr(user, "active_session_sid", False) == sid:
                user.write({"active_session_sid": False})
        except Exception:
            pass
        return super().destroy()
