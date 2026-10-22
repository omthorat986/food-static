/* Foodies Restaurant & Dish Reviews, Recipe Sharing & Community Moderation */
(function () {
    "use strict";

    var allPublicReviews = [];
    var currentFilter = "all";

    function byId(id) {
        return document.getElementById(id);
    }

    function setMessage(el, text, isError) {
        if (!el) return;
        el.textContent = text || "";
        el.style.display = text ? "block" : "none";
        el.className = "notice-banner";
        if (isError) {
            el.style.backgroundColor = "#fef2f2";
            el.style.borderColor = "#fecaca";
            el.style.color = "#991b1b";
        } else {
            el.style.backgroundColor = "#f0fdf4";
            el.style.borderColor = "#bbf7d0";
            el.style.color = "#166534";
        }
    }

    function renderStars(rating) {
        var num = Math.min(5, Math.max(1, parseInt(rating, 10) || 5));
        var stars = "";
        for (var i = 0; i < 5; i++) {
            stars += (i < num) ? "★" : "☆";
        }
        return '<span class="star-rating" title="' + num + '/5 stars">' + stars + '</span>';
    }

    function getCategoryBadge(cat) {
        cat = (cat || "restaurant_review").toLowerCase();
        if (cat === "recipe") {
            return '<span class="category-badge category-recipe">📖 Shared Recipe</span>';
        } else if (cat === "dish_review") {
            return '<span class="category-badge category-dish">🍲 Dish Review</span>';
        } else {
            return '<span class="category-badge category-restaurant">🍽️ Restaurant Review</span>';
        }
    }

    /* ---------------- Public Community Reviews & Recipes ---------------- */
    function loadPublicReviews() {
        var container = byId("public-reviews-grid");
        if (!container) return;

        fetch("/api/reviews/public")
            .then(function (res) { return res.json(); })
            .then(function (data) {
                allPublicReviews = data.reviews || data.submissions || [];
                renderFilteredPublicReviews();
            })
            .catch(function () {
                container.innerHTML = '<p style="color:#ef4444;">Failed to load reviews from cloud storage.</p>';
            });
    }

    function renderFilteredPublicReviews() {
        var container = byId("public-reviews-grid");
        if (!container) return;

        var filtered = allPublicReviews.filter(function (item) {
            if (currentFilter === "all") return true;
            return (item.category || "restaurant_review").toLowerCase() === currentFilter;
        });

        if (filtered.length === 0) {
            container.innerHTML = '<p style="color:#64748b; font-style:italic;">No approved reviews or recipes in this category yet. Be the first to share one!</p>';
            return;
        }

        container.innerHTML = filtered.map(function (item) {
            var safeTitle = escapeHtml(item.dish_name);
            var safeComment = escapeHtml(item.comment);
            var safeAuthor = escapeHtml(item.author_name || "Foodie Community Member");
            var dateStr = new Date(item.created_at).toLocaleDateString();
            var catBadge = getCategoryBadge(item.category);
            var starsHtml = renderStars(item.rating);

            return (
                '<div class="review-item">' +
                    '<div class="review-img-wrap">' +
                        '<img src="' + item.file_url + '" alt="' + safeTitle + '" loading="lazy" onerror="this.src=\'images/nonveg.jpg\'">' +
                    '</div>' +
                    '<div class="review-content">' +
                        '<div style="display:flex; justify-content:space-between; align-items:center;">' +
                            catBadge +
                            starsHtml +
                        '</div>' +
                        '<h3 class="review-title">' + safeTitle + '</h3>' +
                        '<p class="review-text">"' + safeComment + '"</p>' +
                        '<div class="review-meta">' +
                            '<span>Recommended by <strong>' + safeAuthor + '</strong></span>' +
                            '<span>' + dateStr + '</span>' +
                        '</div>' +
                    '</div>' +
                '</div>'
            );
        }).join("");
    }

    /* ---------------- User Submissions ---------------- */
    function loadUserReviews() {
        var container = byId("user-reviews-list");
        if (!container) return;

        var session = window.Foodies ? window.Foodies.getSession() : null;
        if (!session) {
            container.innerHTML = '<p style="color:#64748b;">Please <a href="login.html" style="color:#ef4f5f; font-weight:600;">log in</a> to view your private reviews and recipes.</p>';
            return;
        }

        fetch("/api/reviews/my")
            .then(function (res) {
                if (res.status === 401) throw new Error("Unauthorized");
                return res.json();
            })
            .then(function (data) {
                var items = data.reviews || data.submissions || [];
                if (items.length === 0) {
                    container.innerHTML = '<p style="color:#64748b;">You have not posted any reviews or recipes yet.</p>';
                    return;
                }

                container.innerHTML = items.map(function (item) {
                    var safeTitle = escapeHtml(item.dish_name);
                    var safeComment = escapeHtml(item.comment);
                    var statusClass = (item.status || "pending").toLowerCase();
                    var dateStr = new Date(item.created_at).toLocaleDateString();
                    var sizeKb = Math.round((item.file_size || 0) / 1024);
                    var catBadge = getCategoryBadge(item.category);
                    var starsHtml = renderStars(item.rating);

                    return (
                        '<div class="review-item" style="border-left: 4px solid ' + (statusClass === 'approved' ? '#10b981' : (statusClass === 'rejected' ? '#ef4444' : '#f59e0b')) + ';">' +
                            '<div class="review-content">' +
                                '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">' +
                                    catBadge +
                                    '<span class="status-pill ' + statusClass + '">' + item.status + '</span>' +
                                '</div>' +
                                '<div style="display:flex; justify-content:space-between; align-items:center;">' +
                                    '<h3 class="review-title" style="margin:0;">' + safeTitle + '</h3>' +
                                    starsHtml +
                                '</div>' +
                                '<p class="review-text" style="margin-top:8px;">"' + safeComment + '"</p>' +
                                '<div class="review-meta">' +
                                    '<span>' + item.filename + ' (' + sizeKb + ' KB)</span>' +
                                    '<span>' + dateStr + '</span>' +
                                '</div>' +
                                '<div style="margin-top: 12px; display:flex; gap:10px;">' +
                                    '<a href="' + item.file_url + '" target="_blank" class="moderator-action-btn" style="background:#0284c7; color:#fff; text-decoration:none; padding:6px 14px;">View Attachment (Cloud URL)</a>' +
                                '</div>' +
                            '</div>' +
                        '</div>'
                    );
                }).join("");
            })
            .catch(function () {
                container.innerHTML = '<p style="color:#ef4444;">Could not load your private reviews.</p>';
            });
    }

    /* ---------------- Community Moderator & Curator Panel ---------------- */
    function loadModeratorReviews() {
        var tbody = byId("moderator-reviews-tbody");
        var moderatorSection = byId("community-moderator-section");
        if (!tbody || !moderatorSection) return;

        var session = window.Foodies ? window.Foodies.getSession() : null;
        var isModerator = session && (session.role === "moderator" || session.role === "admin" || session.role === "curator");
        if (!isModerator) {
            moderatorSection.style.display = "none";
            return;
        }

        moderatorSection.style.display = "block";

        fetch("/api/moderator/reviews")
            .then(function (res) {
                if (res.status === 403 || res.status === 401) {
                    moderatorSection.style.display = "none";
                    throw new Error("Forbidden");
                }
                return res.json();
            })
            .then(function (data) {
                var items = data.reviews || data.submissions || [];
                if (items.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#64748b;">No community posts currently pending moderation.</td></tr>';
                    return;
                }
                tbody.innerHTML = items.map(function (item) {
                    var safeUser = escapeHtml(item.user_email);
                    var safeTitle = escapeHtml(item.dish_name);
                    var statusClass = (item.status || "pending").toLowerCase();
                    var dateStr = new Date(item.created_at).toLocaleDateString();
                    var catBadge = getCategoryBadge(item.category);

                    return (
                        '<tr>' +
                            '<td><strong>#' + item.id + '</strong></td>' +
                            '<td>' + catBadge + '</td>' +
                            '<td>' + safeUser + '</td>' +
                            '<td>' + safeTitle + ' (' + (item.rating || 5) + '★)</td>' +
                            '<td><span class="status-pill ' + statusClass + '">' + item.status + '</span></td>' +
                            '<td>' + dateStr + '</td>' +
                            '<td>' +
                                '<a href="' + item.file_url + '" target="_blank" class="moderator-action-btn" style="background:#64748b; color:#fff; text-decoration:none;">View</a>' +
                                (item.status !== "approved" ? '<button class="moderator-action-btn btn-approve" data-id="' + item.id + '" data-action="approved">Approve</button>' : "") +
                                (item.status !== "rejected" ? '<button class="moderator-action-btn btn-reject" data-id="' + item.id + '" data-action="rejected">Reject</button>' : "") +
                                '<button class="moderator-action-btn btn-delete" data-id="' + item.id + '" data-action="delete">Delete</button>' +
                            '</td>' +
                        '</tr>'
                    );
                }).join("");

                // Attach button actions
                tbody.querySelectorAll("button[data-action]").forEach(function (btn) {
                    btn.addEventListener("click", function () {
                        var id = this.getAttribute("data-id");
                        var action = this.getAttribute("data-action");
                        handleModerationAction(id, action);
                    });
                });
            })
            .catch(function () {});
    }

    function getCsrfToken() {
        if (window.Foodies && window.Foodies.getCsrfToken) return window.Foodies.getCsrfToken();
        var match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
        if (match && match[1]) return decodeURIComponent(match[1]);
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.getAttribute("content")) return meta.getAttribute("content");
        return window.__CSRF_TOKEN__ || "";
    }

    function handleModerationAction(id, action) {
        if (action === "delete") {
            if (!confirm("Are you sure you want to delete post #" + id + " to keep the community clean? This removes the object from cloud storage.")) {
                return;
            }
            fetch("/api/moderator/reviews/" + id, {
                method: "DELETE",
                headers: {
                    "X-CSRF-Token": getCsrfToken()
                }
            })
                .then(function (res) { return res.json(); })
                .then(function () {
                    if (window.Foodies && window.Foodies.toast) window.Foodies.toast("Post #" + id + " removed by Moderator.");
                    loadModeratorReviews();
                    loadUserReviews();
                    loadPublicReviews();
                })
                .catch(function () {
                    alert("Failed to delete post.");
                });
        } else {
            fetch("/api/moderator/reviews/" + id + "/status", {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRF-Token": getCsrfToken()
                },
                body: JSON.stringify({ status: action })
            })
            .then(function (res) { return res.json(); })
            .then(function () {
                if (window.Foodies && window.Foodies.toast) window.Foodies.toast("Post #" + id + " marked as " + action + " by Moderator.");
                loadModeratorReviews();
                loadUserReviews();
                loadPublicReviews();
            })
            .catch(function () {
                alert("Failed to update status.");
            });
        }
    }

    /* ---------------- Review & Recipe Upload Form ---------------- */
    function initReviewForm() {
        var form = byId("review-upload-form");
        var msgEl = byId("review-status-message");
        var submitBtn = byId("review-submit-btn");
        var fileInput = byId("review-file-input");
        var fileNameDisplay = byId("file-name-display");

        if (!form) return;

        if (fileInput && fileNameDisplay) {
            fileInput.addEventListener("change", function () {
                if (fileInput.files && fileInput.files[0]) {
                    var f = fileInput.files[0];
                    fileNameDisplay.textContent = "Selected: " + f.name + " (" + Math.round(f.size / 1024) + " KB)";
                } else {
                    fileNameDisplay.textContent = "Attach Restaurant Photo, Dish Photo, or Recipe Card (PNG, JPG, WEBP - Max 5MB)";
                }
            });
        }

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            var session = window.Foodies ? window.Foodies.getSession() : null;
            if (!session) {
                setMessage(msgEl, "Please log in first to share a review or recipe.", true);
                return;
            }

            var category = form.elements.category ? form.elements.category.value : "restaurant_review";
            var title = form.elements.title.value.trim();
            var rating = form.elements.rating ? form.elements.rating.value : "5";
            var comment = form.elements.comment.value.trim();
            var file = fileInput ? fileInput.files[0] : null;

            if (!title || !comment) {
                setMessage(msgEl, "Please provide restaurant/dish/recipe title and details.", true);
                return;
            }

            if (!file) {
                setMessage(msgEl, "Please select an image file to upload.", true);
                return;
            }

            if (file.size > 5 * 1024 * 1024) {
                setMessage(msgEl, "File exceeds the 5MB size limit. Please choose a smaller image.", true);
                return;
            }

            var token = getCsrfToken();
            var formData = new FormData();
            formData.append("category", category);
            formData.append("dish_name", title);
            formData.append("title", title);
            formData.append("rating", rating);
            formData.append("comment", comment);
            formData.append("file", file);
            if (token) {
                formData.append("csrf_token", token);
            }

            submitBtn.disabled = true;
            submitBtn.textContent = "Publishing to Cloud Storage...";
            setMessage(msgEl, "Encrypting and uploading media to cloud storage...", false);

            fetch("/api/reviews", {
                method: "POST",
                headers: {
                    "X-CSRF-Token": token
                },
                body: formData
            })
            .then(function (res) {
                return res.json().then(function (data) {
                    return { status: res.status, data: data };
                });
            })
            .then(function (result) {
                submitBtn.disabled = false;
                submitBtn.textContent = "Publish Review / Recipe";

                if (result.status === 201 && result.data.success) {
                    setMessage(msgEl, "Published successfully! Your review/recipe is encrypted and awaiting community moderator approval.", false);
                    form.reset();
                    if (fileNameDisplay) fileNameDisplay.textContent = "Attach Restaurant Photo, Dish Photo, or Recipe Card (PNG, JPG, WEBP - Max 5MB)";
                    loadUserReviews();
                    loadModeratorReviews();
                    if (window.Foodies && window.Foodies.toast) window.Foodies.toast("Review/recipe submitted to community!");
                } else {
                    setMessage(msgEl, result.data.error || "Submission failed. Please check file format and size.", true);
                }
            })
            .catch(function () {
                submitBtn.disabled = false;
                submitBtn.textContent = "Publish Review / Recipe";
                setMessage(msgEl, "Network error: could not connect to server.", true);
            });
        });
    }

    function initFilterButtons() {
        var buttons = document.querySelectorAll(".filter-btn");
        buttons.forEach(function (btn) {
            btn.addEventListener("click", function () {
                buttons.forEach(function (b) { b.classList.remove("active"); });
                this.classList.add("active");
                currentFilter = this.getAttribute("data-filter") || "all";
                renderFilteredPublicReviews();
            });
        });
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    document.addEventListener("DOMContentLoaded", function () {
        initReviewForm();
        initFilterButtons();
        loadPublicReviews();
        loadUserReviews();
        loadModeratorReviews();
    });
})();
