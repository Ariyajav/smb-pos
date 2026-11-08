/** @odoo-module */
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

export function getOfferingKind(line) {
    return line.product_id?.product_tmpl_id?.offering_kind || false;
}

patch(PosOrder.prototype, {
    hasOfferingLines() {
        return this.lines.some((line) => getOfferingKind(line));
    },

    // Offerings are not sales: an order with only offering lines gets no
    // eBarimt bill (the server skips offering lines too).
    isEbarimtRequired() {
        if (this.hasOfferingLines() && this.lines.every((line) => getOfferingKind(line))) {
            return false;
        }
        return super.isEbarimtRequired(...arguments);
    },

    getOfferingAmountLine() {
        return this.lines.find((line) => getOfferingKind(line) === "amount");
    },
});
