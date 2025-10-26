/** @odoo-module **/

import { registry } from "@web/core/registry";
import { LedgerDashboard } from "./components/LedgerDashboard";

registry.category("actions").add("atlaxchange_ledger.ledger_dashboard_action", LedgerDashboard);