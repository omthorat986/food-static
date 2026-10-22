/* Homepage: live search over the static food catalog (window.foodItems). */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var searchInput = document.getElementById("searchInput");
        var searchResults = document.getElementById("searchResults");
        var cuisineGrid = document.querySelector(".cuisine-grid");
        var exploreTitle = document.getElementById("exploreTitle");
        var noResults = document.getElementById("noResults");
        var foodItems = Array.isArray(window.foodItems) ? window.foodItems : [];

        if (!searchInput || !searchResults || !cuisineGrid || !noResults || !exploreTitle) return;

        searchResults.style.display = "none";

        function reset() {
            cuisineGrid.style.display = "grid";
            searchResults.style.display = "none";
            searchResults.innerHTML = "";
            noResults.style.display = "none";
            exploreTitle.style.display = "block";
        }

        function detailsUrl(item) {
            var imageName = String(item.image || "").split("/").pop();
            var pageName = String(item.page || "").split("/").pop();
            return "food/food-details.html" +
                "?name=" + encodeURIComponent(item.name) +
                "&price=" + encodeURIComponent(item.price) +
                "&image=" + encodeURIComponent(imageName) +
                "&page=" + encodeURIComponent(pageName);
        }

        function buildResult(item) {
            var itemDiv = document.createElement("div");
            itemDiv.className = "search-item";

            var link = document.createElement("a");
            link.href = detailsUrl(item);
            link.style.textDecoration = "none";
            link.style.color = "inherit";

            var img = document.createElement("img");
            img.src = item.image;
            img.alt = item.name;
            img.loading = "lazy";
            link.appendChild(img);

            var h3 = document.createElement("h3");
            h3.textContent = item.name;
            link.appendChild(h3);
            itemDiv.appendChild(link);

            var p = document.createElement("p");
            p.className = "price";
            p.textContent = "Rs. " + item.price;
            itemDiv.appendChild(p);

            var form = document.createElement("form");
            form.className = "add-to-cart-form";
            form.setAttribute("data-page", item.page || "index.html");

            var inputProduct = document.createElement("input");
            inputProduct.type = "hidden";
            inputProduct.name = "product";
            inputProduct.value = item.name;
            form.appendChild(inputProduct);

            var inputPrice = document.createElement("input");
            inputPrice.type = "hidden";
            inputPrice.name = "price";
            inputPrice.value = item.price;
            form.appendChild(inputPrice);

            var button = document.createElement("input");
            button.type = "submit";
            button.value = "Add";
            button.className = "add-to-cart";
            form.appendChild(button);

            itemDiv.appendChild(form);
            return itemDiv;
        }

        searchInput.addEventListener("input", function () {
            var value = searchInput.value.toLowerCase().trim();

            if (value === "") {
                reset();
                return;
            }

            cuisineGrid.style.display = "none";
            exploreTitle.style.display = "none";

            var results = foodItems.filter(function (item) {
                var haystack = [item.name, item.desc, item.category, item.page]
                    .join(" ").toLowerCase();
                return haystack.indexOf(value) !== -1;
            });

            searchResults.innerHTML = "";

            if (results.length > 0) {
                searchResults.style.display = "grid";
                noResults.style.display = "none";
                results.forEach(function (item) {
                    searchResults.appendChild(buildResult(item));
                });
            } else {
                searchResults.style.display = "none";
                noResults.style.display = "block";
            }
        });

        /* keep the card hover clickable area behaving like a link */
        searchInput.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                searchInput.value = "";
                reset();
            }
        });
    });
})();
