/** Add "Fetch Fees" and "Create Fee" buttons to Transaction Fee (v2) list view toolbar **/
odoo.define('atlaxchange_app.transaction_fee_v2_buttons', function (require) {
    "use strict";

    const ListController = require('web.ListController');
    const viewRegistry = require('web.view_registry');
    const ListView = require('web.ListView');

    const TransactionFeeV2ListController = ListController.extend({
        renderButtons() {
            this._super.apply(this, arguments);
            if (!this.$buttons) {
                return;
            }

            const fetchBtn = $('<button type="button" class="btn btn-primary o_fee_v2_fetch_btn">Fetch Fees</button>');
            fetchBtn.on('click', () => {
                fetchBtn.prop('disabled', true);
                this._rpc({
                    model: 'transaction.fee.v2',
                    method: 'fetch_transaction_fees_v2',
                    args: [],
                    kwargs: {},
                }).then(() => {
                    this.trigger_up('do_notify', {
                        title: "Fees fetched",
                        message: "Transaction fees have been synced from the API.",
                    });
                    setTimeout(() => this.do_action({ type: 'ir.actions.client', tag: 'reload' }), 1200);
                }).catch((err) => {
                    const message = (err && err.data && err.data.message) ? err.data.message : String(err || 'Unknown error');
                    this.trigger_up('do_notify', {
                        title: "Fetch failed",
                        message: message,
                        sticky: true,
                    });
                }).finally(() => {
                    fetchBtn.prop('disabled', false);
                });
            });

            const createBtn = $('<button type="button" class="btn btn-secondary o_fee_v2_create_btn">Create Fee</button>');
            createBtn.css('margin-left', '8px');
            createBtn.on('click', () => {
                this.do_action({
                    name: 'Create Transaction Fee (v2)',
                    type: 'ir.actions.act_window',
                    res_model: 'create.transaction.fee.v2.wizard',
                    view_mode: 'form',
                    views: [[false, 'form']],
                    target: 'new',
                    context: {
                        active_model: 'transaction.fee.v2',
                    },
                });
            });

            this.$buttons.prepend(createBtn);
            this.$buttons.prepend(fetchBtn);
        },
    });

    const TransactionFeeV2ListView = ListView.extend({
        config: _.extend({}, ListView.prototype.config, {
            Controller: TransactionFeeV2ListController,
        }),
    });

    viewRegistry.add('transaction_fee_v2_list_with_buttons', TransactionFeeV2ListView);
});