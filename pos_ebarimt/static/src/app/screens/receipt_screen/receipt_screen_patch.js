/** @odoo-module */
// 16.0 source: static/src/js/ebarimt_screen_config.js. In 16.0 it registered
// an extra AbstractReceiptScreen subclass that was never routed to; its only
// effect was a delayed (3 s) get_ebarimt_receipt_data check. 19.0: the check
// is done on the real ReceiptScreen and fills order.uiState.ebarimtData if the
// post-validation load did not get it yet.
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount } from "@odoo/owl";
import { fetchEbarimtData } from "@pos_ebarimt/app/utils/ebarimt_data";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            this.ebarimtCheckTimer = setTimeout(() => this.checkEbarimtStatus(), 3000);
        });
        onWillUnmount(() => clearTimeout(this.ebarimtCheckTimer));
    },

    async checkEbarimtStatus() {
        const order = this.currentOrder;
        if (!order || order.uiState?.ebarimtData) {
            return;
        }
        try {
            await fetchEbarimtData(this.pos, order);
        } catch (error) {
            console.error("eBarimt: status check error", error);
        }
    },
});
