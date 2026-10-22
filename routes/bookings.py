import os
import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename
from db import get_db
from helpers import (
    CONTACT_REGEX, parse_time_obj, archive_expired_bookings,
    get_booking_end_dt, notify_all_admins
)
import cloudinary
import cloudinary.uploader

bookings_bp = Blueprint('bookings', __name__)

PER_PAGE = 5

# ============================================================
# CLOUDINARY CONFIG
# ============================================================
cloudinary.config( 
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'), 
  api_key = os.getenv('CLOUDINARY_API_KEY'), 
  api_secret = os.getenv('CLOUDINARY_API_SECRET') 
)

# ============================================================
# UPLOAD CONFIG — payment proofs
# ============================================================
ALLOWED_PROOF_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def _allowed_proof(filename):
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_PROOF_EXTENSIONS
    )

def _save_payment_proof(file_storage, booking_id):
    if not file_storage or not file_storage.filename:
        return None
    if not _allowed_proof(file_storage.filename):
        return None

    try:
        # Optimized upload to prevent Vercel timeouts
        upload_result = cloudinary.uploader.upload(
            file_storage,
            folder="payment_proofs",
            public_id=f"proof_{booking_id}",
            quality="auto",
            fetch_format="auto"
        )
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"[CLOUDINARY ERROR]: {e}")
        return None


