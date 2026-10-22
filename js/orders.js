/* Orders page: renders the locally stored demo order history. */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var list = document.getElementById("orders-list");
        var F = window.Foodies;
        if (!list || !F) return;

        var orders = F.getOrders().slice().reverse();

        if (orders.length === 0) {
            var empty = document.createElement("div");
            empty.className = "no-orders-message";
            var p = document.createElement("p");
            p.textContent = "No orders yet";
            var link = document.createElement("a");
            link.href = "index.html";
            link.className = "link-btn";
            link.textContent = "Start Shopping";
            empty.appendChild(p);
            empty.appendChild(link);
            list.appendChild(empty);
            return;
        }

        orders.forEach(function (order) {
            var card = document.createElement("div");
            card.className = "order-card";

            var header = document.createElement("div");
            header.className = "order-header";

            var left = document.createElement("div");
            var h3 = document.createElement("h3");
            h3.textContent = "Order #" + order.id;
            var date = document.createElement("p");
            date.className = "order-date";
            date.textContent = new Date(order.date).toLocaleDateString();
            left.appendChild(h3);
            left.appendChild(date);

            var badge = document.createElement("span");
            badge.className = "status-badge";
            badge.textContent = order.status || "Completed";

            header.appendChild(left);
            header.appendChild(badge);

            var body = document.createElement("div");
            body.className = "order-body";

            var nameP = document.createElement("p");
            var nameStrong = document.createElement("strong");
            nameStrong.textContent = "Customer: ";
            nameP.appendChild(nameStrong);
            nameP.appendChild(document.createTextNode(order.name || "N/A"));

            var totalP = document.createElement("p");
            var totalStrong = document.createElement("strong");
            totalStrong.textContent = "Total: ";
            totalP.appendChild(totalStrong);
            totalP.appendChild(document.createTextNode(F.formatINR(order.total)));

            var items = document.createElement("div");
            items.className = "items-list";
            (order.items || []).forEach(function (item) {
                var ip = document.createElement("p");
                ip.className = "item";
                ip.textContent = "- " + item.name + " x" + item.qty;
                items.appendChild(ip);
            });

            body.appendChild(nameP);
            body.appendChild(totalP);
            body.appendChild(items);

            card.appendChild(header);
            card.appendChild(body);
            list.appendChild(card);
        });
    });
})();
