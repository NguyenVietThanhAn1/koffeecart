from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .forms import RegistrationForm, UserForm, UserProfileForm
from .models import Account, UserProfile
from orders.models import Order, OrderProduct
from django.contrib import messages, auth
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

# Verification email
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage

from carts.views import _cart_id, merge_guest_cart
import logging
from urllib.parse import parse_qs, urlencode, urlparse

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)


def _unique_username(email):
    """A username from the email's local part, made unique with a number when taken.

    "an@x.com" -> "an", then "an@y.com" -> "an2". The email is the login, the username
    is only a display name, so a suffix is harmless.
    """
    base = email.split('@')[0][:40] or 'user'
    username, n = base, 1
    while Account.objects.filter(username=username).exists():
        n += 1
        username = f'{base}{n}'
    return username


def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            phone_number = form.cleaned_data['phone_number']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            username = _unique_username(email)
            try:
                # Create the account and send the activation mail as one unit: if the mail
                # cannot be sent, the account is rolled back so the user can simply retry.
                with transaction.atomic():
                    user = Account.objects.create_user(first_name=first_name, last_name=last_name, email=email, username=username, password=password)
                    user.phone_number = phone_number
                    user.save()

                    # No picture yet: the templates show a static default avatar instead.
                    UserProfile.objects.create(user=user)

                    # USER ACTIVATION
                    current_site = get_current_site(request)
                    mail_subject = 'Please activate your account'
                    message = render_to_string('accounts/account_verification_email.html', {
                        'user': user,
                        'protocol': 'https' if request.is_secure() else 'http',
                        'domain': current_site,
                        'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                        'token': default_token_generator.make_token(user),
                    })
                    EmailMessage(mail_subject, message, to=[email]).send()
            except OSError:  # smtplib.SMTPException and connection errors are OSError subclasses
                logger.exception('Could not send verification email to %s', email)
                messages.error(request, 'We could not send the verification email. Please try again later.')
            else:
                query = urlencode({'command': 'verification', 'email': email})
                return redirect(reverse('login') + '?' + query)
    else:
        form = RegistrationForm()
    context = {
        'form': form,
    }
    return render(request, 'accounts/register.html', context)


def login(request):
    if request.method == 'POST':
        email = request.POST.get('email', '')
        password = request.POST.get('password', '')

        user = auth.authenticate(email=email, password=password)

        if user is not None:
            # Before auth.login(): logging in replaces the session key, which is the guest cart id.
            merge_guest_cart(_cart_id(request), user)
            auth.login(request, user)
            messages.success(request, 'You are now logged in.')
            # The login form posts the ?next= it was opened with. Older pages may not have
            # that field, so fall back to the Referer. Only follow it if it stays on this site.
            next_url = request.POST.get('next', '')
            if not next_url:
                referer = request.META.get('HTTP_REFERER', '')
                next_url = parse_qs(urlparse(referer).query).get('next', [''])[0]
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid login credentials')
            return redirect('login')
    return render(request, 'accounts/login.html')


@login_required(login_url = 'login')
@require_POST  # a GET link (or an <img src>) on any site could otherwise log users out
def logout(request):
    auth.logout(request)
    messages.success(request, 'You are logged out.')
    return redirect('login')


def activate(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = Account._default_manager.get(pk=uid)
    except(TypeError, ValueError, OverflowError, Account.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, 'Congratulations! Your account is activated.')
        return redirect('login')
    else:
        messages.error(request, 'Invalid activation link')
        return redirect('register')


@login_required(login_url = 'login')
def dashboard(request):
    orders = Order.objects.order_by('-created_at').filter(user_id=request.user.id, is_ordered=True)
    orders_count = orders.count()

    userprofile, created = UserProfile.objects.get_or_create(user=request.user)
    context = {
        'orders_count': orders_count,
        'userprofile': userprofile,
    }
    return render(request, 'accounts/dashboard.html', context)


def forgotPassword(request):
    if request.method == 'POST':
        email = request.POST.get('email', '')
        user = Account.objects.filter(email__iexact=email).first()
        if user is not None:
            try:
                current_site = get_current_site(request)
                mail_subject = 'Reset Your Password'
                message = render_to_string('accounts/reset_password_email.html', {
                    'user': user,
                    'protocol': 'https' if request.is_secure() else 'http',
                    'domain': current_site,
                    'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                    'token': default_token_generator.make_token(user),
                })
                EmailMessage(mail_subject, message, to=[email]).send()
            except Exception:
                logger.exception('Could not send password reset email to %s', email)

        # Same answer whether or not the account exists (or the mail failed), so this
        # form cannot be used to find out which emails are registered.
        messages.success(request, 'If an account exists for that email, we have sent a password reset link to it.')
        return redirect('login')
    return render(request, 'accounts/forgotPassword.html')


def resetpassword_validate(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = Account._default_manager.get(pk=uid)
    except(TypeError, ValueError, OverflowError, Account.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        request.session['uid'] = uid
        messages.success(request, 'Please reset your password')
        return redirect('resetPassword')
    else:
        messages.error(request, 'This link has been expired!')
        return redirect('login')


def resetPassword(request):
    # resetpassword_validate() puts the user id in the session after the emailed link is checked.
    uid = request.session.get('uid')
    user = Account.objects.filter(pk=uid).first() if uid else None
    if user is None:
        messages.error(request, 'Your password reset session has expired. Please request a new link.')
        return redirect('login')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if password != confirm_password:
            messages.error(request, 'Password do not match!')
            return redirect('resetPassword')
        try:
            validate_password(password, user)
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
            return redirect('resetPassword')

        user.set_password(password)
        user.save()
        del request.session['uid']  # the reset session is single use
        messages.success(request, 'Password reset successful')
        return redirect('login')
    return render(request, 'accounts/resetPassword.html')


@login_required(login_url='login')
def my_orders(request):
    orders = Order.objects.filter(user=request.user, is_ordered=True).order_by('-created_at')
    context = {
        'orders': orders,
    }
    return render(request, 'accounts/my_orders.html', context)


@login_required(login_url='login')
def edit_profile(request):
    userprofile, created = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, request.FILES, instance=userprofile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('edit_profile')
    else:
        user_form = UserForm(instance=request.user)
        profile_form = UserProfileForm(instance=userprofile)
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'userprofile': userprofile,
    }
    return render(request, 'accounts/edit_profile.html', context)


@login_required(login_url='login')
def change_password(request):
    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        user = request.user

        if new_password == confirm_password:
            success = user.check_password(current_password)
            if success:
                try:
                    validate_password(new_password, user)
                except ValidationError as exc:
                    for error in exc.messages:
                        messages.error(request, error)
                    return redirect('change_password')
                user.set_password(new_password)
                user.save()
                # A new password invalidates every session; keep this one logged in.
                update_session_auth_hash(request, user)
                messages.success(request, 'Password updated successfully.')
                return redirect('change_password')
            else:
                messages.error(request, 'Please enter valid current password')
                return redirect('change_password')
        else:
            messages.error(request, 'Password does not match!')
            return redirect('change_password')
    return render(request, 'accounts/change_password.html')


@login_required(login_url='login')
def order_detail(request, order_id):
    order = get_object_or_404(Order, order_number=order_id, user=request.user)
    order_detail = (OrderProduct.objects.filter(order=order)
                    .select_related('product__category').prefetch_related('variations'))
    subtotal = 0
    for i in order_detail:
        subtotal += i.product_price * i.quantity

    context = {
        'order_detail': order_detail,
        'order': order,
        'subtotal': subtotal,
    }
    return render(request, 'accounts/order_detail.html', context)