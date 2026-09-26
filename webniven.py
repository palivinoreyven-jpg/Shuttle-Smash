# 1. Imports
import random
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session
from flask_mysqldb import MySQL
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash

# 2. Application Configuration
app = Flask(__name__)
app.secret_key = 'ebc_badminton_secret_key'

# 3. Database Configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Adminven1!'
app.config['MYSQL_DB'] = 'flask_app_db'

# 4. Mail Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'palivinoreyven@gmail.com'
app.config['MAIL_PASSWORD'] = 'hdlw suub iizj rjts'
app.config['MAIL_DEFAULT_SENDER'] = 'palivinoreyven@gmail.com'

# 5. Extension Initialization
mysql = MySQL(app)
mail = Mail(app)
CONTACT_REGEX = r"^(\+63\d{3}\s\d{3}\s\d{4}|09\d{2}\s\d{3}\s\d{4})$"


# Helper: Safely calculate booking end datetime from any MySQL date/time format
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


# Helper: Universal time string parser
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


# Helper: Auto-Archive Expired Bookings to past_bookings Table
def archive_expired_bookings():
    try:
        cursor = mysql.connection.cursor()
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
            mysql.connection.commit()

        cursor.close()
    except Exception as e:
        print(f"\n[ARCHIVE FUNCTION ERROR]: {e}\n")


# 6. User Signup Route
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')

        cursor = mysql.connection.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        cursor.close()

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

            msg = Message(
                subject="EBC Badminton - Email Verification",
                recipients=[email],
                body=f"Your verification code is: {verification_code}"
            )
            try:
                mail.send(msg)
            except Exception as e:
                print(f"[MAIL ERROR]: {e}")

            return redirect(url_for('verify_email'))

    return render_template('signup.html', error=error)


# 7. Email Verification Route
@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    error = None
    pending_user = session.get('pending_user')

    if not pending_user:
        return redirect(url_for('signup'))

    if request.method == 'POST':
        entered_code = request.form.get('code')

        if entered_code == pending_user['code']:
            cursor = mysql.connection.cursor()
            hashed_password = generate_password_hash(pending_user['password'])
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (pending_user['name'], pending_user['email'], hashed_password, 'user')
            )
            mysql.connection.commit()
            cursor.close()

            session.pop('pending_user', None)
            return redirect(url_for('login'))
        else:
            error = 'Invalid verification code. Please try again.'

    return render_template('verify_email.html', error=error, email=pending_user['email'])


# 8. User Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user_input = request.form.get('email') or request.form.get('username')
        password = request.form.get('password')

        # Admin Hardcoded Fallback
        if user_input == 'ryokuniven@gmail.com' and password == 'Adminven1!':
            session['logged_in'] = True
            session['user_email'] = 'Admin'
            session['role'] = 'admin'
            return redirect(url_for('index'))

        cursor = mysql.connection.cursor()
        cursor.execute(
            "SELECT id, email, password_hash, role FROM users WHERE email = %s",
            (user_input,)
        )
        user = cursor.fetchone()
        cursor.close()

        # Secure check with fallback for legacy plain text passwords
        if user and (check_password_hash(user[2], password) or user[2] == password):
            session['logged_in'] = True
            session['user_email'] = user[1]
            session['role'] = user[3]
            return redirect(url_for('index'))
        else:
            error = 'Invalid Email/Username or Password!'

    return render_template('login.html', error=error)


