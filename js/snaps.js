/* Foodies Snaps & Cloud Storage Gallery Logic */
(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function setMessage(el, text, isError) {
        if (!el) return;
        el.textContent = text || "";
        el.style.display = text ? "block" : "none";
        el.className = isError ? "notice-banner" : "notice-banner";
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

    /* ---------------- Public Gallery ---------------- */
    function loadPublicSnaps() {
        var container = byId("public-snaps-grid");
        if (!container) return;

        fetch("/api/submissions/public")
            .then(function (res) { return res.json(); })
            .then(function (data) {
                var items = data.submissions || [];
                if (items.length === 0) {
                    container.innerHTML = '<p style="color:#64748b; font-style:italic;">No approved community snaps yet. Be the first to share one!</p>';
                    return;
                }
                container.innerHTML = items.map(function (item) {
                    var safeTitle = escapeHtml(item.dish_name);
                    var safeComment = escapeHtml(item.comment);
                    var safeAuthor = escapeHtml(item.author_name || "Foodie Member");
                    var dateStr = new Date(item.created_at).toLocaleDateString();

                    return (
                        '<div class="snap-item">' +
                            '<div class="snap-img-wrap">' +
                                '<img src="' + item.file_url + '" alt="' + safeTitle + '" loading="lazy" onerror="this.src=\'images/nonveg.jpg\'">' +
                            '</div>' +
                            '<div class="snap-content">' +
                                '<h3 class="snap-title">' + safeTitle + '</h3>' +
                                '<p class="snap-comment">"' + safeComment + '"</p>' +
                                '<div class="snap-meta">' +
                                    '<span>By <strong>' + safeAuthor + '</strong></span>' +
                                    '<span>' + dateStr + '</span>' +
                                '</div>' +
                            '</div>' +
                        '</div>'
                    );
                }).join("");
            })
            .catch(function (err) {
                container.innerHTML = '<p style="color:#ef4444;">Failed to load public gallery from cloud storage.</p>';
            });
    }

    /* ---------------- User Submissions ---------------- */
    function loadUserSubmissions() {
        var container = byId("user-submissions-list");
        if (!container) return;

        var session = window.Foodies ? window.Foodies.getSession() : null;
        if (!session) {
            container.innerHTML = '<p style="color:#64748b;">Please <a href="login.html" style="color:#ef4f5f; font-weight:600;">log in</a> to view your private submissions.</p>';
            return;
        }

        fetch("/api/submissions/my")
            .then(function (res) {
                if (res.status === 401) throw new Error("Unauthorized");
                return res.json();
            })
            .then(function (data) {
                var items = data.submissions || [];
                if (items.length === 0) {
                    container.innerHTML = '<p style="color:#64748b;">You have not uploaded any dish snaps yet.</p>';
                    return;
                }
                container.innerHTML = items.map(function (item) {
                    var safeTitle = escapeHtml(item.dish_name);
                    var safeComment = escapeHtml(item.comment);
                    var statusClass = (item.status || "pending").toLowerCase();
                    var dateStr = new Date(item.created_at).toLocaleDateString();
                    var sizeKb = Math.round((item.file_size || 0) / 1024);

                    return (
                        '<div class="snap-item" style="border-left: 4px solid ' + (statusClass === 'approved' ? '#10b981' : (statusClass === 'rejected' ? '#ef4444' : '#f59e0b')) + ';">' +
                            '<div class="snap-content">' +
                                '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">' +
                                    '<h3 class="snap-title" style="margin:0;">' + safeTitle + '</h3>' +
                                    '<span class="status-pill ' + statusClass + '">' + item.status + '</span>' +
                                '</div>' +
                                '<p class="snap-comment">"' + safeComment + '"</p>' +
                                '<div class="snap-meta">' +
                                    '<span>' + item.filename + ' (' + sizeKb + ' KB)</span>' +
                                    '<span>' + dateStr + '</span>' +
                                '</div>' +
                                '<div style="margin-top: 12px; display:flex; gap:10px;">' +
                                    '<a href="' + item.file_url + '" target="_blank" class="admin-action-btn" style="background:#0284c7; color:#fff; text-decoration:none; padding:6px 14px;">View Attachment (Cloud URL)</a>' +
                                '</div>' +
                            '</div>' +
                        '</div>'
                    );
                }).join("");
            })
            .catch(function () {
                container.innerHTML = '<p style="color:#ef4444;">Could not load your private uploads.</p>';
            });
    }

    /* ---------------- Admin Curator Panel ---------------- */
    function loadAdminSubmissions() {
        var tbody = byId("admin-submissions-tbody");
        var adminSection = byId("admin-curator-section");
        if (!tbody || !adminSection) return;

        var session = window.Foodies ? window.Foodies.getSession() : null;
        if (!session || session.role !== "admin") {
            adminSection.style.display = "none";
            return;
        }

        adminSection.style.display = "block";

        fetch("/api/admin/submissions")
            .then(function (res) {
                if (res.status === 403 || res.status === 401) {
                    adminSection.style.display = "none";
                    throw new Error("Forbidden");
                }
                return res.json();
            })
            .then(function (data) {
                var items = data.submissions || [];
                if (items.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#64748b;">No submissions currently in system.</td></tr>';
                    return;
                }
                tbody.innerHTML = items.map(function (item) {
                    var safeUser = escapeHtml(item.user_email);
                    var safeDish = escapeHtml(item.dish_name);
                    var statusClass = (item.status || "pending").toLowerCase();
                    var dateStr = new Date(item.created_at).toLocaleDateString();

                    return (
                        '<tr>' +
                            '<td><strong>#' + item.id + '</strong></td>' +
                            '<td>' + safeUser + '</td>' +
                            '<td>' + safeDish + '</td>' +
                            '<td><span class="status-pill ' + statusClass + '">' + item.status + '</span></td>' +
                            '<td>' + dateStr + '</td>' +
                            '<td>' +
                                '<a href="' + item.file_url + '" target="_blank" class="admin-action-btn" style="background:#64748b; color:#fff; text-decoration:none;">View</a>' +
                                (item.status !== "approved" ? '<button class="admin-action-btn btn-approve" data-id="' + item.id + '" data-action="approved">Approve</button>' : "") +
                                (item.status !== "rejected" ? '<button class="admin-action-btn btn-reject" data-id="' + item.id + '" data-action="rejected">Reject</button>' : "") +
                                '<button class="admin-action-btn btn-delete" data-id="' + item.id + '" data-action="delete">Delete</button>' +
                            '</td>' +
                        '</tr>'
                    );
                }).join("");

                // Attach event listeners to buttons
                tbody.querySelectorAll("button[data-action]").forEach(function (btn) {
                    btn.addEventListener("click", function () {
                        var id = this.getAttribute("data-id");
                        var action = this.getAttribute("data-action");
                        handleAdminAction(id, action);
                    });
                });
            })
            .catch(function () {});
    }

    function handleAdminAction(id, action) {
        if (action === "delete") {
            if (!confirm("Are you sure you want to permanently delete submission #" + id + " and remove its object from cloud storage?")) {
                return;
            }
            fetch("/api/admin/submissions/" + id, { method: "DELETE" })
                .then(function (res) { return res.json(); })
                .then(function () {
                    if (window.Foodies && window.Foodies.toast) window.Foodies.toast("Submission #" + id + " deleted from cloud storage.");
                    loadAdminSubmissions();
                    loadUserSubmissions();
                    loadPublicSnaps();
                })
                .catch(function () {
                    alert("Failed to delete submission.");
                });
        } else {
            // Update status (approve / reject)
            fetch("/api/admin/submissions/" + id + "/status", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: action })
            })
            .then(function (res) { return res.json(); })
            .then(function () {
                if (window.Foodies && window.Foodies.toast) window.Foodies.toast("Submission #" + id + " marked as " + action + ".");
                loadAdminSubmissions();
                loadUserSubmissions();
                loadPublicSnaps();
            })
            .catch(function () {
                alert("Failed to update status.");
            });
        }
    }

    /* ---------------- Submission Upload Form ---------------- */
    function initUploadForm() {
        var form = byId("snap-upload-form");
        var msgEl = byId("upload-status-message");
        var submitBtn = byId("upload-submit-btn");
        var fileInput = byId("snap-file-input");
        var fileNameDisplay = byId("file-name-display");

        if (!form) return;

        if (fileInput && fileNameDisplay) {
            fileInput.addEventListener("change", function () {
                if (fileInput.files && fileInput.files[0]) {
                    var f = fileInput.files[0];
                    fileNameDisplay.textContent = "Selected: " + f.name + " (" + Math.round(f.size / 1024) + " KB)";
                } else {
                    fileNameDisplay.textContent = "Click or drag food image here (PNG, JPG, WEBP - Max 5MB)";
                }
            });
        }

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            var session = window.Foodies ? window.Foodies.getSession() : null;
            if (!session) {
                setMessage(msgEl, "Please log in first to upload a food snap.", true);
                return;
            }

            var dishName = form.elements.dish_name.value.trim();
            var comment = form.elements.comment.value.trim();
            var file = fileInput ? fileInput.files[0] : null;

            if (!dishName || !comment) {
                setMessage(msgEl, "Please provide dish name and review.", true);
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

            var formData = new FormData();
            formData.append("dish_name", dishName);
            formData.append("comment", comment);
            formData.append("file", file);

            submitBtn.disabled = true;
            submitBtn.textContent = "Uploading to Cloud Storage...";
            setMessage(msgEl, "Transferring encrypted file to cloud storage...", false);

            fetch("/api/submissions", {
                method: "POST",
                body: formData
            })
            .then(function (res) {
                return res.json().then(function (data) {
                    return { status: res.status, data: data };
                });
            })
            .then(function (result) {
                submitBtn.disabled = false;
                submitBtn.textContent = "Submit Dish Snap";

                if (result.status === 201 && result.data.success) {
                    setMessage(msgEl, "Uploaded successfully! Your submission is saved in cloud storage with AES256 encryption.", false);
                    form.reset();
                    if (fileNameDisplay) fileNameDisplay.textContent = "Click or drag food image here (PNG, JPG, WEBP - Max 5MB)";
                    loadUserSubmissions();
                    loadAdminSubmissions();
                    if (window.Foodies && window.Foodies.toast) window.Foodies.toast("Dish snap submitted successfully!");
                } else {
                    setMessage(msgEl, result.data.error || "Upload failed. Check file constraints.", true);
                }
            })
            .catch(function (err) {
                submitBtn.disabled = false;
                submitBtn.textContent = "Submit Dish Snap";
                setMessage(msgEl, "Network error: could not connect to server.", true);
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
        initUploadForm();
        loadPublicSnaps();
        loadUserSubmissions();
        loadAdminSubmissions();
    });
})();
