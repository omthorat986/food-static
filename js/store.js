/* =====================================================================
   Foodies static demo store
   Cart / demo session / demo orders are kept in localStorage only.
   No backend, no database, no real authentication or payments.
   ===================================================================== */
(function () {
    "use strict";

    var CART_KEY = "foodies_cart";
    var USERS_KEY = "foodies_users";
    var SESSION_KEY = "foodies_session";
    var ORDERS_KEY = "foodies_orders";
    var LAST_ORDER_KEY = "foodies_last_order";

    /* ---------- low level helpers ---------- */

    function read(key, fallback) {
        try {
            var raw = window.localStorage.getItem(key);
            if (!raw) return fallback;
            var value = JSON.parse(raw);
            return value === null || value === undefined ? fallback : value;
        } catch (e) {
            return fallback;
        }
    }

    function write(key, value) {
        try {
            window.localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            return false;
        }
    }

    /* Every asset/page path is stored relative to the site root so the
       site works from a subdirectory too. `data-base` on <body> supplies
       the prefix for the page currently being rendered. */
    function base() {
        var el = document.body;
        return (el && el.getAttribute("data-base")) || "";
    }

    function normalizeImage(img) {
        if (!img) return "";
        img = String(img).replace(/^(\.\.\/|\.\/)+/, "");
        if (img.indexOf("/") === -1) img = "images/" + img;
        return img;
    }

    function normalizePage(page) {
        if (!page) return "index.html";
        page = String(page).replace(/^(\.\.\/|\.\/)+/, "");
        if (page.indexOf("/") === -1) page = "cuisine/" + page;
        return page;
    }

    function assetUrl(path) {
        return base() + path;
    }

    function formatINR(amount) {
        var n = Number(amount) || 0;
        return "\u20B9" + (Math.round(n * 100) / 100).toString();
    }

    /* ---------- cart ---------- */

    function getCart() {
        var cart = read(CART_KEY, []);
        return Array.isArray(cart) ? cart : [];
    }

    function saveCart(cart) {
        write(CART_KEY, cart);
        updateBadges();
        try {
            document.dispatchEvent(new CustomEvent("foodies:cart-change"));
        } catch (e) { /* older browsers */ }
    }

    function cartCount() {
        return getCart().reduce(function (sum, item) {
            return sum + (Number(item.qty) || 0);
        }, 0);
    }

    function cartTotal() {
        return getCart().reduce(function (sum, item) {
            return sum + (Number(item.price) || 0) * (Number(item.qty) || 0);
        }, 0);
    }

    function addToCart(item) {
        if (!item || !item.name) return false;
        var cart = getCart();
        var name = String(item.name).trim();
        var price = Math.max(0, Number(item.price) || 0);
        var existing = null;
        for (var i = 0; i < cart.length; i++) {
            if (cart[i].name === name) { existing = cart[i]; break; }
        }
        if (existing) {
            existing.qty += 1;
        } else {
            cart.push({
                name: name,
                price: price,
                qty: 1,
                image: normalizeImage(item.image),
                page: normalizePage(item.page)
            });
        }
        saveCart(cart);
        return true;
    }

    function setQty(name, qty) {
        var cart = getCart();
        qty = Number(qty);
        if (!qty || qty < 1) qty = 1;
        var changed = false;
        cart.forEach(function (item) {
            if (item.name === name) { item.qty = Math.min(99, qty); changed = true; }
        });
        if (changed) saveCart(cart);
    }

    function removeItem(name) {
        var cart = getCart().filter(function (item) {
            return item.name !== name;
        });
        saveCart(cart);
    }

    function clearCart() {
        saveCart([]);
    }

    function updateBadges() {
        var count = cartCount();
        var i;
        var countEls = document.querySelectorAll("#cart-count");
        for (i = 0; i < countEls.length; i++) countEls[i].textContent = String(count);
        var pills = document.querySelectorAll(".cart-pill");
        for (i = 0; i < pills.length; i++) pills[i].textContent = "Cart (" + count + ")";
    }

    /* ---------- CSRF Protection ---------- */

    function getCsrfToken() {
        var match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
        if (match && match[1]) return decodeURIComponent(match[1]);
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.getAttribute("content")) return meta.getAttribute("content");
        return window.__CSRF_TOKEN__ || "";
    }

    function ensureCsrfToken(cb) {
        var existing = getCsrfToken();
        if (existing) {
            if (cb) cb(existing);
            return;
        }
        fetch("/api/auth/csrf-token")
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && data.csrf_token) {
                    window.__CSRF_TOKEN__ = data.csrf_token;
                    var meta = document.querySelector('meta[name="csrf-token"]');
                    if (meta) meta.setAttribute("content", data.csrf_token);
                }
                if (cb) cb(data && data.csrf_token ? data.csrf_token : "");
            })
            .catch(function () {
                if (cb) cb("");
            });
    }

    /* ---------- Cloud & Session Management ---------- */

    function getSession() {
        var s = read(SESSION_KEY, null);
        return (s && typeof s === "object") ? s : null;
    }

    function setSession(name, email, role) {
        write(SESSION_KEY, {
            name: name,
            email: email,
            role: role || "user",
            createdAt: new Date().toISOString()
        });
        renderAuth();
    }

    function clearSession() {
        try { window.localStorage.removeItem(SESSION_KEY); } catch (e) { write(SESSION_KEY, null); }
        // Clear server session with CSRF protection header
        try {
            ensureCsrfToken(function (token) {
                fetch("/api/auth/logout", {
                    method: "POST",
                    headers: {
                        "X-CSRF-Token": token || getCsrfToken()
                    }
                }).catch(function () {});
            });
        } catch (e) {}
        renderAuth();
    }

    function getUsers() {
        var users = read(USERS_KEY, []);
        return Array.isArray(users) ? users : [];
    }

    function findUser(email) {
        email = String(email || "").toLowerCase().trim();
        var users = getUsers();
        for (var i = 0; i < users.length; i++) {
            if (String(users[i].email).toLowerCase() === email) return users[i];
        }
        return null;
    }

    function registerUser(name, email, role) {
        email = String(email || "").toLowerCase().trim();
        if (findUser(email)) return false;
        var users = getUsers();
        users.push({ name: name, email: email, role: role || "user", createdAt: new Date().toISOString() });
        write(USERS_KEY, users);
        return true;
    }

    function renderAuth() {
        var greeting = document.getElementById("nav-greeting");
        if (!greeting && !document.getElementById("nav-login")) return;
        var session = getSession();
        var login = document.getElementById("nav-login");
        var register = document.getElementById("nav-register");
        var logout = document.getElementById("nav-logout");
        var user = document.getElementById("nav-user");
        var roleBadge = document.getElementById("nav-role-badge");

        function set(el, visible) {
            if (!el) return;
            if (visible) el.removeAttribute("hidden");
            else el.setAttribute("hidden", "");
        }
        set(login, !session);
        set(register, !session);
        set(greeting, !!session);
        set(logout, !!session);
        if (session && user) {
            user.textContent = session.name;
        }
        if (roleBadge) {
            if (session && session.role === "admin") {
                roleBadge.removeAttribute("hidden");
                roleBadge.textContent = "Admin Curator";
                roleBadge.style.background = "#be123c";
            } else if (session && session.role === "moderator") {
                roleBadge.removeAttribute("hidden");
                roleBadge.textContent = "Community Moderator";
                roleBadge.style.background = "#0284c7";
            } else {
                roleBadge.setAttribute("hidden", "");
            }
        }

        // Show/hide role-specific elements on the page for moderators and admins
        var isPrivileged = session && (session.role === "admin" || session.role === "moderator" || session.role === "curator");
        var privilegedElements = document.querySelectorAll(".admin-only, .moderator-only");
        privilegedElements.forEach(function (el) {
            if (isPrivileged) {
                el.style.display = "";
            } else {
                el.style.display = "none";
            }
        });
    }

    function syncAuthWithServer() {
        fetch("/api/auth/me")
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.authenticated && data.user) {
                    setSession(data.user.name, data.user.email, data.user.role);
                }
            })
            .catch(function () {});
    }

    function initHealthPolling() {
        // Status indicator removed from UI
        return;
    }

    /* ---------- demo orders ---------- */

    function getOrders() {
        var orders = read(ORDERS_KEY, []);
        return Array.isArray(orders) ? orders : [];
    }

    function addOrder(order) {
        var orders = getOrders();
        orders.push(order);
        write(ORDERS_KEY, orders);
        write(LAST_ORDER_KEY, order);
        return order;
    }

    function getLastOrder() {
        return read(LAST_ORDER_KEY, null);
    }

    /* ---------- UI helpers ---------- */

    function toast(message) {
        var styleId = "foodies-toast-style";
        if (!document.getElementById(styleId)) {
            var style = document.createElement("style");
            style.id = styleId;
            style.textContent =
                ".foodies-toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(24px);" +
                "background:#1c1c1c;color:#fff;padding:12px 24px;border-radius:999px;font-size:0.95rem;font-weight:600;" +
                "box-shadow:0 8px 24px rgba(0,0,0,.28);opacity:0;transition:opacity .25s ease,transform .25s ease;" +
                "z-index:9999;pointer-events:none;max-width:90vw;text-align:center}" +
                ".foodies-toast.show{opacity:1;transform:translateX(-50%) translateY(0)}";
            document.head.appendChild(style);
        }
        var old = document.querySelector(".foodies-toast");
        if (old && old.parentNode) old.parentNode.removeChild(old);
        var el = document.createElement("div");
        el.className = "foodies-toast";
        el.textContent = message;
        document.body.appendChild(el);
        window.setTimeout(function () { el.classList.add("show"); }, 10);
        window.setTimeout(function () {
            el.classList.remove("show");
            window.setTimeout(function () {
                if (el.parentNode) el.parentNode.removeChild(el);
            }, 300);
        }, 1800);
    }

    function resolveFormProduct(form) {
        var nameEl = form.querySelector('[name="product"]');
        var priceEl = form.querySelector('[name="price"]');
        var name = nameEl ? nameEl.value : (form.getAttribute("data-name") || "");
        var price = priceEl ? priceEl.value : (form.getAttribute("data-price") || "0");

        var scope = form.closest(".item-card, .search-item, .food-details-card, [data-item]");
        var img = form.getAttribute("data-image") || "";
        var page = form.getAttribute("data-page") || "";
        if (!img && scope) {
            var imgEl = scope.querySelector("img");
            if (imgEl) img = imgEl.getAttribute("src") || "";
        }
        if (!page && scope && scope.getAttribute("data-page")) page = scope.getAttribute("data-page");
        if (!page) page = defaultPage();

        return { name: name, price: price, image: img, page: page };
    }

    function defaultPage() {
        var path = window.location.pathname || "";
        if (path.indexOf("/cuisine/") !== -1) {
            var file = path.split("/").pop();
            return "cuisine/" + file;
        }
        return "index.html";
    }

    /* ---------- global behaviour wiring ---------- */

    function handleAddFormSubmit(event) {
        var form = event.target;
        if (!form || !form.classList || !form.classList.contains("add-to-cart-form")) return;
        event.preventDefault();
        var item = resolveFormProduct(form);
        if (!item.name) return;
        if (addToCart(item)) {
            toast(item.name + " added to cart");
        }
    }

    document.addEventListener("submit", handleAddFormSubmit);

    document.addEventListener("DOMContentLoaded", function () {
        ensureCsrfToken();
        updateBadges();
        renderAuth();
        syncAuthWithServer();
        initHealthPolling();

        var logout = document.getElementById("nav-logout");
        if (logout) {
            logout.addEventListener("click", function (event) {
                event.preventDefault();
                clearSession();
                toast("Logged out successfully");
            });
        }
    });

    window.getCsrfToken = getCsrfToken;
    window.ensureCsrfToken = ensureCsrfToken;

    window.Foodies = {
        getCsrfToken: getCsrfToken,
        ensureCsrfToken: ensureCsrfToken,
        getCart: getCart,
        addToCart: addToCart,
        setQty: setQty,
        removeItem: removeItem,
        clearCart: clearCart,
        cartCount: cartCount,
        cartTotal: cartTotal,
        updateBadges: updateBadges,
        getSession: getSession,
        setSession: setSession,
        clearSession: clearSession,
        getUsers: getUsers,
        findUser: findUser,
        registerUser: registerUser,
        getOrders: getOrders,
        addOrder: addOrder,
        getLastOrder: getLastOrder,
        assetUrl: assetUrl,
        formatINR: formatINR,
        toast: toast,
        renderAuth: renderAuth,
        syncAuthWithServer: syncAuthWithServer,
        initHealthPolling: initHealthPolling
    };
})();
