/* Food details page: reads ?name= &price= &image= &page= and shows the dish. */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var F = window.Foodies;
        var params = new URLSearchParams(window.location.search);

        var nameParam = (params.get("name") || "").trim();
        var priceParam = params.get("price") || "";
        var imageParam = params.get("image") || "";
        var pageParam = params.get("page") || "";

        var card = document.getElementById("details-card");
        var missing = document.getElementById("details-missing");
        function showMissing() {
            if (card) card.setAttribute("hidden", "");
            if (missing) missing.removeAttribute("hidden");
        }

        if (!card || !nameParam) {
            showMissing();
            return;
        }

        var catalog = Array.isArray(window.foodItems) ? window.foodItems : [];
        var match = null;
        for (var i = 0; i < catalog.length; i++) {
            if (catalog[i].name === nameParam) { match = catalog[i]; break; }
        }

        var price = Number(priceParam);
        if (!price && match) price = Number(match.price);
        if (!price) price = 0;

        var imageFile = imageParam.split("/").pop() || (match ? match.image.split("/").pop() : "");
        var pageFile = pageParam.split("/").pop() || (match ? match.page.split("/").pop() : "");
        var rootRelativePage = pageFile ? ("cuisine/" + pageFile) : "index.html";
        var base = (document.body.getAttribute("data-base")) || "";

        var imgEl = document.getElementById("details-img");
        if (imgEl && imageFile) {
            imgEl.src = base + "images/" + imageFile;
            imgEl.alt = nameParam;
        }

        var nameEl = document.getElementById("details-name");
        if (nameEl) nameEl.textContent = nameParam;
        document.title = nameParam + " - Foodies";

        var categoryEl = document.getElementById("details-category");
        if (categoryEl) categoryEl.textContent = match ? match.category : "Foodies menu";

        var ratingEl = document.getElementById("details-rating");
        if (ratingEl) {
            if (match && match.rating) {
                ratingEl.textContent = match.rating + " \u2605";
                ratingEl.removeAttribute("hidden");
            } else {
                ratingEl.setAttribute("hidden", "");
            }
        }

        var timeEl = document.getElementById("details-time");
        if (timeEl) {
            if (match && match.time) {
                timeEl.textContent = match.time;
                timeEl.removeAttribute("hidden");
            } else {
                timeEl.setAttribute("hidden", "");
            }
        }

        var descEl = document.getElementById("details-desc");
        if (descEl) {
            descEl.textContent = (match && match.desc)
                ? match.desc
                : "A popular dish from the Foodies menu.";
        }

        var priceEl = document.getElementById("details-price");
        if (priceEl && F) priceEl.textContent = F.formatINR(price);

        var form = document.getElementById("details-form");
        if (form) {
            form.setAttribute("data-page", rootRelativePage);
            form.setAttribute("data-image", "images/" + imageFile);
            var productInput = form.querySelector('[name="product"]');
            var priceInput = form.querySelector('[name="price"]');
            if (productInput) productInput.value = nameParam;
            if (priceInput) priceInput.value = price;
        }

        var back = document.getElementById("details-back");
        if (back) {
            back.href = base + rootRelativePage;
            var catLabel = match ? match.category : "menu";
            back.textContent = "\u2190 Back to " + catLabel;
        }

        if (F) F.updateBadges();
    });
})();
