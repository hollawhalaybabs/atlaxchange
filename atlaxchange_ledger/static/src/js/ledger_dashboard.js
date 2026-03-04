/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class LedgerDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.state = useState({
            records: [],
            walletOptions: [],
            customerOptions: [],
            customerNameOptions: [], // fallback options (by customer_name)
            metrics: {
                transactions: { count: { debit: 0, credit: 0, total: 0 }, amount: { debit: 0, credit: 0, total: 0 } },
                customers: 0,
                fees: { count: { debit: 0, credit: 0, total: 0 }, amount: { debit: 0, credit: 0, total: 0 } },
            },
            filters: {
                customer_id: "",
                customer_name: "", // fallback when partner_id is missing
                reference: "",
                status: "",
                transfer_direction: "",
                wallet: "",
                date_from: "",
                date_to: "",
            },
            paging: { page: 1, page_size: 100, pages: 1, total: 0 },
            loading: true,
        });
        onWillStart(async () => { await this.fetchData(); });
    }

    formatNumber(n) {
        try { return new Intl.NumberFormat().format(n || 0); }
        catch { return String(n || 0); }
    }

    // Wallet-aware formatter: symbol only when a wallet is selected
    formatCurrency(n) {
        const selected = this.state.filters.wallet;
        if (!selected) return this.formatNumber(n);
        try {
            return new Intl.NumberFormat(undefined, { style: "currency", currency: selected }).format(n || 0);
        } catch {
            return `${this.formatNumber(n)} ${selected}`;
        }
    }

    // Use explicit currency code (for destination amounts in the table)
    formatCurrencyByCode(n, code) {
        if (!code) return this.formatNumber(n);
        try {
            return new Intl.NumberFormat(undefined, { style: "currency", currency: code }).format(n || 0);
        } catch {
            return `${this.formatNumber(n)} ${code}`;
        }
    }

    async fetchData() {
        this.state.loading = true;
        try {
            const result = await this.rpc("/atlaxchange/ledger_dashboard/data", {
                filters: this.state.filters,
                page: this.state.paging.page,
                page_size: this.state.paging.page_size,
            });
            this.state.records = result?.records || [];
            this.state.metrics = result?.metrics || this.state.metrics;
            this.state.walletOptions = result?.wallet_options || [];
            this.state.customerOptions = result?.customer_options || [];
            this.state.customerNameOptions = result?.customer_name_options || []; // NEW
            if (result?.paging) this.state.paging = result.paging;
        } catch (err) {
            console.error("LedgerDashboard.fetchData error:", err);
            this.notification?.add("Failed to load ledger dashboard data", { type: "danger" });
            this.state.records = [];
        } finally {
            this.state.loading = false;
        }
    }

    async onFilterChange(ev) {
        const { name, value } = ev.target;
        this.state.filters[name] = value;
        // Ensure only one of customer_id / customer_name is active
        if (name === 'customer_id' && value) {
            this.state.filters.customer_name = '';
        } else if (name === 'customer_name' && value) {
            this.state.filters.customer_id = '';
        }
        this.state.paging.page = 1;
        await this.fetchData();
    }

    async gotoPage(page) {
        const p = Math.max(1, Math.min(Number(page) || 1, this.state.paging.pages || 1));
        if (p === this.state.paging.page) return;
        this.state.paging.page = p;
        await this.fetchData();
    }
    async nextPage() { await this.gotoPage((this.state.paging.page || 1) + 1); }
    async prevPage() { await this.gotoPage((this.state.paging.page || 1) - 1); }

    exportCSV() {
        const headers = ["Date","Reference","Customer","Bank","Beneficiary","Currency","Dest Currency","Amount","Fee","Rate","Dest Amount","Status","transfer_direction"];
        let csv = headers.join(",") + "\n";
        for (const rec of this.state.records) {
            csv += [
                rec.date, rec.reference, rec.customer, rec.bank, rec.beneficiary,
                rec.currency, rec.dest_currency, rec.amount, rec.fee, rec.conversion_rate,
                rec.total_amount, rec.status, rec.transfer_direction
            ].join(",") + "\n";
        }
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = "ledger_report.csv"; a.click();
        URL.revokeObjectURL(url);
    }

    async refreshIngestion() {
        // Mirror the list view "Refresh 1000" behavior, then reload dashboard data
        this.state.loading = true;
        try {
            const stats = await this.rpc("/web/dataset/call_kw/atlaxchange.ledger/fetch_ledger_history_enqueue", {
                model: "atlaxchange.ledger",
                method: "fetch_ledger_history_enqueue",
                args: [],
                kwargs: {
                    sync: true,
                    popup: false,
                    target_count: 1000,
                    max_seconds: 12,
                    direction: 'auto',
                    page_size: 1000,
                    page_size_param: 'limit',
                    after_param: 'cursor',
                    before_param: 'cursor',
                },
            });
            const processed = stats?.processed || 0;
            const created = stats?.created || 0;
            const updated = stats?.updated || 0;
            const pages = stats?.pages || 0;
            const partial = stats?.partial ? ` (partial: ${stats?.reason || 'time budget'})` : '';
            this.notification?.add(`Processed: ${processed}, Created: ${created}, Updated: ${updated}, Pages: ${pages}${partial}`, {
                title: "Ledger refreshed (1000)",
                type: "success",
            });
            await this.fetchData();
        } catch (err) {
            const message = (err && err.message) || (err?.data?.message) || String(err || 'Unknown error');
            this.notification?.add(message, { title: "Fetch failed", type: "danger", sticky: true });
        } finally {
            this.state.loading = false;
        }
    }
}

LedgerDashboard.template = "atlaxchange_ledger.LedgerDashboard";