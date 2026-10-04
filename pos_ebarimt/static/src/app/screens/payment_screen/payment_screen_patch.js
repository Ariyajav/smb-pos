/** @odoo-module */
// 16.0 source: static/src/js/screens/payment_screen_extend.js
// (Registries.Component.extend(PaymentScreen, ...)). 19.0: patch() on the
// PaymentScreen prototype; popups go through the dialog service.
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ask, makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { EbarimtConfirmPopup } from "@pos_ebarimt/app/popups/ebarimt_confirm_popup/ebarimt_confirm_popup";
import { EBARIMT_DEFAULT_CONFIG } from "@pos_ebarimt/app/models/pos_order_patch";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        const currentOrder = this.currentOrder;
        if (!currentOrder) {
            return await super.validateOrder(...arguments);
        }

        try {
            // ========== POSAPI WARNING CHECK ==========
            const warningResult = await this.checkPosAPIWarnings();
            if (warningResult && warningResult.warnings && warningResult.warnings.length > 0) {
                const warningMessages = warningResult.warnings.map((w) => w.message).join("\n\n");
                const hasCritical = warningResult.warnings.some((w) => w.type === "critical");
                const warningConfirmed = await ask(this.dialog, {
                    title: hasCritical ? _t("⛔ АНХААРУУЛГА!") : _t("⚠️ Анхааруулга"),
                    body:
                        warningMessages +
                        "\n\n" +
                        (hasCritical
                            ? _t("Үргэлжлүүлэх үү? (Сугалаагүй баримт хэвлэгдэнэ)")
                            : _t("Үргэлжлүүлэх үү?")),
                    confirmLabel: _t("Тийм"),
                    cancelLabel: _t("Үгүй"),
                });
                if (!warningConfirmed) {
                    return;
                }
            }
            // ========== END POSAPI WARNING CHECK ==========

            const payload = await makeAwaitable(this.dialog, EbarimtConfirmPopup, {
                title: _t("📄 eBarimt тохиргоо"),
                body: _t("Баримтын төрөл сонгоно уу"),
                partner: currentOrder.getPartner() || null,
            });
            if (!payload) {
                // popup cancelled / closed
                return;
            }
            this.storeEbarimtInfo(currentOrder, payload);
        } catch (error) {
            // Алдаа гарсан ч order validation үргэлжлүүлэх (16.0 behaviour)
            console.error("eBarimt: error in popup handling", error);
        }
        return await super.validateOrder(...arguments);
    },

    /**
     * Order дээр eBarimt мэдээлэл хадгалах
     */
    storeEbarimtInfo(order, ebarimtData) {
        if (!ebarimtData || typeof ebarimtData !== "object") {
            ebarimtData = { ...EBARIMT_DEFAULT_CONFIG };
        }
        order.setEbarimtConfig({
            receiptType: ebarimtData.receiptType || "individual",
            billType: ebarimtData.billType || "B2C_RECEIPT",
            customerTin: ebarimtData.customerTin || "",
            manualCustomerTin: ebarimtData.manualCustomerTin || "",
            hasCustomer: ebarimtData.hasCustomer || false,
            customerName: ebarimtData.customerName || "",
            configuredAt: new Date().toISOString(),
        });
    },

    getOrderEbarimtInfo(order) {
        return order ? order.getEbarimtConfig() : null;
    },

    /**
     * PosAPI анхааруулга шалгах
     * - Сугалааны дугаар дуусаж байгаа эсэх
     * - Мэдээ илгээх хугацаа хэтэрсэн эсэх
     */
    async checkPosAPIWarnings() {
        try {
            return await this.pos.data.call("account.ebarimt.posapi", "check_posapi_warnings", [
                this.pos.company.id,
            ]);
        } catch (error) {
            console.error("eBarimt: error checking PosAPI warnings", error);
            // Алдаа гарсан ч үргэлжлүүлэх боломжтой
            return { success: false, warnings: [], lottery_ok: true, sync_ok: true };
        }
    },
});
