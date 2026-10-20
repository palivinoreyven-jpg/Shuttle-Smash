from datetime import datetime, timedelta
from db import get_db

CONTACT_REGEX = r"^(\+63\d{3}\s\d{3}\s\d{4}|09\d{2}\s\d{3}\s\d{4})$"


def parse_time_obj(t_val):
    if isinstance(t_val, timedelta):
        return datetime.min + t_val
    if hasattr(t_val, 'hour') and not isinstance(t_val, datetime):
        return datetime.combine(datetime.min, t_val)

    t_str = str(t_val).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(t_str, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unrecognized time format: {t_str}")


def get_booking_end_dt(b_date, b_time, duration):
    if isinstance(b_date, datetime):
        dt_date = b_date.date()
    elif hasattr(b_date, 'year'):
        dt_date = b_date
    else:
        dt_date = datetime.strptime(str(b_date), '%Y-%m-%d').date()

    if isinstance(b_time, timedelta):
        total_seconds = int(b_time.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        dt_time = datetime.min.time().replace(hour=hours, minute=minutes, second=seconds)
    elif hasattr(b_time, 'hour') and not isinstance(b_time, datetime):
        dt_time = b_time
    else:
        t_str = str(b_time).strip()
        parsed_t = None
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                parsed_t = datetime.strptime(t_str, fmt).time()
                break
            except ValueError:
                pass
        dt_time = parsed_t if parsed_t else datetime.min.time()

    start_dt = datetime.combine(dt_date, dt_time)
    try:
        dur = int(duration)
    except (ValueError, TypeError):
        dur = 1
    return start_dt + timedelta(hours=dur)


def archive_expired_bookings():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status 
            FROM badminton_bookings
        """)
        all_bookings = cursor.fetchall()
        now = datetime.now()

        expired_ids = []
        for b in all_bookings:
            end_dt = get_booking_end_dt(b[5], b[6], b[7])
            if end_dt < now:
                cursor.execute("""
                    INSERT INTO past_bookings 
                    (original_booking_id, customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Completed')
                """, (b[0], b[1], b[2], b[3], b[4], b[5], str(b[6]), b[7], b[8]))
                expired_ids.append(b[0])

        if expired_ids:
            format_strings = ','.join(['%s'] * len(expired_ids))
            cursor.execute(f"DELETE FROM badminton_bookings WHERE id IN ({format_strings})", tuple(expired_ids))

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"\n[ARCHIVE FUNCTION ERROR]: {e}\n")


def archive_one_month_old_records():
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO deleted_records (record_type, original_id, user_email, customer_name, details, total_amount, record_date)
            SELECT 'Booking', id, email, customer_name, CONCAT('Court ', court_number, ' Booking'), total_amount, booking_date
            FROM past_bookings
            WHERE booking_date < DATE_SUB(NOW(), INTERVAL 1 MONTH)
        """)
        cursor.execute("DELETE FROM past_bookings WHERE booking_date < DATE_SUB(NOW(), INTERVAL 1 MONTH)")

        cursor.execute("""
            INSERT INTO deleted_records (record_type, original_id, user_email, customer_name, details, total_amount, record_date)
            SELECT 'Shop Transaction', id, user_email, user_email, CONCAT('Product: ', product_name, ' (Qty: ', quantity, ')'), total_amount, transaction_date
            FROM shop_transactions
            WHERE transaction_date < DATE_SUB(NOW(), INTERVAL 1 MONTH)
        """)
        cursor.execute("DELETE FROM shop_transactions WHERE transaction_date < DATE_SUB(NOW(), INTERVAL 1 MONTH)")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"\n[ONE-MONTH CLEANUP ERROR]: {e}\n")


# ============================================================
# NOTIFICATIONS
# ============================================================
def create_notification(user_email, title, message):
    """Insert a single notification row for a user."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO notifications (user_email, title, message)
            VALUES (%s, %s, %s)
        """, (user_email, title, message))
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[CREATE NOTIFICATION ERROR]: {e}")


def notify_all_admins(title, message):
    """Send a notification to every user with role='admin'."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM users WHERE role = 'admin'")
        admin_emails = [row[0] for row in cursor.fetchall() if row[0]]

        if admin_emails:
            values = [(email, title, message) for email in admin_emails]
            cursor.executemany("""
                INSERT INTO notifications (user_email, title, message)
                VALUES (%s, %s, %s)
            """, values)

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[NOTIFY ADMINS ERROR]: {e}")


def broadcast_notification(title, message, only_emails=None):
    """
    Send a notification to:
      - all users, if only_emails is None
      - only the given list of emails, if provided
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        if only_emails is None:
            cursor.execute("SELECT email FROM users")
            recipients = [row[0] for row in cursor.fetchall() if row[0]]
        else:
            recipients = [e for e in only_emails if e]

        if recipients:
            values = [(email, title, message) for email in recipients]
            cursor.executemany("""
                INSERT INTO notifications (user_email, title, message)
                VALUES (%s, %s, %s)
            """, values)

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[BROADCAST NOTIFICATION ERROR]: {e}")