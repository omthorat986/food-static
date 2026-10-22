/* Cart page: renders the localStorage cart with quantity controls. */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var tbody = document.getElementById("cart-body");
        var totalEl = document.getElementById("cart-total");
        var checkoutBtn = document.getElementById("checkout-btn");
        var clearBtn = document.getElementById("clear-cart-btn");
        if (!tbody || !window.Foodies) return;

        var F = window.Foodies;

        function buildQtyControl(item) {
            var wrap = document.createElement("div");
            wrap.className = "qty-control";

            var dec = document.createElement("button");
            dec.type = "button";
            dec.className = "qty-btn";
            dec.setAttribute("data-action", "dec");
            dec.setAttribute("data-name", item.name);
            dec.setAttribute("aria-label", "Decrease quantity of " + item.name);
            dec.textContent = "\u2212";

            var value = document.createElement("span");
            value.className = "qty-value";
            value.textContent = String(item.qty);

            var inc = document.createElement("button");
            inc.type = "button";
            inc.className = "qty-btn";
            inc.setAttribute("data-action", "inc");
            inc.setAttribute("data-name", item.name);
            inc.setAttribute("aria-label", "Increase quantity of " + item.name);
            inc.textContent = "+";

            wrap.appendChild(dec);
            wrap.appendChild(value);
            wrap.appendChild(inc);
            return wrap;
        }

        function buildRow(item) {
            var tr = document.createElement("tr");

            var nameTd = document.createElement("td");
            nameTd.className = "product-name";
            var link = document.createElement("a");
            link.className = "cart-item-link";
            link.href = F.assetUrl(item.page || "index.html");
            link.textContent = item.name;
            nameTd.appendChild(link);
            tr.appendChild(nameTd);

            var priceTd = document.createElement("td");
            priceTd.textContent = F.formatINR(item.price);
            tr.appendChild(priceTd);

            var qtyTd = document.createElement("td");
            qtyTd.appendChild(buildQtyControl(item));
            tr.appendChild(qtyTd);

            var subtotalTd = document.createElement("td");
            subtotalTd.className = "subtotal";
            subtotalTd.textContent = F.formatINR(item.price * item.qty);
            tr.appendChild(subtotalTd);

            var actionTd = document.createElement("td");
            var remove = document.createElement("button");
            remove.type = "button";
            remove.className = "remove-link";
            remove.setAttribute("data-action", "remove");
            remove.setAttribute("data-name", item.name);
            remove.textContent = "Remove";
            actionTd.appendChild(remove);
            tr.appendChild(actionTd);

            return tr;
        }

        function render() {
            var cart = F.getCart();
            tbody.innerHTML = "";

            if (cart.length === 0) {
                var empty = document.createElement("tr");
                var cell = document.createElement("td");
                cell.colSpan = 5;
                cell.className = "empty-msg";
                cell.textContent = "Your cart is empty!";
                empty.appendChild(cell);
                tbody.appendChild(empty);
            } else {
                cart.forEach(function (item) {
                    tbody.appendChild(buildRow(item));
                });
            }

            if (totalEl) totalEl.textContent = F.formatINR(F.cartTotal());
            if (checkoutBtn) {
                if (cart.length === 0) checkoutBtn.setAttribute("hidden", "");
                else checkoutBtn.removeAttribute("hidden");
            }
            if (clearBtn) {
                if (cart.length === 0) clearBtn.setAttribute("hidden", "");
                else clearBtn.removeAttribute("hidden");
            }
        }

        tbody.addEventListener("click", function (event) {
            var btn = event.target.closest("[data-action]");
            if (!btn) return;
            var name = btn.getAttribute("data-name");
            var action = btn.getAttribute("data-action");
            var cart = F.getCart();
            var item = null;
            for (var i = 0; i < cart.length; i++) {
                if (cart[i].name === name) { item = cart[i]; break; }
            }
            if (!item) return;

            if (action === "inc") {
                F.setQty(name, item.qty + 1);
            } else if (action === "dec") {
                if (item.qty <= 1) F.removeItem(name);
                else F.setQty(name, item.qty - 1);
            } else if (action === "remove") {
                F.removeItem(name);
                F.toast(name + " removed from cart");
            }
            render();
        });

        if (clearBtn) {
            clearBtn.addEventListener("click", function () {
                F.clearCart();
                F.toast("Cart cleared");
                render();
            });
        }

        document.addEventListener("foodies:cart-change", render);
        render();
    });
})();
