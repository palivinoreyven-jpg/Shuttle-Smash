import os
import re
import uuid
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
from db import get_db
from helpers import create_notification, notify_all_admins, broadcast_notification
import cloudinary
import cloudinary.uploader

admin_bp = Blueprint('admin', __name__)

NAME_HAS_LETTER = re.compile(r'[A-Za-z]')

# ============================================================
# CLOUDINARY CONFIG
# ============================================================
cloudinary.config( 
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'), 
  api_key = os.getenv('CLOUDINARY_API_KEY'), 
  api_secret = os.getenv('CLOUDINARY_API_SECRET') 
)

# ============================================================
# UPLOAD CONFIG
# ============================================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, os.pardir))
PAYMENT_QR_FOLDER = os.path.join(PROJECT_ROOT, 'static', 'uploads', 'payment_qr')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def _allowed_file(filename):
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def _save_product_image(file_storage, product_id):
    if not file_storage or not file_storage.filename:
        return None
    if not _allowed_file(file_storage.filename):
        return None

    try:
        upload_result = cloudinary.uploader.upload(
            file_storage,
            folder="products",
            public_id=f"prod_{product_id}"
        )
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"[CLOUDINARY ERROR]: {e}")
        return None


def _save_qr_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not _allowed_file(file_storage.filename):
        return None

    try:
        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(
            file_storage,
            folder="payment_qr",
            public_id="current_qr"
        )
        # Return the secure URL
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"[CLOUDINARY ERROR]: {e}")
        return None


def _get_setting(cursor, key, default=None):
    cursor.execute("SELECT setting_value FROM settings WHERE setting_key = %s", (key,))
    row = cursor.fetchone()
    return row[0] if row and row[0] is not None else default


def _set_setting(cursor, key, value):
    cursor.execute("""
        INSERT INTO settings (setting_key, setting_value)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
    """, (key, value))