# 9. User Logout Route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# 10. Dashboard Route (Index)
@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    archive_expired_bookings()

    cursor = mysql.connection.cursor()
    chart_data = None
    user_email = session.get('user_email')

    if session.get('role') == 'admin':
        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status 
            FROM badminton_bookings 
            ORDER BY booking_date ASC, booking_time ASC
        """)
        bookings = cursor.fetchall()

        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status 
            FROM past_bookings 
            ORDER BY booking_date DESC, booking_time DESC
        """)
        history_bookings = cursor.fetchall()

        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount, transaction_date 
            FROM shop_transactions 
            ORDER BY transaction_date DESC
        """)
        shop_transactions = cursor.fetchall()

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

    else:
        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status 
            FROM badminton_bookings 
            WHERE LOWER(status) = 'verified' 
            ORDER BY booking_date ASC, booking_time ASC
        """)
        bookings = cursor.fetchall()

        cursor.execute("""
            SELECT id, customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status 
            FROM past_bookings 
            WHERE email = %s 
            ORDER BY booking_date DESC, booking_time DESC
        """, (user_email,))
        history_bookings = cursor.fetchall()

        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount, transaction_date 
            FROM shop_transactions 
            WHERE user_email = %s
            ORDER BY transaction_date DESC
        """, (user_email,))
        shop_transactions = cursor.fetchall()

    cursor.close()
    return render_template(
        'index.html', 
        bookings=bookings, 
        history_bookings=history_bookings, 
        shop_transactions=shop_transactions,
        chart_data=chart_data
    )


# 11. Admin Verify Booking Route
@app.route('/verify/<int:booking_id>', methods=['POST'])
def verify_booking(booking_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor()
    cursor.execute("UPDATE badminton_bookings SET status = 'Verified' WHERE id = %s", (booking_id,))
    mysql.connection.commit()
    cursor.close()
    return redirect(url_for('index'))


# 12. New Booking Page Route
@app.route('/new')
def new_booking_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('new_booking.html')


# 13. Process Court Booking Route
@app.route('/book', methods=['POST'])
def book_court():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    user_email = session.get('user_email') or session.get('email')

    cursor = mysql.connection.cursor()
    
    customer_name = user_email
    if user_email:
        try:
            cursor.execute("SELECT name FROM users WHERE email = %s", (user_email,))
            user_row = cursor.fetchone()
            if user_row and user_row[0]:
                customer_name = user_row[0]
        except Exception:
            mysql.connection.rollback()

    contact = request.form.get('contact', '').strip()
    
    if not re.match(CONTACT_REGEX, contact):
        return render_template('book.html', error="Invalid contact format. Use 0900 000 0000 or +63000 000 0000.")
    
    raw_court = request.form.get('court_number', '')
    booking_date = request.form.get('booking_date')
    booking_time_str = request.form.get('booking_time')
    duration_hours_str = request.form.get('duration_hours')

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
                        error = f"Court {court_number} is already booked for that time slot. Please select a different time or court."
                        return render_template('new_booking.html', error=error)

            # Insert booking record into MySQL
            cursor.execute("""
                INSERT INTO badminton_bookings 
                (customer_name, email, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending')
            """, (customer_name, user_email, contact, court_number, booking_date, formatted_time_str, duration_hours, total_amount))

            mysql.connection.commit()

            # Retrieve the newly generated primary key (ID) for the receipt
            booking_id = cursor.lastrowid
            cursor.close()

            # Redirect to the dedicated receipt route
            return redirect(url_for('view_receipt', transaction_id=booking_id))

        except Exception as e:
            if 'cursor' in locals() and cursor:
                cursor.close()
            return render_template('new_booking.html', error=f"Database error: {str(e)}")

    return render_template('new_booking.html', error="Please fill out all required fields.")


# -------------------------------------------------------------
# ADD THIS RECEIPT ROUTE RIGHT BELOW YOUR BOOKING ROUTE
# -------------------------------------------------------------
@app.route('/receipt/<int:transaction_id>')
def view_receipt(transaction_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    # Read transaction type from URL parameter (defaults to 'booking')
    rec_type = request.args.get('type', 'booking')
    cursor = mysql.connection.cursor()

    if rec_type == 'shop':
        # Fetch shop order from shop_transactions table
        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount 
            FROM shop_transactions 
            WHERE id = %s
        """, (transaction_id,))
        order = cursor.fetchone()
        cursor.close()

        if not order:
            return "Receipt not found", 404

        transaction_data = {
            "id": order[0],
            "customer_name": order[1],
            "contact": order[1],  # Uses user email
            "type": "Shop Order",
            "total_amount": float(order[4]),
            "details": {
                "product_name": order[2],
                "quantity": order[3]
            }
        }

    else:
        # Fetch court booking from badminton_bookings table
        cursor.execute("""
            SELECT id, customer_name, contact, court_number, booking_date, booking_time, duration_hours, total_amount, status 
            FROM badminton_bookings 
            WHERE id = %s
        """, (transaction_id,))
        booking = cursor.fetchone()
        cursor.close()

        if not booking:
            return "Receipt not found", 404

        transaction_data = {
            "id": booking[0],
            "customer_name": booking[1],
            "contact": booking[2],
            "type": "Court Booking",
            "total_amount": float(booking[7]),
            "details": {
                "court_number": f"Court {booking[3]}",
                "booking_date": str(booking[4]),
                "booking_time": str(booking[5]),
                "duration": booking[6]
            }
        }

    return render_template('receipt.html', transaction=transaction_data)
