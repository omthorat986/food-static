/* Checkout + order confirmation pages.
   Everything here is a local demonstration: no payment is processed
   and no card / PayPal data is ever collected. */
(function () {
    "use strict";

    function money(value, formatINR) {
        return formatINR(Number(value) || 0);
    }

    function makeOrderId() {
        var stamp = Date.now().toString(36).toUpperCase();
        var rand = Math.floor(Math.random() * 46656).toString(36).toUpperCase();
        return "FOD-" + stamp + "-" + ("000" + rand).slice(-3);
    }

    function digitsOnly(value) {
        return String(value || "").replace(/\D+/g, "");
    }

    /* ---------------------- checkout view ---------------------- */

    function initCheckout() {
        var form = document.getElementById("checkout-form");
        var F = window.Foodies;
        if (!form || !F) return;

        var itemsEl = document.getElementById("summary-items");
        var totalEl = document.getElementById("summary-total");
        var messageEl = document.getElementById("checkout-message");
        var emptyEl = document.getElementById("checkout-empty");

        function renderSummary() {
            var cart = F.getCart();
            var count = F.cartCount();
            if (itemsEl) itemsEl.textContent = String(count);
            if (totalEl) totalEl.textContent = money(F.cartTotal(), F.formatINR);

            if (cart.length === 0) {
                if (emptyEl) emptyEl.removeAttribute("hidden");
                form.setAttribute("hidden", "");
            } else {
                if (emptyEl) emptyEl.setAttribute("hidden", "");
                form.removeAttribute("hidden");
            }
        }

        function setMessage(text, isError) {
            if (!messageEl) return;
            messageEl.textContent = text || "";
            messageEl.className = "message" + (text ? (isError ? " error" : " success") : "");
        }

        function fieldValue(name) {
            var el = form.elements[name];
            return el ? String(el.value).trim() : "";
        }

        function markInvalid(name, invalid) {
            var el = form.elements[name];
            if (!el) return;
            if (invalid) el.classList.add("input-error");
            else el.classList.remove("input-error");
        }

        form.addEventListener("submit", function (event) {
            event.preventDefault();

            var cart = F.getCart();
            if (cart.length === 0) {
                setMessage("Your cart is empty, so there is nothing to order.", true);
                return;
            }

            var name = fieldValue("name");
            var address = fieldValue("address");
            var phone = fieldValue("phone");

            var nameBad = name.length < 2;
            var addressBad = address.length < 6;
            var phoneBad = digitsOnly(phone).length < 10;

            markInvalid("name", nameBad);
            markInvalid("address", addressBad);
            markInvalid("phone", phoneBad);

            if (nameBad || addressBad || phoneBad) {
                var problems = [];
                if (nameBad) problems.push("a name of at least 2 characters");
                if (addressBad) problems.push("an address of at least 6 characters");
                if (phoneBad) problems.push("a phone number with at least 10 digits");
                setMessage("Please provide " + problems.join(", ") + ".", true);
                return;
            }

            var order = {
                id: makeOrderId(),
                date: new Date().toISOString(),
                name: name,
                address: address,
                phone: phone,
                total: F.cartTotal(),
                items: cart.map(function (item) {
                    return { name: item.name, price: item.price, qty: item.qty };
                }),
                status: "Completed (demo)",
                payment: "None - demo order",
                demo: true
            };

            F.addOrder(order);
            F.clearCart();
            window.location.href = "success.html";
        });

        renderSummary();
        document.addEventListener("foodies:cart-change", renderSummary);
    }

    /* ---------------------- success view ---------------------- */

    function initSuccess() {
        var F = window.Foodies;
        var container = document.getElementById("order-details");
        if (!F || !container) return;

        var order = F.getLastOrder();
        var fallback = document.getElementById("order-fallback");
        if (!order) {
            container.setAttribute("hidden", "");
            if (fallback) fallback.removeAttribute("hidden");
            return;
        }

        function row(label, value) {
            var div = document.createElement("div");
            div.className = "detail-item";
            var strong = document.createElement("strong");
            strong.textContent = label + ": ";
            div.appendChild(strong);
            div.appendChild(document.createTextNode(value));
            return div;
        }

        container.innerHTML = "";
        container.appendChild(row("Order ID", order.id));
        container.appendChild(row("Name", order.name));
        container.appendChild(row("Address", order.address));
        container.appendChild(row("Phone", order.phone));
        container.appendChild(row("Items", String(order.items.reduce(function (n, i) {
            return n + i.qty;
        }, 0))));
        container.appendChild(row("Amount", money(order.total, F.formatINR) + " (not charged)"));
        container.appendChild(row("Order Date", new Date(order.date).toLocaleString()));
        container.appendChild(row("Status", order.status));

        var items = document.createElement("div");
        items.className = "detail-item";
        var itemsStrong = document.createElement("strong");
        itemsStrong.textContent = "Order Items: ";
        items.appendChild(itemsStrong);
        var list = document.createElement("ul");
        list.className = "order-items";
        order.items.forEach(function (item) {
            var li = document.createElement("li");
            li.textContent = item.name + " x" + item.qty + " - " + money(item.price * item.qty, F.formatINR);
            list.appendChild(li);
        });
        items.appendChild(list);
        container.appendChild(items);
    }

    document.addEventListener("DOMContentLoaded", function () {
        var view = document.body.getAttribute("data-view");
        if (view === "checkout") initCheckout();
        else if (view === "success") initSuccess();
    });
})();