# ============================================================
# DASHBOARD (index)
# ============================================================
@bookings_bp.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    archive_expired_bookings()

    conn = get_db()
    cursor = conn.cursor()
    chart_data = None
    user_email = session.get('user_email')
    is_admin = session.get('role') == 'admin'

    cursor.execute("""
        SELECT id, title, message, is_read, created_at
        FROM notifications
        WHERE user_email = %s
        ORDER BY created_at DESC
        LIMIT 30
    """, (user_email,))
    notif_rows = cursor.fetchall()
    notifications_list = []
    for n in notif_rows:
        notifications_list.append({
            'id': n[0],
            'title': n[1],
            'message': n[2],
            'is_read': bool(n[3]),
            'time': n[4].strftime('%b %d, %Y %I:%M %p') if n[4] else ''
        })

    # Counts — reject/cancel bookings are excluded from active counts
    if is_admin:
        cursor.execute("""
            SELECT COUNT(*) FROM badminton_bookings 
            WHERE LOWER(status) IN ('pending', 'pending verification', 'verified')
        """)
        active_bookings_count = cursor.fetchone()[0]
        cursor.execute("""
            SELECT COUNT(*) FROM shop_transactions 
            WHERE status IN ('Pending', 'Verified', 'Shipped')
        """)
        active_orders_count = cursor.fetchone()[0]
    else:
        cursor.execute("""
            SELECT COUNT(*) FROM badminton_bookings 
            WHERE email = %s 
              AND LOWER(status) IN ('pending', 'pending verification', 'verified')
        """, (user_email,))
        active_bookings_count = cursor.fetchone()[0]
        cursor.execute("""
            SELECT COUNT(*) FROM shop_transactions 
            WHERE user_email = %s AND status IN ('Pending', 'Verified', 'Shipped')
        """, (user_email,))
        active_orders_count = cursor.fetchone()[0]

    cart_count = len(session.get('cart', {})) if session.get('cart') else 0

    schedule_page = max(1, int(request.args.get('dash_schedule_page', 1)))
    hist_page = max(1, int(request.args.get('dash_hist_page', 1)))
    shop_page = max(1, int(request.args.get('dash_shop_page', 1)))

    schedule_offset = (schedule_page - 1) * PER_PAGE
    hist_offset = (hist_page - 1) * PER_PAGE
    shop_offset = (shop_page - 1) * PER_PAGE

    public_schedule = []
    total_schedule_pages = 1
    history_bookings = []
    total_hist_pages = 1
    shop_history = []
    total_shop_pages = 1

    if is_admin:
        cursor.execute("SELECT COUNT(*) FROM past_bookings")
        total_hist = cursor.fetchone()[0]
        total_hist_pages = max(1, (total_hist + PER_PAGE - 1) // PER_PAGE)

        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, 
                   duration_hours, total_amount, status
            FROM past_bookings 
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'completed' THEN 0
                    WHEN 'rejected' THEN 1
                    WHEN 'cancelled' THEN 1
                    ELSE 2
                END,
                booking_date DESC, booking_time DESC
            LIMIT %s OFFSET %s
        """, (PER_PAGE, hist_offset))
        history_bookings = cursor.fetchall()

        cursor.execute("""
            SELECT COUNT(*) FROM shop_transactions WHERE status IN ('Completed', 'Rejected')
        """)
        total_shop = cursor.fetchone()[0]
        total_shop_pages = max(1, (total_shop + PER_PAGE - 1) // PER_PAGE)

        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount, transaction_date, status
            FROM shop_transactions 
            WHERE status IN ('Completed', 'Rejected')
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'completed' THEN 0
                    WHEN 'rejected' THEN 1
                    ELSE 2
                END,
                transaction_date DESC
            LIMIT %s OFFSET %s
        """, (PER_PAGE, shop_offset))
        shop_history = cursor.fetchall()
    else:
        # Only show UPCOMING verified bookings on the public schedule
        cursor.execute("""
            SELECT COUNT(*) FROM badminton_bookings 
            WHERE LOWER(status) = 'verified'
              AND LOWER(status) NOT IN ('rejected', 'cancelled')
              AND booking_date >= CURDATE()
        """)
        total_schedule = cursor.fetchone()[0]
        total_schedule_pages = max(1, (total_schedule + PER_PAGE - 1) // PER_PAGE)

        cursor.execute("""
            SELECT id, court_number, booking_date, booking_time, duration_hours, status
            FROM badminton_bookings
            WHERE LOWER(status) = 'verified'
              AND LOWER(status) NOT IN ('rejected', 'cancelled')
              AND booking_date >= CURDATE()
            ORDER BY booking_date ASC, booking_time ASC
            LIMIT %s OFFSET %s
        """, (PER_PAGE, schedule_offset))
        public_schedule = cursor.fetchall()

    if is_admin:
        dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
        day_labels = [(datetime.now() - timedelta(days=i)).strftime('%a (%b %d)') for i in range(6, -1, -1)]

        cursor.execute("""
            SELECT booking_date_only, COALESCE(SUM(total_amt), 0) FROM (
                SELECT DATE(booking_date) AS booking_date_only, total_amount AS total_amt
                FROM badminton_bookings
                WHERE booking_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND LOWER(status) = 'verified'
                UNION ALL
                SELECT DATE(booking_date) AS booking_date_only, total_amount AS total_amt
                FROM past_bookings
                WHERE booking_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
            ) AS combined_revenue
            GROUP BY booking_date_only
        """)
        booking_raw = dict(cursor.fetchall())
        booking_map = {str(k): float(v) for k, v in booking_raw.items()}
        booking_series = [booking_map.get(d, 0.0) for d in dates]
        total_booking_revenue = sum(booking_map.values())

        cursor.execute("""
            SELECT DATE(transaction_date), COALESCE(SUM(total_amount), 0)
            FROM shop_transactions
            WHERE transaction_date >= DATE_SUB(NOW(), INTERVAL 6 DAY)
              AND status IN ('Verified', 'Shipped', 'Completed')
            GROUP BY DATE(transaction_date)
        """)
        shop_raw = dict(cursor.fetchall())
        shop_map = {str(k): float(v) for k, v in shop_raw.items()}
        shop_series = [shop_map.get(d, 0.0) for d in dates]

        cursor.execute("""
            SELECT day_name, COUNT(*) FROM (
                SELECT DAYNAME(booking_date) AS day_name FROM badminton_bookings WHERE LOWER(status) = 'verified'
                UNION ALL
                SELECT DAYNAME(booking_date) AS day_name FROM past_bookings
            ) AS combined_dow
            GROUP BY day_name
        """)
        dow_raw = dict(cursor.fetchall())
        days_full = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        dow_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        dow_series = [int(dow_raw.get(day, 0)) for day in days_full]

        chart_data = {
            'labels': day_labels,
            'booking_series': booking_series,
            'shop_series': shop_series,
            'total_booking': total_booking_revenue,
            'total_shop': sum(shop_series),
            'dow_labels': dow_labels,
            'dow_series': dow_series
        }

    cursor.close()
    conn.close()

    return render_template(
        'index.html',
        public_schedule=public_schedule,
        schedule_page=schedule_page,
        total_schedule_pages=total_schedule_pages,
        history_bookings=history_bookings,
        hist_page=hist_page,
        total_hist_pages=total_hist_pages,
        shop_history=shop_history,
        shop_page=shop_page,
        total_shop_pages=total_shop_pages,
        chart_data=chart_data,
        active_bookings_count=active_bookings_count,
        active_orders_count=active_orders_count,
        cart_count=cart_count,
        notifications=notifications_list,
        is_admin=is_admin
    )


# ============================================================
# MY RESERVATIONS
# ============================================================
@bookings_bp.route('/bookings')
def my_bookings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    user_email = session.get('user_email')
    is_admin = session.get('role') == 'admin'

    active_page = max(1, int(request.args.get('mb_active_page', 1)))
    history_page = max(1, int(request.args.get('mb_history_page', 1)))
    active_offset = (active_page - 1) * PER_PAGE
    history_offset = (history_page - 1) * PER_PAGE

    conn = get_db()
    cursor = conn.cursor()

    active_bookings = []
    total_active_pages = 1
    history_bookings = []
    total_history_pages = 1

    if is_admin:
        cursor.execute("""
            SELECT COUNT(*) FROM badminton_bookings 
            WHERE LOWER(status) IN ('pending', 'pending verification', 'verified')
        """)
        total_active = cursor.fetchone()[0]
        total_active_pages = max(1, (total_active + PER_PAGE - 1) // PER_PAGE)

        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, 
                   duration_hours, total_amount, status, payment_proof_filename
            FROM badminton_bookings 
            WHERE LOWER(status) IN ('pending', 'pending verification', 'verified')
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'verified' THEN 0
                    WHEN 'pending verification' THEN 1
                    WHEN 'pending' THEN 2
                    ELSE 3
                END,
                booking_date ASC, booking_time ASC
            LIMIT %s OFFSET %s
        """, (PER_PAGE, active_offset))
        active_bookings = cursor.fetchall()
    else:
        cursor.execute("""
            SELECT COUNT(*) FROM badminton_bookings 
            WHERE email = %s 
              AND LOWER(status) IN ('pending', 'pending verification', 'verified')
        """, (user_email,))
        total_active = cursor.fetchone()[0]
        total_active_pages = max(1, (total_active + PER_PAGE - 1) // PER_PAGE)

        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, 
                   duration_hours, total_amount, status, payment_proof_filename
            FROM badminton_bookings 
            WHERE email = %s 
              AND LOWER(status) IN ('pending', 'pending verification', 'verified')
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'verified' THEN 0
                    WHEN 'pending verification' THEN 1
                    WHEN 'pending' THEN 2
                    ELSE 3
                END,
                booking_date ASC, booking_time ASC
            LIMIT %s OFFSET %s
        """, (user_email, PER_PAGE, active_offset))
        active_bookings = cursor.fetchall()

        # History for users — includes Rejected (visible to users)
        cursor.execute("""
            SELECT COUNT(*) FROM past_bookings 
            WHERE email = %s
        """, (user_email,))
        total_history = cursor.fetchone()[0]
        total_history_pages = max(1, (total_history + PER_PAGE - 1) // PER_PAGE)

        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, 
                   duration_hours, total_amount, status
            FROM past_bookings 
            WHERE email = %s 
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'completed' THEN 0
                    WHEN 'rejected' THEN 1
                    WHEN 'cancelled' THEN 1
                    ELSE 2
                END,
                booking_date DESC, booking_time DESC
            LIMIT %s OFFSET %s
        """, (user_email, PER_PAGE, history_offset))
        history_bookings = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'bookings_list.html',
        active_bookings=active_bookings,
        active_page=active_page,
        total_active_pages=total_active_pages,
        history_bookings=history_bookings,
        history_page=history_page,
        total_history_pages=total_history_pages,
        is_admin=is_admin
    )


# ============================================================
# NEW RESERVATION
# ============================================================
@bookings_bp.route('/new', methods=['GET', 'POST'])
def new_booking():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT blocked_date FROM blocked_dates")
    blocked_dates_rows = cursor.fetchall()
    blocked_dates_set = set()
    for row in blocked_dates_rows:
        d = row[0]
        if hasattr(d, 'strftime'):
            blocked_dates_set.add(d.strftime('%Y-%m-%d'))
        else:
            blocked_dates_set.add(str(d))

    if request.method == 'GET':
        cursor.close()
        conn.close()
        return render_template('new_booking.html', blocked_dates=sorted(blocked_dates_set))

    user_email = session.get('user_email') or session.get('email')

    if session.get('role') == 'admin':
        customer_name = (request.form.get('customer_name') or '').strip()
        if not customer_name:
            cursor.close()
            conn.close()
            return render_template(
                'new_booking.html',
                error="Please enter the customer's name.",
                blocked_dates=sorted(blocked_dates_set)
            )
    else:
        customer_name = user_email
        if user_email:
            try:
                cursor.execute("SELECT name FROM users WHERE email = %s", (user_email,))
                user_row = cursor.fetchone()
                if user_row and user_row[0]:
                    customer_name = user_row[0]
            except Exception:
                pass

    contact = request.form.get('contact', '').strip()

    if not re.match(CONTACT_REGEX, contact):
        cursor.close()
        conn.close()
        return render_template(
            'new_booking.html',
            error="Invalid contact format. Use 0900 000 0000 or +63000 000 0000.",
            blocked_dates=sorted(blocked_dates_set)
        )

    raw_court = request.form.get('court_number', '')
    booking_date = request.form.get('booking_date')
    booking_time_str = request.form.get('booking_time')
    duration_hours_str = request.form.get('duration_hours')

    if booking_date and booking_date in blocked_dates_set:
        cursor.close()
        conn.close()
        try:
            pretty_date = datetime.strptime(booking_date, '%Y-%m-%d').strftime('%B %d, %Y')
        except ValueError:
            pretty_date = booking_date
        return render_template(
            'new_booking.html',
            error=f"Notice: Esguerra Badminton Court is not available on {pretty_date}. Please choose another date.",
            blocked_dates=sorted(blocked_dates_set)
        )

    court_digits = ''.join(filter(str.isdigit, str(raw_court)))
    court_number = int(court_digits) if court_digits else 1
    HOURLY_RATE = 150

    if contact and raw_court and booking_date and booking_time_str and duration_hours_str:
        try:
            duration_hours = int(duration_hours_str)
            total_amount = duration_hours * HOURLY_RATE

            req_start = parse_time_obj(booking_time_str)
            req_end = req_start + timedelta(hours=duration_hours)
            formatted_time_str = req_start.strftime("%H:%M:%S")

            cursor.execute("""
                SELECT booking_time, duration_hours 
                FROM badminton_bookings 
                WHERE court_number = %s AND booking_date = %s
            """, (court_number, booking_date))
            existing_bookings = cursor.fetchall()

            now = datetime.now()
            for b_time, b_duration in existing_bookings:
                b_start = parse_time_obj(b_time)
                b_end = b_start + timedelta(hours=int(b_duration))
                b_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
                if datetime.combine(b_date_obj, b_end.time()) >= now:
                    if req_start < b_end and req_end > b_start:
                        cursor.close()
                        conn.close()
                        error = f"Court {court_number} is already reserved for that time slot. Please select a different time or court."
                        return render_template('new_booking.html', error=error, blocked_dates=sorted(blocked_dates_set))

            cursor.execute("""
                INSERT INTO badminton_bookings 
                (customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending Verification')
            """, (customer_name, user_email, contact, court_number, booking_date, formatted_time_str, duration_hours, total_amount))

            booking_id = cursor.lastrowid
            cursor.close()
            conn.close()

            try:
                pretty_date = datetime.strptime(booking_date, '%Y-%m-%d').strftime('%B %d, %Y')
            except Exception:
                pretty_date = booking_date

            notify_all_admins(
                title="New Reservation Pending Payment",
                message=(
                    f"{customer_name} reserved Court {court_number} on {pretty_date} "
                    f"at {formatted_time_str[:5]} for {duration_hours} hr(s). "
                    f"Total: ₱{total_amount:.2f}. Awaiting payment proof."
                )
            )

            return redirect(url_for('bookings.booking_payment', booking_id=booking_id))

        except Exception as e:
            if cursor:
                cursor.close()
            conn.close()
            return render_template('new_booking.html', error=f"Database error: {str(e)}", blocked_dates=sorted(blocked_dates_set))

    cursor.close()
    conn.close()
    return render_template('new_booking.html', error="Please fill out all required fields.", blocked_dates=sorted(blocked_dates_set))


# ============================================================
# PAYMENT PAGE (QR + proof upload)
# ============================================================
@bookings_bp.route('/booking/payment/<int:booking_id>', methods=['GET'])
def booking_payment(booking_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, customer_name, email, contact, court_number, booking_date, booking_time,
               duration_hours, total_amount, status, payment_proof_filename
        FROM badminton_bookings
        WHERE id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    is_admin = session.get('role') == 'admin'
    is_owner = (booking[2] == session.get('user_email'))
    if not is_admin and not is_owner:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    if booking[9] not in ('Pending Verification', 'Pending'):
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    cursor.execute("""
        SELECT setting_key, setting_value FROM settings
        WHERE setting_key IN ('payment_qr_filename', 'payment_wallet_name',
                              'payment_wallet_number', 'payment_instructions')
    """)
    settings_rows = dict(cursor.fetchall())

    cursor.close()
    conn.close()

    return render_template(
        'booking_payment.html',
        booking=booking,
        qr_filename=settings_rows.get('payment_qr_filename'),
        wallet_name=settings_rows.get('payment_wallet_name') or 'GCash',
        wallet_number=settings_rows.get('payment_wallet_number') or '',
        payment_instructions=settings_rows.get('payment_instructions') or '',
    )


@bookings_bp.route('/booking/submit-payment/<int:booking_id>', methods=['POST'])
def submit_payment(booking_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, customer_name, email, court_number, booking_date, booking_time,
               duration_hours, total_amount, status, payment_proof_filename
        FROM badminton_bookings
        WHERE id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    is_admin = session.get('role') == 'admin'
    is_owner = (booking[2] == session.get('user_email'))
    if not is_admin and not is_owner:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.my_bookings'))

    proof_file = request.files.get('payment_proof')
    if not proof_file or not proof_file.filename:
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.booking_payment', booking_id=booking_id))

        print("--- STARTING CLOUDINARY UPLOAD ---")
    saved_name = _save_payment_proof(proof_file, booking_id)
    print(f"--- CLOUDINARY UPLOAD FINISHED: {saved_name} ---")
    
    if not saved_name:
        print("--- UPLOAD FAILED, REDIRECTING BACK ---")
        cursor.close()
        conn.close()
        return redirect(url_for('bookings.booking_payment', booking_id=booking_id))

    # Get the reference number from the form
    payment_reference = request.form.get('payment_reference', '').strip()

    # Save both the image and the reference number
    cursor.execute("""
        UPDATE badminton_bookings
        SET payment_proof_filename = %s,
            payment_reference = %s,
            status = 'Pending Verification'
        WHERE id = %s
    """, (saved_name, payment_reference, booking_id))

    cursor.close()
    conn.close()

    try:
        ref_text = f" Ref No: {payment_reference}." if payment_reference else ""
        notify_all_admins(
            title="Payment Proof Submitted",
            message=(
                f"{booking[1]} has uploaded payment proof for Reservation #{booking_id} "
                f"(Court {booking[3]} on {booking[4]}). Total ₱{float(booking[7]):.2f}.{ref_text} "
                f"Please review and verify."
            )
        )
    except Exception as e:
        print(f"[PAYMENT NOTIFY ERROR]: {e}")

    return redirect(url_for('bookings.payment_success', booking_id=booking_id))

@bookings_bp.route('/booking/payment-success/<int:booking_id>', methods=['GET'])
def payment_success(booking_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    return render_template('payment_success.html', booking_id=booking_id)


# ============================================================
# RECEIPT
# ============================================================
@bookings_bp.route('/receipt/<int:transaction_id>')
def view_receipt(transaction_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    rec_type = request.args.get('type', 'booking')
    conn = get_db()
    cursor = conn.cursor()
    is_admin = session.get('role') == 'admin'

    if rec_type == 'shop':
        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount, status 
            FROM shop_transactions 
            WHERE id = %s
        """, (transaction_id,))
        order = cursor.fetchone()

        customer_name = order[1] if order else "Customer"
        if order and order[1]:
            try:
                cursor.execute("SELECT name FROM users WHERE email = %s", (order[1],))
                user_row = cursor.fetchone()
                if user_row and user_row[0]:
                    customer_name = user_row[0]
            except Exception:
                pass

        cursor.close()
        conn.close()

        if not order:
            return "Receipt not found", 404

        is_owner = (order[1] == session.get('user_email'))
        if not is_admin and not is_owner:
            return "Receipt not found", 404

        transaction_data = {
            "id": order[0],
            "customer_name": customer_name,
            "contact": order[1],
            "type": "Shop Order",
            "status": order[5] or 'Pending',
            "total_amount": float(order[4]),
            "details": {
                "product_name": order[2],
                "quantity": order[3]
            }
        }

    else:
        cursor.execute("""
            SELECT id, customer_name, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status, email 
            FROM badminton_bookings 
            WHERE id = %s
        """, (transaction_id,))
        booking = cursor.fetchone()

        if not booking:
            cursor.execute("""
                SELECT id, customer_name, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status, email 
                FROM past_bookings 
                WHERE id = %s
                LIMIT 1
            """, (transaction_id,))
            booking = cursor.fetchone()

        if not booking:
            cursor.execute("""
                SELECT id, customer_name, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status, email 
                FROM past_bookings 
                WHERE original_booking_id = %s
                ORDER BY id DESC
                LIMIT 1
            """, (transaction_id,))
            booking = cursor.fetchone()

        cursor.close()
        conn.close()

        if not booking:
            return "Receipt not found", 404

        is_owner = (booking[9] == session.get('user_email'))
        if not is_admin and not is_owner:
            return "Receipt not found", 404

        transaction_data = {
            "id": booking[0],
            "customer_name": booking[1],
            "contact": booking[2],
            "type": "Court Booking",
            "status": booking[8] or 'Pending',
            "total_amount": float(booking[7]),
            "details": {
                "court_number": f"Court {booking[3]}",
                "booking_date": str(booking[4]),
                "booking_time": str(booking[5]),
                "duration": booking[6]
            }
        }

    return render_template('receipt.html', transaction=transaction_data)


# ============================================================
# API — AVAILABLE COURTS
# ============================================================
@bookings_bp.route('/api/available-courts')
def available_courts():
    booking_date = request.args.get('date')
    booking_time = request.args.get('time')
    duration_str = request.args.get('duration', '1')

    if not booking_date or not booking_time:
        return jsonify({'booked': []})

    try:
        duration = max(1, int(duration_str))
    except ValueError:
        duration = 1

    try:
        req_start = parse_time_obj(booking_time)
    except ValueError:
        return jsonify({'booked': []})

    req_end = req_start + timedelta(hours=duration)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT court_number, booking_time, duration_hours
        FROM badminton_bookings
        WHERE booking_date = %s 
          AND LOWER(status) = 'verified'
    """, (booking_date,))
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    booked_details = []
    for court_num, b_time, b_duration in rows:
        try:
            b_start = parse_time_obj(b_time)
            b_end = b_start + timedelta(hours=int(b_duration))
        except Exception as e:
            print(f"Error parsing time: {e}")
            continue

        # Check if the requested time overlaps with an existing booking
        if req_start < b_end and req_end > b_start:
            try:
                start_str = b_start.strftime('%I:%M %p').lstrip('0')
                end_str = b_end.strftime('%I:%M %p').lstrip('0')
                time_range = f"{start_str} - {end_str}"
            except AttributeError:
                time_range = f"{b_time} ({b_duration} hr)"

            booked_details.append({
                'court': int(court_num),
                'time_range': time_range
            })

    return jsonify({'booked': booked_details})