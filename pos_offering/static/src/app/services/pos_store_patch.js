/** @odoo-module */
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { OfferingPopup } from "@pos_offering/app/popups/offering_popup/offering_popup";
import { getOfferingKind } from "@pos_offering/app/models/pos_order_patch";

patch(PosStore.prototype, {
    async pay() {
        const order = this.getOrder();
        // Refunds keep the amounts and names of the original order.
        if (
            order?.hasOfferingLines() &&
            !order.isRefund &&
            !order.lines.some((line) => line.qty < 0)
        ) {
            if (order.lines.some((line) => !getOfferingKind(line))) {
                this.dialog.add(AlertDialog, {
                    title: _t("Сүсэг"),
                    body: _t(
                        "Ном, сүсгийг бараатай нэг захиалгад хамт оруулах боломжгүй. Тусад нь хоёр захиалга болгоно уу."
                    ),
                });
                return;
            }
            if (!(await this.editOffering(order))) {
                return;
            }
        }
        return await super.pay(...arguments);
    },

    /**
     * Ask who the offering is from, the family size, the reading day and the
     * amount, and put the amount on the order's offering amount line.
     * Returns false when the cashier cancels.
     */
    async editOffering(order) {
        const amountProduct = this.models["product.template"].find(
            (tmpl) => tmpl.offering_kind === "amount"
        );
        if (!amountProduct) {
            this.dialog.add(AlertDialog, {
                title: _t("Сүсэг"),
                body: _t(
                    "Сүсгийн дүнгийн бараа олдсонгүй. Бараанд \"Offering amount\" тохиргоотой, POS-д харагдах бараа үүсгэнэ үү."
                ),
            });
            return false;
        }
        const days = this.models["pos.offering.day"]
            .getAll()
            .sort((a, b) => a.sequence - b.sequence || a.id - b.id)
            .map((day) => day.name);
        const amountLine = order.getOfferingAmountLine();
        const payload = await makeAwaitable(this.dialog, OfferingPopup, {
            offeringFrom: order.offering_from || "",
            familySize: order.offering_family_size || 1,
            day: order.offering_day || "",
            amount: amountLine ? amountLine.price_unit : 0,
            days,
        });
        if (!payload) {
            return false;
        }
        order.offering_from = payload.offeringFrom;
        order.offering_family_size = payload.familySize;
        order.offering_day = payload.day;
        if (amountLine) {
            amountLine.setQuantity(1, true);
            amountLine.setUnitPrice(payload.amount);
            amountLine.price_type = "manual";
        } else {
            await this.addLineToOrder(
                { product_tmpl_id: amountProduct, price_unit: payload.amount, qty: 1 },
                order,
                {},
                false
            );
        }
        return true;
    },
});
