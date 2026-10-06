"""Project-level checks: health endpoint and the home page."""
import logging

from django.db import connection
from django.urls import reverse


def test_health_ok(client, db):
    resp = client.get(reverse('health_check'))
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok', 'app': 'koffeecart', 'database': 'ok'}


def test_health_reports_database_failure_without_leaking_details(client, db, monkeypatch, caplog):
    def boom():
        raise RuntimeError('connection to server at "db-secret-host" failed')

    # Undo the patch right after the request so DB teardown can still connect.
    with monkeypatch.context() as patch, caplog.at_level(logging.ERROR):
        patch.setattr(connection, 'ensure_connection', boom)
        resp = client.get(reverse('health_check'))
    assert resp.status_code == 503
    assert resp.json() == {'status': 'degraded', 'app': 'koffeecart', 'database': 'error'}
    assert 'db-secret-host' not in resp.content.decode()
    assert 'db-secret-host' in caplog.text  # the detail goes to the server log instead


def test_home_page_lists_available_products_only(client, make_product):
    shown = make_product()
    hidden = make_product()
    hidden.is_available = False
    hidden.save()
    resp = client.get(reverse('home'))
    assert resp.status_code == 200
    names = [p.product_name for p in resp.context['products']]
    assert shown.product_name in names and hidden.product_name not in names


def _stored_session(client):
    from django.contrib.sessions.models import Session
    return Session.objects.get(session_key=client.session.session_key)


def test_session_expiry_slides_forward_on_activity(client, user_a):
    """Idle timeout is 1 hour, counted from the LAST request, not from login."""
    from datetime import timedelta
    from django.utils import timezone

    client.force_login(user_a)
    session = _stored_session(client)
    session.expire_date = timezone.now() + timedelta(minutes=5)  # pretend 55 idle minutes passed
    session.save()

    assert client.get(reverse('dashboard')).status_code == 200
    remaining = _stored_session(client).expire_date - timezone.now()
    assert timedelta(minutes=59) < remaining <= timedelta(hours=1)


def test_expired_session_is_logged_out(client, user_a):
    from datetime import timedelta
    from django.utils import timezone

    client.force_login(user_a)
    session = _stored_session(client)
    session.expire_date = timezone.now() - timedelta(seconds=1)
    session.save()

    resp = client.get(reverse('dashboard'))
    assert resp.status_code == 302
    assert resp.url.startswith(reverse('login'))
