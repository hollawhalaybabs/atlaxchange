/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { jsonrpc } from "@web/core/network/rpc_service";

export class LedgerDashboard extends Component {
    setup() {
        this.state = useState({
            records: [],
            filters: {
                status: "",
                type: "",
                date_from: "",
                date_to: "",
            },
            loading: true,
        });

        onWillStart(async () => {
            await this.fetchData();
        });
    }

    async fetchData() {
        this.state.loading = true;
        const result = await jsonrpc("/atlaxchange/ledger_dashboard/data", [this.state.filters]);
        this.state.records = result.records;
        this.state.loading = false;
    }

    async onFilterChange(ev) {
        const { name, value } = ev.target;
        this.state.filters[name] = value;
        await this.fetchData();
    }

    exportCSV() {
        let csv = "Customer,Currency,Amount,Fee,Status,Date,Type\n";
        for (const rec of this.state.records) {
            csv += [
                rec.customer, rec.currency, rec.amount, rec.fee, rec.status, rec.date, rec.type
            ].join(",") + "\n";
        }
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "ledger_report.csv";
        a.click();
        URL.revokeObjectURL(url);
    }
}

LedgerDashboard.template = "atlaxchange_ledger.LedgerDashboard";