# ============================================================
# BOOKING VERIFY / COMPLETE / REJECT
# ============================================================
@admin_bp.route('/verify/<int:booking_id>', methods=['POST'])
def verify_booking(booking_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_name, email, court_number, booking_date, booking_time 
        FROM badminton_bookings 
        WHERE id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    cursor.execute("""
        UPDATE badminton_bookings 
        SET status = 'Verified', 
            verified_at = NOW(), 
            verified_by = %s 
        WHERE id = %s
    """, (session.get('user_email'), booking_id))

    cursor.close()
    conn.close()

    if booking and booking[1]:
        try:
            formatted_date = booking[3].strftime('%B %d, %Y') if hasattr(booking[3], 'strftime') else str(booking[3])
        except Exception:
            formatted_date = str(booking[3])

        create_notification(
            user_email=booking[1],
            title="Reservation Verified",
            message=(
                f"Good news! Your Court {booking[2]} reservation on {formatted_date} "
                f"at {booking[4]} has been verified. Your official receipt is ready — "
                f"view it from your dashboard."
            )
        )

    return redirect(url_for('bookings.my_bookings'))


@admin_bp.route('/booking/complete/<int:booking_id>', methods=['POST'])
def complete_booking(booking_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_name, email, court_number, booking_date, booking_time 
        FROM badminton_bookings 
        WHERE id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    cursor.execute("""
        INSERT INTO past_bookings 
        (original_booking_id, customer_name, email, contact, court_number, 
         booking_date, booking_time, duration_hours, total_amount, status, 
         verified_at, verified_by, payment_proof_filename)
        SELECT id, customer_name, email, contact, court_number, 
               booking_date, booking_time, duration_hours, total_amount, 'Completed',
               verified_at, verified_by, payment_proof_filename
        FROM badminton_bookings 
        WHERE id = %s
    """, (booking_id,))

    cursor.execute("DELETE FROM badminton_bookings WHERE id = %s", (booking_id,))

    cursor.close()
    conn.close()

    if booking[1]:
        try:
            formatted_date = booking[3].strftime('%B %d, %Y') if hasattr(booking[3], 'strftime') else str(booking[3])
        except Exception:
            formatted_date = str(booking[3])

        create_notification(
            user_email=booking[1],
            title="Reservation Completed",
            message=(
                f"Your Court {booking[2]} reservation on {formatted_date} at {booking[4]} "
                f"has been marked as Completed. Thank you for playing at Esguerra Badminton Court!"
            )
        )

    return redirect(url_for('bookings.my_bookings'))


@admin_bp.route('/reject/<int:booking_id>', methods=['POST'])
def reject_booking(booking_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    reason = (request.form.get('reason') or '').strip()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_name, email, contact, court_number, booking_date, booking_time, 
               duration_hours, total_amount, status 
        FROM badminton_bookings 
        WHERE id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    cursor.execute("""
        INSERT INTO past_bookings 
        (original_booking_id, customer_name, email, contact, court_number, 
         booking_date, booking_time, duration_hours, total_amount, status,
         verified_at, verified_by, payment_proof_filename)
        SELECT id, customer_name, email, contact, court_number, 
               booking_date, booking_time, duration_hours, total_amount, 'Rejected',
               NOW(), %s, payment_proof_filename
        FROM badminton_bookings 
        WHERE id = %s
    """, (session.get('user_email'), booking_id))

    cursor.execute("DELETE FROM badminton_bookings WHERE id = %s", (booking_id,))

    cursor.close()
    conn.close()

    if booking[1]:
        try:
            formatted_date = booking[4].strftime('%B %d, %Y') if hasattr(booking[4], 'strftime') else str(booking[4])
        except Exception:
            formatted_date = str(booking[4])

        reason_line = f" Reason: {reason}" if reason else ""

        create_notification(
            user_email=booking[1],
            title="Reservation Rejected",
            message=(
                f"Unfortunately, your Court {booking[3]} reservation on {formatted_date} "
                f"at {booking[5]} was not approved.{reason_line} "
                f"Please contact the court admin if you have questions, or make a new reservation."
            )
        )

    return redirect(url_for('bookings.my_bookings'))


# ============================================================
# PAYMENT PROOF VERIFY / REJECT / VIEW
# ============================================================
@admin_bp.route('/admin/payment-proof/<int:booking_id>', methods=['GET'])
def view_payment_proof(booking_id):
    """Redirect to the Cloudinary URL for the payment proof."""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT payment_proof_filename FROM badminton_bookings WHERE id = %s", (booking_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row or not row[0]:
        return "No proof uploaded", 404

    # If it's a Cloudinary URL, redirect to it directly
    if str(row[0]).startswith('http'):
        return redirect(row[0])

    # Fallback for old local files
    proof_dir = os.path.join(PROJECT_ROOT, 'static', 'uploads', 'payment_proofs')
    return send_from_directory(proof_dir, row[0])


@admin_bp.route('/admin/verify-payment/<int:booking_id>', methods=['POST'])
def verify_payment(booking_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_name, email, court_number, booking_date, booking_time 
        FROM badminton_bookings 
        WHERE id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    cursor.execute("""
        UPDATE badminton_bookings 
        SET status = 'Verified',
            verified_at = NOW(),
            verified_by = %s
        WHERE id = %s
    """, (session.get('user_email'), booking_id))

    cursor.close()
    conn.close()

    if booking[1]:
        try:
            formatted_date = booking[3].strftime('%B %d, %Y') if hasattr(booking[3], 'strftime') else str(booking[3])
        except Exception:
            formatted_date = str(booking[3])

        create_notification(
            user_email=booking[1],
            title="Payment Verified",
            message=(
                f"Your payment for Court {booking[2]} reservation on {formatted_date} "
                f"at {booking[4]} has been verified. Your official receipt is ready — "
                f"view it from your dashboard."
            )
        )

    return redirect(url_for('bookings.my_bookings'))


@admin_bp.route('/admin/reject-payment/<int:booking_id>', methods=['POST'])
def reject_payment(booking_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    reason = (request.form.get('reason') or '').strip()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_name, email, court_number, booking_date, booking_time 
        FROM badminton_bookings 
        WHERE id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    cursor.execute("""
        INSERT INTO past_bookings 
        (original_booking_id, customer_name, email, contact, court_number, 
         booking_date, booking_time, duration_hours, total_amount, status,
         verified_at, verified_by, payment_proof_filename)
        SELECT id, customer_name, email, contact, court_number, 
               booking_date, booking_time, duration_hours, total_amount, 'Rejected',
               NOW(), %s, payment_proof_filename
        FROM badminton_bookings 
        WHERE id = %s
    """, (session.get('user_email'), booking_id))

    cursor.execute("DELETE FROM badminton_bookings WHERE id = %s", (booking_id,))

    cursor.close()
    conn.close()

    if booking[1]:
        try:
            formatted_date = booking[3].strftime('%B %d, %Y') if hasattr(booking[3], 'strftime') else str(booking[3])
        except Exception:
            formatted_date = str(booking[3])

        reason_line = f" Reason: {reason}" if reason else ""

        create_notification(
            user_email=booking[1],
            title="Payment Rejected",
            message=(
                f"Your payment for Court {booking[2]} reservation on {formatted_date} "
                f"at {booking[4]} was not approved.{reason_line} "
                f"Please contact the court admin for details."
            )
        )

    return redirect(url_for('bookings.my_bookings'))


# ============================================================
# PAYMENT SETTINGS PAGE
# ============================================================
@admin_bp.route('/admin/payment-settings', methods=['GET'])
def payment_settings_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    settings_dict = {
        'payment_qr_filename': _get_setting(cursor, 'payment_qr_filename'),
        'payment_wallet_name': _get_setting(cursor, 'payment_wallet_name', 'GCash'),
        'payment_wallet_number': _get_setting(cursor, 'payment_wallet_number', ''),
        'payment_instructions': _get_setting(cursor, 'payment_instructions', ''),
    }

    cursor.close()
    conn.close()

    return render_template('admin_payment_settings.html', settings=settings_dict)


@admin_bp.route('/admin/payment-settings/update', methods=['POST'])
def update_payment_settings():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    wallet_name = (request.form.get('payment_wallet_name') or '').strip() or 'GCash'
    wallet_number = (request.form.get('payment_wallet_number') or '').strip()
    instructions = (request.form.get('payment_instructions') or '').strip()

    conn = get_db()
    cursor = conn.cursor()

    _set_setting(cursor, 'payment_wallet_name', wallet_name)
    _set_setting(cursor, 'payment_wallet_number', wallet_number)
    _set_setting(cursor, 'payment_instructions', instructions)

    qr_file = request.files.get('qr_image')
    if qr_file and qr_file.filename:
        saved_name = _save_qr_image(qr_file)
        if saved_name:
            _set_setting(cursor, 'payment_qr_filename', saved_name)

    cursor.close()
    conn.close()

    return redirect(url_for('admin.payment_settings_page'))


@admin_bp.route('/admin/payment-settings/remove-qr', methods=['POST'])
def remove_payment_qr():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    _set_setting(cursor, 'payment_qr_filename', '')
    cursor.close()
    conn.close()

    return redirect(url_for('admin.payment_settings_page'))


# ============================================================
# SHOP ORDER VERIFY / REJECT / SHIP / COMPLETE
# ============================================================
@admin_bp.route('/shop-order/verify/<int:order_id>', methods=['POST'])
def verify_shop_order(order_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_email, product_name, quantity, total_amount, status 
        FROM shop_transactions 
        WHERE id = %s
    """, (order_id,))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.my_orders'))

    cursor.execute("SELECT id FROM products WHERE name = %s LIMIT 1", (order[1],))
    product_row = cursor.fetchone()

    if product_row:
        cursor.execute("""
            UPDATE product_stocks 
            SET stock = GREATEST(stock - %s, 0) 
            WHERE product_id = %s
        """, (order[2], product_row[0]))

    cursor.execute("""
        UPDATE shop_transactions 
        SET status = 'Verified', 
            verified_at = NOW(), 
            verified_by = %s 
        WHERE id = %s
    """, (session.get('user_email'), order_id))

    cursor.close()
    conn.close()

    if order[0]:
        create_notification(
            user_email=order[0],
            title="Order Verified",
            message=(
                f"Your order #{order_id} ({order[1]} x{order[2]}) has been verified. "
                f"Your official receipt is ready — view it from your dashboard. "
                f"We'll notify you when it ships."
            )
        )

    return redirect(url_for('shop.my_orders'))


@admin_bp.route('/shop-order/reject/<int:order_id>', methods=['POST'])
def reject_shop_order(order_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    reason = (request.form.get('reason') or '').strip()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_email, product_name, quantity, total_amount, status 
        FROM shop_transactions 
        WHERE id = %s
    """, (order_id,))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.my_orders'))

    cursor.execute("""
        UPDATE shop_transactions 
        SET status = 'Rejected', 
            verified_at = NOW(), 
            verified_by = %s 
        WHERE id = %s
    """, (session.get('user_email'), order_id))

    cursor.close()
    conn.close()

    if order[0]:
        reason_line = f" Reason: {reason}" if reason else ""

        create_notification(
            user_email=order[0],
            title="Order Rejected",
            message=(
                f"Unfortunately, your order #{order_id} ({order[1]} x{order[2]}) "
                f"was not approved.{reason_line} "
                f"Please contact the court admin if you have questions."
            )
        )

    return redirect(url_for('shop.my_orders'))


@admin_bp.route('/shop-order/ship/<int:order_id>', methods=['POST'])
def ship_shop_order(order_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_email, product_name, quantity 
        FROM shop_transactions 
        WHERE id = %s
    """, (order_id,))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.my_orders'))

    cursor.execute("""
        UPDATE shop_transactions 
        SET status = 'Shipped', 
            delivered_at = NOW() 
        WHERE id = %s
    """, (order_id,))

    cursor.close()
    conn.close()

    if order[0]:
        create_notification(
            user_email=order[0],
            title="Order Shipped",
            message=(
                f"Your order #{order_id} ({order[1]} x{order[2]}) has been shipped. "
                f"Please pick it up at the court counter."
            )
        )

    return redirect(url_for('shop.my_orders'))


@admin_bp.route('/shop-order/complete/<int:order_id>', methods=['POST'])
def complete_shop_order(order_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_email, product_name, quantity 
        FROM shop_transactions 
        WHERE id = %s
    """, (order_id,))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.my_orders'))

    cursor.execute("""
        UPDATE shop_transactions 
        SET status = 'Completed' 
        WHERE id = %s
    """, (order_id,))

    cursor.close()
    conn.close()

    if order[0]:
        create_notification(
            user_email=order[0],
            title="Order Completed",
            message=(
                f"Your order #{order_id} ({order[1]} x{order[2]}) is now Complete. "
                f"Thank you for shopping at Esguerra Badminton Court!"
            )
        )

    return redirect(url_for('shop.my_orders'))


# ============================================================
# STOCK / PRODUCTS
# ============================================================
@admin_bp.route('/admin/stocks')
def admin_stocks():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.name, p.category, p.price, ps.stock, p.description, p.is_active, p.image_filename
        FROM products p 
        JOIN product_stocks ps ON p.id = ps.product_id 
        ORDER BY p.is_active DESC, p.category, p.name
    """)
    products = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('admin_stocks.html', products=products)


@admin_bp.route('/add_product', methods=['POST'])
def add_product():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    name = (request.form.get('name') or '').strip()
    category = request.form.get('category')
    price = request.form.get('price')
    stock = request.form.get('stock')
    description = request.form.get('description')

    if not NAME_HAS_LETTER.search(name):
        return redirect(url_for('admin.admin_stocks'))

    if name and category and price and stock:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO products (name, category, price, description, is_active, image_filename)
            VALUES (%s, %s, %s, %s, 1, NULL)
        """, (name, category, float(price), description))

        product_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO product_stocks (product_id, stock)
            VALUES (%s, %s)
        """, (product_id, int(stock)))

        image_file = request.files.get('image')
        if image_file and image_file.filename:
            saved_url = _save_product_image(image_file, product_id)
            if saved_url:
                cursor.execute("""
                    UPDATE products SET image_filename = %s WHERE id = %s
                """, (saved_url, product_id))

        cursor.close()
        conn.close()

    return redirect(url_for('admin.admin_stocks'))


@admin_bp.route('/update_product/<int:product_id>', methods=['POST'])
def update_product(product_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    name = (request.form.get('name') or '').strip()
    price = request.form.get('price')
    description = request.form.get('description')

    if not NAME_HAS_LETTER.search(name):
        return redirect(url_for('admin.admin_stocks'))

    if name and price:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE products 
            SET name = %s, price = %s, description = %s 
            WHERE id = %s
        """, (name, float(price), description, product_id))

        image_file = request.files.get('image')
        if image_file and image_file.filename:
            saved_url = _save_product_image(image_file, product_id)
            if saved_url:
                cursor.execute("""
                    UPDATE products SET image_filename = %s WHERE id = %s
                """, (saved_url, product_id))

        cursor.close()
        conn.close()

    return redirect(url_for('admin.admin_stocks'))


@admin_bp.route('/restock/<int:product_id>', methods=['POST'])
def restock_product(product_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    additional_stock = request.form.get('additional_stock')

    if additional_stock and int(additional_stock) > 0:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE product_stocks 
            SET stock = stock + %s 
            WHERE product_id = %s
        """, (int(additional_stock), product_id))
        cursor.close()
        conn.close()

    return redirect(url_for('admin.admin_stocks'))


# ============================================================
# TOGGLE PRODUCT ACTIVE / INACTIVE
# ============================================================
@admin_bp.route('/toggle_product/<int:product_id>', methods=['POST'])
def toggle_product(product_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE products 
        SET is_active = NOT is_active 
        WHERE id = %s
    """, (product_id,))

    cursor.close()
    conn.close()

    return redirect(url_for('admin.admin_stocks'))


# ============================================================
# BLOCKED DATES
# ============================================================
@admin_bp.route('/admin/blocked-dates')
def blocked_dates_page():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, blocked_date, reason, created_at 
        FROM blocked_dates 
        ORDER BY blocked_date ASC
    """)
    blocked = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template(
        'admin_blocked_dates.html',
        blocked_dates=blocked,
        today=date.today()
    )


@admin_bp.route('/admin/block-date', methods=['POST'])
def block_date():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    date_str = (request.form.get('blocked_date') or '').strip()
    reason = (request.form.get('reason') or '').strip() or None

    if not date_str:
        return redirect(url_for('admin.blocked_dates_page'))

    try:
        blocked_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return redirect(url_for('admin.blocked_dates_page'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM blocked_dates WHERE blocked_date = %s", (blocked_date,))
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        conn.close()
        return redirect(url_for('admin.blocked_dates_page'))

    cursor.execute("""
        INSERT INTO blocked_dates (blocked_date, reason)
        VALUES (%s, %s)
    """, (blocked_date, reason))

    cursor.execute("""
        SELECT id, customer_name, email, contact, court_number, booking_date, 
               booking_time, duration_hours, total_amount, status 
        FROM badminton_bookings 
        WHERE booking_date = %s
    """, (blocked_date,))
    affected = cursor.fetchall()

    affected_emails = []
    for b in affected:
        cursor.execute("""
            INSERT INTO past_bookings 
            (original_booking_id, customer_name, email, contact, court_number, 
             booking_date, booking_time, duration_hours, total_amount, status,
             verified_at, verified_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Cancelled', NOW(), %s)
        """, (b[0], b[1], b[2], b[3], b[4], b[5], str(b[6]), b[7], b[8],
              session.get('user_email')))

        cursor.execute("DELETE FROM badminton_bookings WHERE id = %s", (b[0],))

        if b[2]:
            affected_emails.append(b[2])

    cursor.close()
    conn.close()

    formatted_date = blocked_date.strftime('%B %d, %Y')

    broadcast_notification(
        title="Court Unavailable",
        message=f"Notice: Esguerra Badminton Court is not available on {formatted_date}. Please choose another date."
    )

    if affected_emails:
        for email in set(affected_emails):
            create_notification(
                user_email=email,
                title="Reservation Cancelled",
                message=(
                    f"Your reservation on {formatted_date} has been cancelled because "
                    f"Esguerra Badminton Court is unavailable that day. "
                    f"We apologize for the inconvenience."
                )
            )

    return redirect(url_for('admin.blocked_dates_page'))


@admin_bp.route('/admin/unblock-date/<int:blocked_id>', methods=['POST'])
def unblock_date(blocked_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blocked_dates WHERE id = %s", (blocked_id,))
    cursor.close()
    conn.close()

    return redirect(url_for('admin.blocked_dates_page'))