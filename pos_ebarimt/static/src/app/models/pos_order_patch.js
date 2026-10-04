/** @odoo-module */
// 16.0 source: static/src/js/pos_models.js (models.Order prototype overrides).
// 19.0: pos.order ebarimt_* fields are real python fields loaded into the POS
// model, so they are serialized to the server by name (no export_as_JSON /
// init_from_JSON / _order_fields needed). JS-only flags live in uiState, which
// is persisted to IndexedDB like the 16.0 init_from_JSON round-trip.
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

export const EBARIMT_DEFAULT_CONFIG = Object.freeze({
    receiptType: "individual",
    billType: "B2C_RECEIPT",
    customerTin: "",
    manualCustomerTin: "",
});

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        // Defaults previously applied server-side by _order_fields()
        // (setup() also runs on updates: keep the current value when the
        // incoming vals do not carry the field).
        this.ebarimt_receipt_type =
            vals.ebarimt_receipt_type || this.ebarimt_receipt_type || "individual";
        this.ebarimt_bill_type = vals.ebarimt_bill_type || this.ebarimt_bill_type || "B2C_RECEIPT";
        this.ebarimt_customer_tin = vals.ebarimt_customer_tin || this.ebarimt_customer_tin || "";
        this.ebarimt_manual_customer_tin =
            vals.ebarimt_manual_customer_tin || this.ebarimt_manual_customer_tin || "";
        this.ebarimt_config_json = vals.ebarimt_config_json || this.ebarimt_config_json || "";
    },

    initState() {
        super.initState(...arguments);
        this.uiState.ebarimtConfigured = false;
        this.uiState.ebarimtConfigStored = false;
        // Result of pos.order.get_ebarimt_receipt_data(), fetched after sync
        this.uiState.ebarimtData = null;
    },

    /**
     * eBarimt тохиргоо хадгалах
     */
    setEbarimtConfig(config) {
        config = config || { ...EBARIMT_DEFAULT_CONFIG };
        this.ebarimt_receipt_type = config.receiptType || "individual";
        this.ebarimt_bill_type = config.billType || "B2C_RECEIPT";
        // Manual TIN-г customer TIN руу шууд хийх
        if (config.receiptType === "organization") {
            this.ebarimt_customer_tin = config.manualCustomerTin || config.customerTin || "";
        } else {
            this.ebarimt_customer_tin = "";
        }
        this.ebarimt_manual_customer_tin = config.manualCustomerTin || "";
        this.ebarimt_config_json = JSON.stringify(config);
        this.uiState.ebarimtConfigured = true;
        this.uiState.ebarimtConfigStored = false;
    },

    getEbarimtConfigObject() {
        if (!this.ebarimt_config_json) {
            return null;
        }
        try {
            return JSON.parse(this.ebarimt_config_json);
        } catch {
            return null;
        }
    },

    isEbarimtConfigured() {
        return Boolean(this.uiState?.ebarimtConfigured || this.ebarimt_config_json);
    },

    /**
     * eBarimt тохиргоо авах
     */
    getEbarimtConfig() {
        return {
            configured: this.isEbarimtConfigured(),
            receiptType: this.ebarimt_receipt_type,
            billType: this.ebarimt_bill_type,
            customerTin: this.ebarimt_customer_tin,
            manualCustomerTin: this.ebarimt_manual_customer_tin,
            fullConfig: this.getEbarimtConfigObject(),
            stored: Boolean(this.uiState?.ebarimtConfigStored),
        };
    },

    resetEbarimtConfig() {
        this.ebarimt_receipt_type = "individual";
        this.ebarimt_bill_type = "B2C_RECEIPT";
        this.ebarimt_customer_tin = "";
        this.ebarimt_manual_customer_tin = "";
        this.ebarimt_config_json = "";
        this.uiState.ebarimtConfigured = false;
        this.uiState.ebarimtConfigStored = false;
    },
});
