from odoo import models, fields
import time
import logging
import odoo.http as http
from odoo.http import request

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
	_inherit = "ir.http"

	@classmethod
	def _get_timeout_seconds(cls):
		"""Return inactivity timeout (in seconds) from system parameters.

		Falls back to 10 minutes when not configured or invalid.
		"""
		try:
			# Stored as seconds in ir.config_parameter
			param = request.env["ir.config_parameter"].sudo().get_param(
				"user_inactivity_timeout", default="900"
			)
			timeout = int(param)
			# Minimum 60 seconds safety floor
			return max(timeout, 60)
		except Exception:  # pragma: no cover - defensive fallback
			return 600

	@classmethod
	def _expire_if_inactive(cls):
		"""Expire current session if inactive longer than configured timeout."""
		if not request or not request.session or not request.session.uid:
			return

		try:
			timeout_s = cls._get_timeout_seconds()
			now = int(time.time())
			last_activity = request.session.get("last_activity_ts")

			if last_activity and (now - int(last_activity) > timeout_s):
				# Keep sid to also drop it from the session store
				sid = request.session.sid

				# Logout will clear uid and csrf, ensuring the next dispatch redirects
				request.session.logout()

				# Best-effort: remove the old server-side session
				try:
					http.root.session_store.delete(sid)
				except Exception as e:  # pragma: no cover - store backend specific
					_logger.debug("Failed to delete expired session %s: %s", sid, e)

				# Also clear user's active_session_sid if it pointed to this sid
				try:
					if sid and request.env.user.exists():
						user = request.env.user.sudo()
						if getattr(user, "active_session_sid", False) == sid:
							user.write({"active_session_sid": False})
				except Exception:
					pass
		except Exception as e:  # pragma: no cover - never break requests due to this
			_logger.debug("Inactivity check failed: %s", e)

	@classmethod
	def _dispatch(cls, endpoint):
		"""Wrap the core dispatcher to enforce server-side inactivity timeout.

		- If session is inactive beyond the threshold, we log it out before
		  dispatch. The core auth machinery will then redirect/deny as usual.
		- Otherwise, we proceed and update last_activity timestamp after handling
		  the request (only for authenticated sessions).
		"""
		# Pre-dispatch: expire session if needed
		cls._expire_if_inactive()

		# Dispatch the request via standard Odoo flow
		response = super()._dispatch(endpoint)

		# Post-dispatch: update last activity for authenticated users
		try:
			if request and request.session and request.session.uid:
				# Do not consider bus longpolling as user activity
				path = getattr(request.httprequest, "path", "") or ""
				if not path.startswith("/longpolling"):
					request.session["last_activity_ts"] = int(time.time())
		except Exception:  # pragma: no cover - never block responses
			pass

		return response