# 14. Delete Booking Route
@app.route('/delete/<int:booking_id>', methods=['POST'])
def delete_booking(booking_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM badminton_bookings WHERE id = %s", (booking_id,))
    mysql.connection.commit()
    cursor.close()
    return redirect(url_for('index'))


# 15. Pro Shop View Route
@app.route('/shop')
def shop():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    selected_category = request.args.get('category', 'All')

    cursor = mysql.connection.cursor()

    cursor.execute("""
        SELECT DISTINCT category 
        FROM products 
        WHERE category IS NOT NULL AND category != '' 
        ORDER BY category
    """)
    categories_tuples = cursor.fetchall()
    categories = [cat[0] for cat in categories_tuples]

    if selected_category and selected_category != 'All':
        cursor.execute("""
            SELECT p.id, p.name, p.category, p.price, ps.stock, p.description 
            FROM products p 
            JOIN product_stocks ps ON p.id = ps.product_id 
            WHERE p.category = %s
            ORDER BY p.name
        """, (selected_category,))
    else:
        cursor.execute("""
            SELECT p.id, p.name, p.category, p.price, ps.stock, p.description 
            FROM products p 
            JOIN product_stocks ps ON p.id = ps.product_id 
            ORDER BY p.category, p.name
        """)

    products = cursor.fetchall()
    cursor.close()

    return render_template(
        'shop.html', 
        products=products, 
        categories=categories, 
        selected_category=selected_category
    )


# 16. Add Item to Cart Route
@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']
    prod_id_str = str(product_id)

    try:
        qty_to_add = int(request.form.get('quantity', 1))
    except ValueError:
        qty_to_add = 1

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT stock FROM product_stocks WHERE product_id = %s", (product_id,))
    item = cursor.fetchone()
    cursor.close()

    if item:
        stock = item[0]
        current_in_cart = cart.get(prod_id_str, 0)

        if current_in_cart + qty_to_add <= stock:
            cart[prod_id_str] = current_in_cart + qty_to_add
        else:
            cart[prod_id_str] = stock

        session.modified = True

    return redirect(url_for('shop'))


# 17. View Cart Route
@app.route('/cart')
def view_cart():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    cart = session.get('cart', {})
    cart_items = []
    total_price = 0.0

    if cart:
        cursor = mysql.connection.cursor()
        format_strings = ','.join(['%s'] * len(cart))
        cursor.execute(f"""
            SELECT p.id, p.name, p.price, ps.stock 
            FROM products p 
            JOIN product_stocks ps ON p.id = ps.product_id 
            WHERE p.id IN ({format_strings})
        """, tuple(cart.keys()))
        products = cursor.fetchall()
        cursor.close()

        for p in products:
            p_id = str(p[0])
            qty = cart.get(p_id, 0)
            subtotal = float(p[2]) * qty
            total_price += subtotal
            cart_items.append({
                'id': p[0],
                'name': p[1],
                'price': float(p[2]),
                'stock': p[3],
                'quantity': qty,
                'subtotal': subtotal
            })

    return render_template('cart.html', cart_items=cart_items, total_price=total_price)


# 18. Remove Item from Cart Route
@app.route('/remove_from_cart/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    cart = session.get('cart', {})
    prod_id_str = str(product_id)

    if prod_id_str in cart:
        del cart[prod_id_str]
        session.modified = True

    return redirect(url_for('view_cart'))


# 19. Checkout Route
@app.route('/checkout', methods=['POST'])
def checkout():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    cart = session.get('cart', {})
    if not cart:
        return redirect(url_for('shop'))

    user_email = session.get('user_email', 'Unknown User')
    cursor = mysql.connection.cursor()

    last_transaction_id = None

    for prod_id, qty in cart.items():
        cursor.execute("SELECT name, price FROM products WHERE id = %s", (prod_id,))
        prod = cursor.fetchone()

        cursor.execute("SELECT stock FROM product_stocks WHERE product_id = %s", (prod_id,))
        stock_item = cursor.fetchone()

        if prod and stock_item and stock_item[0] >= qty:
            p_name = prod[0]
            p_price = float(prod[1])
            subtotal = p_price * qty

            cursor.execute("UPDATE product_stocks SET stock = stock - %s WHERE product_id = %s", (qty, prod_id))

            cursor.execute("""
                INSERT INTO shop_transactions (user_email, product_name, quantity, total_amount)
                VALUES (%s, %s, %s, %s)
            """, (user_email, p_name, qty, subtotal))

            # Store the last created transaction ID to view on receipt
            last_transaction_id = cursor.lastrowid

    mysql.connection.commit()
    cursor.close()

    session['cart'] = {}
    session.modified = True

    # Redirect to receipt route with a query parameter type='shop'
    if last_transaction_id:
        return redirect(url_for('view_receipt', transaction_id=last_transaction_id, type='shop'))

    return redirect(url_for('shop'))




# 20. Admin Inventory Page Route
@app.route('/admin/stocks')
def admin_stocks():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT p.id, p.name, p.category, p.price, ps.stock, p.description 
        FROM products p 
        JOIN product_stocks ps ON p.id = ps.product_id 
        ORDER BY p.category, p.name
    """)
    products = cursor.fetchall()
    cursor.close()

    return render_template('admin_stocks.html', products=products)


# 21. Add New Product Route
@app.route('/add_product', methods=['POST'])
def add_product():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    name = request.form.get('name')
    category = request.form.get('category')
    price = request.form.get('price')
    stock = request.form.get('stock')
    description = request.form.get('description')

    if name and category and price and stock:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            INSERT INTO products (name, category, price, description)
            VALUES (%s, %s, %s, %s)
        """, (name, category, float(price), description))

        product_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO product_stocks (product_id, stock)
            VALUES (%s, %s)
        """, (product_id, int(stock)))

        mysql.connection.commit()
        cursor.close()

    return redirect(url_for('admin_stocks'))


# 22. Update Product Route
@app.route('/update_product/<int:product_id>', methods=['POST'])
def update_product(product_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    name = request.form.get('name')
    price = request.form.get('price')
    description = request.form.get('description')

    if name and price:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE products 
            SET name = %s, price = %s, description = %s 
            WHERE id = %s
        """, (name, float(price), description, product_id))

        mysql.connection.commit()
        cursor.close()

    return redirect(url_for('admin_stocks'))


