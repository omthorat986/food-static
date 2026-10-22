/* Demo login / registration.
   Accounts are stored only in this browser's localStorage. There is no
   server, no database and no real authentication. Passwords are never
   stored or verified. */
(function () {
    "use strict";

    var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

    function byId(id) {
        return document.getElementById(id);
    }

    function setMessage(el, text, type) {
        if (!el) return;
        el.textContent = text || "";
        el.className = "message" + (text ? " " + (type || "") : "");
    }

    function newCaptcha(el) {
        var value = String(Math.floor(1000 + Math.random() * 9000));
        if (el) el.textContent = value;
        return value;
    }

    function getCsrfToken() {
        var match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
        if (match) return decodeURIComponent(match[1]);
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute("content");
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
                window.__CSRF_TOKEN__ = data.csrf_token;
                if (cb) cb(data.csrf_token);
            })
            .catch(function () {
                if (cb) cb("");
            });
    }

    /* ------------------------------ login ------------------------------ */

    function initLogin() {
        var form = byId("login-form");
        var F = window.Foodies;
        if (!form || !F) return;

        var messageEl = byId("auth-message");
        var captchaEl = byId("captcha-value");
        var captcha = newCaptcha(captchaEl);
        var emailEl = form.elements.email;
        var passwordEl = form.elements.password;
        var captchaInput = form.elements.captcha;

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            var email = String(emailEl.value).trim();
            var password = String(passwordEl.value);

            [emailEl, passwordEl, captchaInput].forEach(function (el) {
                el.classList.remove("input-error");
            });

            if (!EMAIL_RE.test(email)) {
                emailEl.classList.add("input-error");
                setMessage(messageEl, "Please enter a valid email address.", "error");
                return;
            }
            if (password.length < 6) {
                passwordEl.classList.add("input-error");
                setMessage(messageEl, "Password must be at least 6 characters.", "error");
                return;
            }
            if (String(captchaInput.value).trim() !== captcha) {
                captchaInput.classList.add("input-error");
                captcha = newCaptcha(captchaEl);
                setMessage(messageEl, "Captcha incorrect! Please try the new code.", "error");
                return;
            }

            /* Backend API call */
            setMessage(messageEl, "Verifying credentials with cloud backend...", "");
            ensureCsrfToken(function (token) {
                fetch("/api/auth/login", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": token || getCsrfToken()
                    },
                    body: JSON.stringify({ email: email, password: password })
                })
                .then(function (res) {
                    return res.json().then(function (data) {
                        return { status: res.status, data: data };
                    });
                })
                .then(function (result) {
                    if (result.status === 200 && result.data.success) {
                        var u = result.data.user;
                        F.setSession(u.name, u.email, u.role);
                        setMessage(messageEl, "Login successful! Redirecting...", "success");
                        window.setTimeout(function () {
                            window.location.href = "index.html";
                        }, 1000);
                    } else {
                        captcha = newCaptcha(captchaEl);
                        setMessage(messageEl, result.data.error || "Login failed. Check credentials.", "error");
                    }
                })
                .catch(function (err) {
                    captcha = newCaptcha(captchaEl);
                    setMessage(messageEl, "Could not connect to cloud server.", "error");
                });
            });
        });
    }

    /* ----------------------------- register ---------------------------- */

    function initRegister() {
        var form = byId("register-form");
        var F = window.Foodies;
        if (!form || !F) return;

        var messageEl = byId("auth-message");
        var nameEl = form.elements.name;
        var emailEl = form.elements.email;
        var passwordEl = form.elements.password;

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            var name = String(nameEl.value).trim();
            var email = String(emailEl.value).trim().toLowerCase();
            var password = String(passwordEl.value);

            [nameEl, emailEl, passwordEl].forEach(function (el) {
                el.classList.remove("input-error");
            });

            if (name.length < 2) {
                nameEl.classList.add("input-error");
                setMessage(messageEl, "Please enter your name.", "error");
                return;
            }
            if (!EMAIL_RE.test(email)) {
                emailEl.classList.add("input-error");
                setMessage(messageEl, "Please enter a valid email address.", "error");
                return;
            }
            if (password.length < 6) {
                passwordEl.classList.add("input-error");
                setMessage(messageEl, "Password must be at least 6 characters.", "error");
                return;
            }

            setMessage(messageEl, "Creating account in cloud database...", "");
            ensureCsrfToken(function (token) {
                fetch("/api/auth/register", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": token || getCsrfToken()
                    },
                    body: JSON.stringify({ name: name, email: email, password: password })
                })
                .then(function (res) {
                    return res.json().then(function (data) {
                        return { status: res.status, data: data };
                    });
                })
                .then(function (result) {
                    if (result.status === 201 && result.data.success) {
                        var u = result.data.user;
                        F.setSession(u.name, u.email, u.role);
                        setMessage(messageEl, "Registration successful! Welcome to Foodies.", "success");
                        window.setTimeout(function () {
                            window.location.href = "index.html";
                        }, 1200);
                    } else {
                        setMessage(messageEl, result.data.error || "Registration failed.", "error");
                    }
                })
                .catch(function (err) {
                    setMessage(messageEl, "Could not connect to cloud server.", "error");
                });
            });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        ensureCsrfToken();
        initLogin();
        initRegister();
    });
})();
