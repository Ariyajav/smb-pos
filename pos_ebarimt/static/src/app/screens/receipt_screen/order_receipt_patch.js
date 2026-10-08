/** @odoo-module */
// 16.0 source: static/src/js/pos_receipt.js (OrderReceipt extended through
// Registries, polling pos.order.get_ebarimt_receipt_data with retries).
// 19.0: patch() on OrderReceipt. The data is normally already on
// order.uiState.ebarimtData (loaded right after validation, see
// utils/ebarimt_data.js) because the printer service renders the receipt
// off-screen and does not wait for async loads. When it is missing (e.g.
// reprint from the ticket screen) the 16.0 retry loop is used.
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { fetchEbarimtData } from "@pos_ebarimt/app/utils/ebarimt_data";

// @page rules cannot be scoped to a class, so the zero page margin that a
// 58 mm roll needs (Chrome's default margins would eat a quarter of the
// width) is added only on POS whose receipt paper is 58 mm.
const NARROW_PAGE_STYLE_ID = "pos-ebarimt-page-58mm";

function ensureNarrowPrintPage() {
    if (document.getElementById(NARROW_PAGE_STYLE_ID)) {
        return;
    }
    const style = document.createElement("style");
    style.id = NARROW_PAGE_STYLE_ID;
    style.textContent = "@media print { @page { margin: 0; padding: 0; } }";
    document.head.appendChild(style);
}

const EBARIMT_MAX_RETRIES = 8;
const EBARIMT_RETRY_DELAY = 12000;

patch(OrderReceipt.prototype, {
    setup() {
        super.setup(...arguments);
        try {
            this.ebarimtPos = useService("pos");
        } catch {
            // OrderReceipt rendered outside the POS app (no pos service)
            this.ebarimtPos = null;
        }
        this.ebarimtState = useState({
            loading: false,
            error: null,
            data: this.props.order?.uiState?.ebarimtData || null,
            retryCount: 0,
            initialized: false,
        });
        this._ebarimtAlive = true;
        if (this.ebarimtPaperWidth === "58") {
            ensureNarrowPrintPage();
        }
        onMounted(() => this.initEbarimt());
        onWillUnmount(() => this.cleanupEbarimt());
    },

    async initEbarimt() {
        if (this.ebarimtState.initialized) {
            return;
        }
        this.ebarimtState.initialized = true;
        const order = this.props.order;
        if (!order) {
            this.ebarimtState.error = "Захиалга олдсонгүй";
            return;
        }
        // Draft orders (bill printing before payment) have no eBarimt yet.
        if (this.ebarimtState.data || !order.finalized || !this.ebarimtPos) {
            return;
        }
        await this.loadEbarimtData();
    },

    async loadEbarimtData() {
        const order = this.props.order;
        if (!order || !this.ebarimtPos || this.ebarimtState.loading || !this._ebarimtAlive) {
            return;
        }
        this.ebarimtState.loading = true;
        this.ebarimtState.error = null;
        try {
            const data = await fetchEbarimtData(this.ebarimtPos, order);
            if (data) {
                this.ebarimtState.data = data;
                this.ebarimtState.retryCount = 0;
            } else if (this.ebarimtState.retryCount < EBARIMT_MAX_RETRIES) {
                this.ebarimtState.retryCount++;
                this.ebarimtState.error = `eBarimt хүлээж байна... (${this.ebarimtState.retryCount}/${EBARIMT_MAX_RETRIES})`;
                if (this._ebarimtAlive) {
                    this.ebarimtRetryTimer = setTimeout(
                        () => this.loadEbarimtData(),
                        EBARIMT_RETRY_DELAY
                    );
                }
            } else {
                this.ebarimtState.error = "eBarimt мэдээлэл олдсонгүй";
            }
        } catch (error) {
            this.ebarimtState.error = error.message || "eBarimt алдаа гарлаа";
        } finally {
            this.ebarimtState.loading = false;
        }
    },

    cleanupEbarimt() {
        this._ebarimtAlive = false;
        if (this.ebarimtRetryTimer) {
            clearTimeout(this.ebarimtRetryTimer);
            this.ebarimtRetryTimer = null;
        }
    },

    async refreshEbarimt() {
        this.cleanupEbarimt();
        this._ebarimtAlive = true;
        this.ebarimtState.retryCount = 0;
        this.ebarimtState.error = null;
        this.ebarimtState.data = null;
        await this.loadEbarimtData();
    },

    get hasEbarimt() {
        return Boolean(!this.ebarimtState.loading && this.ebarimtData?.bill_id);
    },

    get ebarimtLoading() {
        return this.ebarimtState.loading;
    },

    get ebarimtError() {
        return this.ebarimtState.error;
    },

    get ebarimtData() {
        return this.ebarimtState.data || this.props.order?.uiState?.ebarimtData || null;
    },

    get ebarimtQrUrl() {
        const data = this.ebarimtData;
        if (data && data.qr_code_base64) {
            return `data:image/png;base64,${data.qr_code_base64}`;
        }
        return null;
    },

    // Whole tugrik with thousands separators: 28000 -> "28,000"
    ebarimtFmt(amount) {
        return Math.round(amount || 0).toLocaleString("en-US");
    },

    get isReplacementBill() {
        return Boolean(this.hasEbarimt && this.ebarimtData.replaced && this.ebarimtData.items);
    },

    // Totals printed in the eBarimt section: the bill's own amounts when the
    // bill replaced an earlier one, else the order's.
    get ebarimtTotal() {
        return this.isReplacementBill ? this.ebarimtData.amount : this.props.order.priceIncl;
    },

    get ebarimtTotalExcl() {
        if (!this.isReplacementBill) {
            return this.props.order.priceExcl;
        }
        const data = this.ebarimtData;
        return data.amount - (data.vat || 0) - (data.city_tax || 0);
    },

    get ebarimtPaperWidth() {
        return this.props.order?.config?.receipt_paper_width || "80";
    },

    get ebarimtPaperClass() {
        return `receipt-${this.ebarimtPaperWidth}mm`;
    },

    get isConsumerReceipt() {
        return Boolean(this.ebarimtData && this.ebarimtData.bill_type === "B2C_RECEIPT");
    },

    get formattedLottery() {
        const lottery = this.ebarimtData?.lottery;
        if (!lottery) {
            return "";
        }
        if (lottery.includes(" ")) {
            return lottery;
        }
        if (lottery.length >= 8) {
            return `${lottery.substring(0, 2)} ${lottery.substring(2)}`;
        }
        return lottery;
    },

    get formattedEbarimtDate() {
        const date = this.ebarimtData?.date;
        if (!date) {
            return "";
        }
        try {
            return new Date(date).toLocaleString("mn-MN", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
            });
        } catch {
            return date;
        }
    },

    get orderEbarimtInfo() {
        const order = this.props.order;
        if (!order) {
            return null;
        }
        return order.getEbarimtConfig();
    },

    get receiptTypeDisplay() {
        const info = this.orderEbarimtInfo;
        if (!info || !info.configured) {
            return "Тодорхойгүй";
        }
        return info.receiptType === "organization" ? "Байгууллага" : "Хувь хүн";
    },

    get showEbarimtConfigInfo() {
        return Boolean(this.props.order?.isEbarimtConfigured());
    },
});
