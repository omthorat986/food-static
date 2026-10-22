# Foodies — Static Frontend

A fully static version of the **Foodies** food-ordering website, converted from the
original PHP + MySQL project to pure **HTML5, CSS3 and vanilla JavaScript**.

The site runs with **no PHP, no MySQL, no backend and no build step**. It can be
hosted on Amazon S3 (static website hosting), any static server, or Nginx on EC2.

> All account, cart, order and checkout behaviour is a **local browser demo**.
> There is no real authentication, no database and no payment processing.

---

## Running locally

Any static web server works. Pick one:

**Python (already installed on most systems)**

```powershell
cd Foodies-Static
python -m http.server 8080
```

Then open <http://localhost:8080/>.

**Node**

```powershell
cd Foodies-Static
npx serve .
```

> Opening `index.html` directly with `file://` mostly works, but a local HTTP
> server is recommended so that `localStorage`, relative paths and the search
> behave exactly as they would when deployed.

### Deploying

- **Amazon S3**: upload the contents of `Foodies-Static/` to the bucket, enable
  static website hosting, set `index.html` as the index document.
- **Nginx (EC2)**: copy `Foodies-Static/` to `/var/www/foodies` and point a
  `root`/`try_files` directive at it. The project uses relative paths only, so it
  also works from a sub-directory (e.g. `https://example.com/foodies/`).

---

## Project structure

```text
Foodies-Static/
├── index.html              Homepage + live search
├── login.html              Demo login
├── register.html           Demo registration
├── orders.html             Demo order history
├── cart/
│   └── cart.html           Shopping cart (qty controls)
├── paypal/
│   ├── checkout.html       Demo checkout form (no payment)
│   ├── success.html        Simulated order confirmation
│   └── cancel.html         Cancelled-order page
├── cuisine/
│   ├── bengali.html
│   ├── chinese.html
│   ├── gujarati.html
│   ├── maharashtrian.html
│   ├── north-indian.html
│   ├── south-indian.html
│   ├── sweet.html
│   └── western.html
├── food/
│   └── food-details.html   Dish details (?name= &price= &image= &page=)
├── css/
│   ├── style.css           (original style.css)
│   ├── login.css  register.css  orders.css
│   ├── cart.css  cuisine.css
│   ├── checkout.css  success.css  cancel.css
│   └── food-details.css
├── js/
│   ├── food-data.js        Static catalog generated from the cuisine pages
│   ├── store.js            Cart + demo session + demo orders (localStorage)
│   ├── main.js             Homepage search
│   ├── cart.js             Cart rendering / quantities
│   ├── auth-demo.js        Login & registration validation
│   ├── checkout.js         Checkout + confirmation
│   ├── orders.js           Order history rendering
│   └── details.js          Dish details page
├── images/                 All original food photos and icons
├── README.md
└── .gitignore
```

All paths are relative — no absolute Windows paths, no `.php` routes.

---

## Pages converted

| Original (PHP)          | Converted (static)          |
| ----------------------- | --------------------------- |
| `index.php`             | `index.html`                |
| `login.php`             | `login.html`                |
| `register.php`          | `register.html`             |
| `orders.php`            | `orders.html`               |
| `cart/cart.php`         | `cart/cart.html`            |
| `paypal/checkout.php`   | `paypal/checkout.html`      |
| `paypal/success.php`    | `paypal/success.html`       |
| `paypal/cancel.php`     | `paypal/cancel.html`        |
| `cuisine/*.html` (8)    | `cuisine/*.html` (8)        |
| *(PHP includes)*        | `js/store.js` (shared state)|

Backend-only files that no longer exist as pages:
`db.php`, `logout.php`, `remove.php`, `cart/add-to-cart.php`,
`cart/remove.php`, `paypal/process.php`. Their behaviour is now handled in
JavaScript (`store.js`).

No original food-details page existed; `food/food-details.html` was added so that
dish links from the cuisine pages and the homepage search lead somewhere useful
instead of dead-ending.

---

## What is fully functional

- Cuisine navigation and all 8 menu pages (93 dishes, original photos/prices/descriptions).
- Homepage live search across every dish; results link to the dish details page.
- Add to cart from cuisine pages, search results and the dish details page.
- Cart: increase/decrease quantity, remove items, clear cart, live subtotal and
  grand total, dynamic cart badge in the navbar.
- Cart persists across page refreshes via `localStorage`.
- Empty-cart handling (checkout is hidden/blocked until the cart has items).
- Checkout form validation (name, address, phone) with inline error messages.
- Order confirmation page with a simulated order id/receipt, plus order history
  on the Orders page.

## Demonstrations only (NOT production features)

- **Login / registration**: purely client-side. Accounts are stored in
  `localStorage`; passwords are **never** stored or verified. The captcha is a
  cosmetic demo. This provides **no security whatsoever**.
- **Checkout / payment**: there is **no payment gateway**. Original PayPal
  sandbox integration, business email and server-side order saving were removed.
  Placing an order just writes a demo record to `localStorage`.
- **Orders**: stored only in the current browser; clearing browser data removes them.

These screens are clearly labelled as demos in the UI.

---

## Backend functionality removed

- `db.php` — MySQL connection (`mysqli_connect` to `foodie_db`) deleted.
- All SQL queries (`users`, `foods`, `cart_items`, `orders`, `order_items`) replaced
  with static data (`js/food-data.js`) and `localStorage`.
- `password_hash` / `password_verify` server-side auth removed.
- PHP sessions replaced with a clearly-labelled demo session in `localStorage`.
- PayPal sandbox redirect (`process.php`, business email, `return`/`cancel_return`
  URLs) removed.
- No credentials, API keys or secrets are present anywhere in this project.

---

## Testing performed

- All internal links and asset references (CSS/JS/images) checked programmatically —
  every referenced local file exists and there are no remaining `.php` links.
- JavaScript syntax-checked with Node.
- Pages served through a local static HTTP server and requested successfully
  (HTTP 200 for all pages and assets).
- Cart add/quantity/remove/total and `localStorage` persistence exercised.
- Checkout validation and the simulated order flow exercised.
- Confirmed no PHP/MySQL installation is required.

## Known limitations

- Search matches dish name, description and cuisine (not fuzzy/spelling tolerant).
- Demo data is per-browser; it is not shared between devices or users.
- The footer newsletter form still posts to the original third-party Mailchimp
  endpoint; it depends on that external account remaining active.
- The original project contained a stray `c.exe` binary and PHP-only files; none of
  them were copied into this static project.
# food-static
