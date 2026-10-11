/** @odoo-module */
// Burger menu item "eBarimt илгээх": asks PosAPI (sendData) to push the
// receipts it holds to the eBarimt system now.
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(Navbar.prototype, {
    async ebarimtSendData() {
        if (this.ebarimtSending) {
            return;
        }
        this.ebarimtSending = true;
        try {
            const result = await this.pos.data.call("account.ebarimt.posapi", "pos_send_data", [
                this.pos.company.id,
            ]);
            this.notification.add(result.message, {
                title: _t("eBarimt"),
                type: result.ok ? "success" : "danger",
            });
        } catch (error) {
            console.error("eBarimt: sendData error", error);
            this.notification.add(_t("Could not reach the server. Check the connection and try again."), {
                title: _t("eBarimt"),
                type: "danger",
            });
        } finally {
            this.ebarimtSending = false;
        }
    },
});
