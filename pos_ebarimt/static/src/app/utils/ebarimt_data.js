/** @odoo-module */
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

/**
 * Identifier used by pos.order.get_ebarimt_receipt_data(): server id first,
 * then pos_reference, then name (same order as the 16.0 receipt code).
 */
export function getEbarimtOrderIdentifier(order) {
    if (typeof order.id === "number" && order.id > 0) {
        return order.id;
    }
    return order.pos_reference || order.name || null;
}

/**
 * Fetch the eBarimt receipt data of an order from the server and keep it on
 * order.uiState.ebarimtData. Returns the data or null.
 */
export async function fetchEbarimtData(pos, order) {
    const identifier = order && getEbarimtOrderIdentifier(order);
    if (!identifier) {
        return null;
    }
    const result = await pos.data.call("pos.order", "get_ebarimt_receipt_data", [
        identifier,
        pos.config.id,
    ]);
    if (result && result.bill_id) {
        order.uiState.ebarimtData = result;
        return result;
    }
    return null;
}

// After the order is synced (eBarimt is sent server-side in pos.order.write
// when the order becomes 'paid'), load the bill id / lottery / QR so the
// receipt has it before it is shown or auto-printed. In 16.0 the receipt
// component polled for it; the receipt patch still retries if it is missing.
patch(OrderPaymentValidation.prototype, {
    async afterOrderValidation() {
        if (this.order && !this.order.uiState?.ebarimtData) {
            try {
                await fetchEbarimtData(this.pos, this.order);
            } catch (error) {
                console.warn("eBarimt: could not load receipt data", error);
            }
        }
        return await super.afterOrderValidation(...arguments);
    },
});

// Every print (auto-print, the receipt screen's Print button, reprint from
// the orders list) renders the receipt off-screen without waiting for async
// loads. The current bill is therefore fetched here first, so a print shows
// a bill that arrived later (retry after the gateway was down) or that
// replaced the first one (partial return). If the fetch fails, the data
// already loaded is printed.
patch(PosStore.prototype, {
    async printReceipt(options = {}) {
        const order = options.order || this.getOrder();
        if (order?.finalized) {
            try {
                await fetchEbarimtData(this, order);
            } catch (error) {
                console.warn("eBarimt: could not load receipt data", error);
            }
        }
        return await super.printReceipt(...arguments);
    },
});
