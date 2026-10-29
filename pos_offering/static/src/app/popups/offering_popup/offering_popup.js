/** @odoo-module */
// Asked on Payment for orders with offering readings: who the offering is
// from, the number of family members, the reading day and one offering amount
// for the whole order. The result is returned with props.getPayload()
// (see makeAwaitable in point_of_sale/app/utils).
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class OfferingPopup extends Component {
    static template = "pos_offering.OfferingPopup";
    static components = { Dialog };
    static props = {
        offeringFrom: { type: String, optional: true },
        familySize: { type: Number, optional: true },
        day: { type: String, optional: true },
        amount: { type: Number, optional: true },
        days: Array,
        getPayload: Function,
        close: Function,
    };

    setup() {
        this.state = useState({
            offeringFrom: this.props.offeringFrom || "",
            familySize: String(this.props.familySize || 1),
            day: this.props.day || this.props.days[0] || "",
            amount: this.props.amount ? String(this.props.amount) : "",
            error: "",
        });
    }

    onConfirm() {
        const offeringFrom = this.state.offeringFrom.trim();
        const familySize = parseInt(this.state.familySize, 10);
        const amount = parseFloat(String(this.state.amount).replace(/[\s,]/g, ""));
        if (!offeringFrom) {
            this.state.error = _t("Хэнээс гэдгийг оруулна уу.");
            return;
        }
        if (!(familySize >= 1)) {
            this.state.error = _t("Ам бүлийн тоо 1-ээс их байна.");
            return;
        }
        if (!(amount > 0)) {
            this.state.error = _t("Сүсэглэх дүнг оруулна уу.");
            return;
        }
        this.props.getPayload({ offeringFrom, familySize, day: this.state.day, amount });
        this.props.close();
    }
}
