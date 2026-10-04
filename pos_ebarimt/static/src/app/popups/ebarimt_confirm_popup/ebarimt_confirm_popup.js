/** @odoo-module */
// 16.0 source: static/src/js/popups/ebarimt_confirm_popup.js
// (AbstractAwaitablePopup + Registries). 19.0: plain OWL component rendered
// in a Dialog through the dialog service; the result is returned with
// props.getPayload() (see makeAwaitable in point_of_sale/app/utils).
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class EbarimtConfirmPopup extends Component {
    static template = "pos_ebarimt.EbarimtConfirmPopup";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        body: { type: String, optional: true },
        partner: { optional: true },
        getPayload: Function,
        close: Function,
    };
    static defaultProps = {
        title: "📄 eBarimt тохиргоо",
        body: "",
    };

    setup() {
        this.dialog = useService("dialog");
        const partner = this.props.partner || null;
        this.state = useState({
            receiptType: "individual",
            manualCustomerTin: "",
            hasCustomer: !!partner,
            customerName: (partner && partner.name) || "",
            customerTin: (partner && (partner.vat_tin || partner.vat)) || "",
        });
    }

    changeReceiptType(newType) {
        this.state.receiptType = newType;
        if (newType === "individual") {
            this.state.manualCustomerTin = "";
        }
    }

    onCancel() {
        this.props.close();
    }

    onConfirm() {
        const result = this.getConfirmResult();
        if (!this.validateInput(result)) {
            return;
        }
        this.props.getPayload(result);
        this.props.close();
    }

    getConfirmResult() {
        const isOrganization = this.state.receiptType === "organization";
        let finalCustomerTin = "";
        if (isOrganization) {
            if (this.state.manualCustomerTin && this.state.manualCustomerTin.trim()) {
                finalCustomerTin = this.state.manualCustomerTin.trim();
            } else if (this.state.hasCustomer && this.state.customerTin) {
                finalCustomerTin = this.state.customerTin;
            }
        }
        return {
            receiptType: this.state.receiptType,
            billType: isOrganization ? "B2B_RECEIPT" : "B2C_RECEIPT",
            customerTin: finalCustomerTin,
            hasCustomer: this.state.hasCustomer,
            customerName: this.state.customerName,
            manualCustomerTin: this.state.manualCustomerTin.trim(),
        };
    }

    validateInput(result) {
        if (result.receiptType === "organization") {
            if (!result.customerTin) {
                this.dialog.add(AlertDialog, {
                    title: _t("⚠️ Алдаа"),
                    body: _t(
                        "Байгууллагын баримтад ТТД заавал шаардлагатай.\n\nХарилцагч сонгох эсвэл ТТД оруулна уу."
                    ),
                });
                return false;
            }
            if (result.customerTin.length < 7) {
                this.dialog.add(AlertDialog, {
                    title: _t("⚠️ Алдаа"),
                    body: _t("ТТД дор хаяж 7 тэмдэгт байх ёстой.\n\nТТД-г зөв оруулна уу."),
                });
                return false;
            }
        }
        return true;
    }

    onManualTinChange() {
        const cleanValue = this.state.manualCustomerTin.replace(/[^a-zA-Z0-9]/g, "");
        if (cleanValue !== this.state.manualCustomerTin) {
            this.state.manualCustomerTin = cleanValue;
        }
    }
}
