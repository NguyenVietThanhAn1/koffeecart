# Incident write-ups

Real problems found in this project, written the way a post-incident review would be:
**symptom → root cause → fix → how we know it stays fixed**. Each fix has a regression test that
failed before the change. Commit references are on the `upgrade/phase-3-7` history.

---

## 1. Email password published in the repository

- **Symptom**: the Gmail app password used to send account emails was readable by anyone on the public GitHub repo.
- **Root cause**: `EMAIL_HOST_PASSWORD` was hard-coded in `koffeecart/settings.py`. The repo also tracked `.vagrant/` (with a private SSH key), `db.sqlite3`, `__pycache__/` and collected static files.
- **Fix** (Phase 0): every secret moved to environment variables read with `python-decouple`; `.env.example` lists names only; junk removed from the index and `.gitignore`/`.dockerignore` fixed. The leaked password must be **revoked** at Google: removing it from the latest commit does not remove it from git history.
- **Stays fixed**: CI runs Trivy with the `secret` scanner on every push.

## 2. Anyone could mark an order as paid (forged payment)

- **Symptom**: a `POST /orders/payments/` with JSON `{"status": "COMPLETED", ...}` turned an order into a paid order and reduced stock, without any payment.
- **Root cause**: the view trusted the payment status, amount and transaction id sent by the browser (they came from the PayPal button's JavaScript).
- **Fix** (Phase 2, S1): payments became cash on delivery decided on the server. The client sends only the order number; method, amount (`order.order_total`), status (`Pending`) and transaction id are set by the server.
- **Stays fixed**: `orders/tests.py::test_old_forged_json_payment_is_rejected`, `test_cod_payment_ignores_client_supplied_fields`.

## 3. Users could read other users' orders (IDOR)

- **Symptom**: user B opening `/accounts/order_detail/<A's order number>/` saw A's name, address and phone.
- **Root cause**: the order was fetched by number only, `Order.objects.get(order_number=...)`, with no owner check.
- **Fix** (Phase 2, S2): `get_object_or_404(Order, order_number=..., user=request.user)`; another user's order is a 404, which also hides that it exists. The same rule was applied to `order_complete`, cart lines and reviews.
- **Stays fixed**: `accounts/tests.py::test_order_detail_other_user_gets_404`, `carts/tests.py::test_cannot_remove_another_users_cart_item`.

## 4. Production site had no CSS or JavaScript

- **Symptom**: behind Nginx every `/static/...` request returned 404; the site rendered as unstyled HTML.
- **Root cause**: Django collected static files into `BASE_DIR/static`, but the Docker volume and Nginx `alias` pointed at `/app/staticfiles`. Nothing failed loudly because the Dockerfile ran `collectstatic || true`.
- **Fix** (Phase 1): `STATIC_ROOT = BASE_DIR / "staticfiles"`, `collectstatic` without `|| true` so a failure stops the build, and a one-shot `migrate` service refreshes the shared static volume on every deploy.
- **Stays fixed**: the CI smoke test starts the real production stack and requests a stylesheet through Nginx (`curl -fsSI http://localhost/static/css/koffee.css`).

## 5. The last item in stock could be sold twice

- **Symptom**: two customers paying at the same moment for the last unit could both succeed, leaving stock at -1; a crash halfway left an order paid but stock unchanged.
- **Root cause**: stock was read, checked and written without a transaction or row lock (read-modify-write race).
- **Fix** (Phase 2, B6): the whole payment runs in `transaction.atomic()`; the order and product rows are locked with `select_for_update()`; stock is checked for every line before anything is written.
- **Stays fixed**: `orders/test_concurrency.py` fires two payments in parallel threads against PostgreSQL in CI (SQLite ignores row locks, so these tests are skipped locally on purpose).

## 6. Cart changed after "Place order" was charged the old total

- **Symptom**: a customer could reach the confirmation page, add more items in another tab, then confirm: the order recorded the earlier (smaller) total for the larger set of items.
- **Root cause**: `order_total` was computed at `place_order`, while the order lines were built from the cart at `payments` time. Two moments, two different carts.
- **Fix** (Phase 4B, R1): inside the locked payment transaction the total is recomputed from the cart; if it differs from the confirmed total nothing is placed and the user is sent back to checkout.
- **Stays fixed**: `orders/tests.py::test_cart_changed_after_place_order_is_not_placed`.

## 7. Second user with the same email prefix got a server error

- **Symptom**: after `an@x.com` registered, registering `an@y.com` returned HTTP 500.
- **Root cause**: the username was derived as `email.split("@")[0]` and the column is unique, so the second insert raised `IntegrityError`.
- **Fix** (Phase 4B, R2): a unique username is generated (`an`, `an2`, ...). The email is the login; the username is only a display handle.
- **Stays fixed**: `accounts/tests.py::test_register_same_local_part_different_domain`.
