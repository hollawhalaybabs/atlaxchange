/** @odoo-module **/

import { registry } from "@web/core/registry";
// Import the LedgerDashboard component defined in static/src/js/ledger_dashboard.js
import { LedgerDashboard } from "../js/ledger_dashboard";

registry.category("actions").add("atlaxchange_ledger.ledger_dashboard_action", LedgerDashboard);