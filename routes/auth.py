import os
import random
import resend
from resend.exceptions import ResendError
from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db

auth_bp = Blueprint('auth', __name__)

# ============================================================
# RESEND EMAIL CONFIG
# ============================================================
# Vercel will automatically inject this from your Environment Variables
resend.api_key = os.environ.get("RESEND_API_KEY")

def send_otp_email(to_email, subject, code):
    """Helper function to send OTP via Resend HTTP API"""
    try:
        # Using "from" (not "sender") based on your Vercel logs
        response = resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": [to_email],
            "subject": subject,
            "html": f"<p>Your verification code is: <strong>{code}</strong></p>"
        })
        print(f"[RESEND SUCCESS]: {response}")
        return True
    except Exception as e:
        print(f"[RESEND ERROR]: {e}")
        return False


# ============================================================
# SIGNUP
# ============================================================
@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        cursor.close()
        conn.close()

        if existing_user:
            error = "An account with that email already exists."
        else:
            verification_code = str(random.randint(100000, 999999))
            session['pending_user'] = {
                'name': name,
                'email': email,
                'password': password,
                'code': verification_code
            }

            # Send OTP using Resend
            send_otp_email(
                to_email=email, 
                subject="EBC Badminton - Email Verification", 
                code=verification_code
            )

            return redirect(url_for('auth.verify_email'))

    return render_template('signup.html', error=error)


@auth_bp.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    error = None
    pending_user = session.get('pending_user')

    if not pending_user:
        return redirect(url_for('auth.signup'))

    if request.method == 'POST':
        entered_code = request.form.get('code')

        if entered_code == pending_user['code']:
            conn = get_db()
            cursor = conn.cursor()
            hashed_password = generate_password_hash(pending_user['password'])
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (pending_user['name'], pending_user['email'], hashed_password, 'user')
            )
            cursor.close()
            conn.close()

            session.pop('pending_user', None)
            return redirect(url_for('auth.login'))
        else:
            error = 'Invalid verification code. Please try again.'

    return render_template('verify_email.html', error=error, email=pending_user['email'])


# ============================================================
# LOGIN
# ============================================================
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user_input = request.form.get('email') or request.form.get('username')
        password = request.form.get('password')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, password_hash, role, name FROM users WHERE email = %s",
            (user_input,)
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and (check_password_hash(user[2], password) or user[2] == password):
            session['logged_in'] = True
            session['user_email'] = user[1]
            session['user_name'] = user[4] if len(user) > 4 and user[4] else user[1]
            session['role'] = user[3]
            return redirect(url_for('bookings.index'))
        else:
            error = 'Invalid Email/Username or Password!'

    return render_template('login.html', error=error)


# ============================================================
# LOGOUT
# ============================================================
@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


# ============================================================
# FORGOT PASSWORD
# ============================================================
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    error = None
    if request.method == 'POST':
        email = request.form.get('email')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user:
            error = "No account found with that email address."
            return render_template('forgot_password.html', error=error)

        reset_otp = str(random.randint(100000, 999999))
        session['reset_password_data'] = {
            'email': email,
            'otp': reset_otp,
            'verified': False
        }

        # Send OTP using Resend
        send_otp_email(
            to_email=email, 
            subject="EBC Badminton - Password Reset Code", 
            code=reset_otp
        )

        return redirect(url_for('auth.verify_reset_otp'))

    return render_template('forgot_password.html', error=error)


@auth_bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    error = None
    reset_data = session.get('reset_password_data')

    if not reset_data or 'email' not in reset_data:
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        user_otp = request.form.get('otp')

        if user_otp == reset_data.get('otp'):
            reset_data['verified'] = True
            session['reset_password_data'] = reset_data
            session.modified = True
            return redirect(url_for('auth.reset_password'))
        else:
            error = "Invalid verification code. Please try again."

    return render_template('verify_reset_otp.html', error=error, email=reset_data['email'])


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    error = None
    reset_data = session.get('reset_password_data')

    if not reset_data or 'email' not in reset_data or not reset_data.get('verified'):
        return redirect(url_for('auth.forgot_password'))

    email = reset_data['email']

    if request.method == 'POST':
        new_pass = request.form.get('new_password')
        confirm_pass = request.form.get('confirm_password')

        if not new_pass or not confirm_pass:
            error = "Please fill in all fields."
        elif new_pass != confirm_pass:
            error = "Passwords do not match."
        else:
            hashed_password = generate_password_hash(new_pass)
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s", (hashed_password, email))
            cursor.close()
            conn.close()

            session.pop('reset_password_data', None)
            return redirect(url_for('auth.login'))

    return render_template('reset_password.html', error=error, email=email)