# 23. Restock Product Route
@app.route('/restock/<int:product_id>', methods=['POST'])
def restock_product(product_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    additional_stock = request.form.get('additional_stock')

    if additional_stock and int(additional_stock) > 0:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE product_stocks 
            SET stock = stock + %s 
            WHERE product_id = %s
        """, (int(additional_stock), product_id))
        mysql.connection.commit()
        cursor.close()

    return redirect(url_for('admin_stocks'))


# 24. Route to Remove Product (Zero Stock Only)
@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor()
    try:
        cursor.execute("SELECT stock FROM product_stocks WHERE product_id = %s", (product_id,))
        stock_item = cursor.fetchone()

        if stock_item and stock_item[0] == 0:
            cursor.execute("DELETE FROM product_stocks WHERE product_id = %s", (product_id,))
            cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
            mysql.connection.commit()
            cursor.close()
            return redirect(url_for('admin_stocks'))
        else:
            cursor.close()
            return redirect(url_for('admin_stocks'))

    except Exception as e:
        mysql.connection.rollback()
        if 'cursor' in locals() and cursor:
            cursor.close()
        return redirect(url_for('admin_stocks'))


# 25. Helper & Routes for Password Recovery / Data Cleanup
def archive_one_month_old_records():
    try:
        cursor = mysql.connection.cursor()

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

        mysql.connection.commit()
        cursor.close()
    except Exception as e:
        print(f"\n[ONE-MONTH CLEANUP ERROR]: {e}\n")


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    error = None
    if request.method == 'POST':
        email = request.form.get('email')
        
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()

        if not user:
            error = "No account found with that email address."
            return render_template('forgot_password.html', error=error)

        reset_otp = str(random.randint(100000, 999999))
        session['reset_password_data'] = {
            'email': email,
            'otp': reset_otp
        }

        msg = Message(
            subject="EBC Badminton - Password Reset Code",
            recipients=[email],
            body=f"Your password reset code is: {reset_otp}\n\nIf you did not request this, please ignore this email."
        )
        try:
            mail.send(msg)
            print(f"\n[SUCCESS] OTP {reset_otp} sent to {email}\n")
        except Exception as e:
            print(f"\n[MAIL ERROR]: {e}\n")

        return redirect(url_for('reset_password'))

    return render_template('forgot_password.html', error=error)


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    error = None
    reset_data = session.get('reset_password_data')

    if not reset_data or 'email' not in reset_data:
        return redirect(url_for('forgot_password'))

    email = reset_data['email']

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        new_pass = request.form.get('new_password')
        confirm_pass = request.form.get('confirm_password')

        if user_otp != reset_data.get('otp'):
            error = "Invalid verification code."
        elif new_pass != confirm_pass:
            error = "Passwords do not match."
        else:
            hashed_password = generate_password_hash(new_pass)
            cursor = mysql.connection.cursor()
            cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s", (hashed_password, email))
            mysql.connection.commit()
            cursor.close()

            session.pop('reset_password_data', None)
            return redirect(url_for('login'))

    return render_template('reset_password.html', error=error, email=email)


# 26. Main Entry Point
if __name__ == '__main__':
    app.run(debug=True)