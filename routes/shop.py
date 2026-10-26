import os
from flask import Blueprint, render_template, request, redirect, url_for, session
from db import get_db
from helpers import notify_all_admins, create_notification
from extensions import cache
import cloudinary
import cloudinary.uploader

shop_bp = Blueprint('shop', __name__)

PER_PAGE = 5

# ============================================================
# CLOUDINARY CONFIG
# ============================================================
cloudinary.config( 
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'), 
  api_key = os.getenv('CLOUDINARY_API_KEY'), 
  api_secret = os.getenv('CLOUDINARY_API_SECRET') 
)


@shop_bp.route('/shop')
@cache.cached(timeout=120, query_string=True)
def shop():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    selected_category = request.args.get('category', 'All')

    conn = get_db()
    cursor = conn.cursor()

    # Categories — only active products
    cursor.execute("""
        SELECT DISTINCT category 
        FROM products 
        WHERE category IS NOT NULL AND category != '' AND is_active = 1
        ORDER BY category
    """)
    categories_tuples = cursor.fetchall()
    categories = [cat[0] for cat in categories_tuples]

    # Product listing
    if selected_category and selected_category != 'All':
        cursor.execute("""
            SELECT p.id, p.name, p.category, p.price, ps.stock, p.description, p.image_filename
            FROM products p 
            JOIN product_stocks ps ON p.id = ps.product_id 
            WHERE p.category = %s AND p.is_active = 1
            ORDER BY p.name
        """, (selected_category,))
    else:
        cursor.execute("""
            SELECT p.id, p.name, p.category, p.price, ps.stock, p.description, p.image_filename
            FROM products p 
            JOIN product_stocks ps ON p.id = ps.product_id 
            WHERE p.is_active = 1
            ORDER BY p.category, p.name
        """)

    products = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template(
        'shop.html', 
        products=products, 
        categories=categories, 
        selected_category=selected_category
    )


@shop_bp.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']
    prod_id_str = str(product_id)

    try:
        qty_to_add = int(request.form.get('quantity', 1))
    except ValueError:
        qty_to_add = 1

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT stock FROM product_stocks WHERE product_id = %s", (product_id,))
    item = cursor.fetchone()
    cursor.close()
    conn.close()

    if item:
        stock = item[0]
        current_in_cart = cart.get(prod_id_str, 0)

        if current_in_cart + qty_to_add <= stock:
            cart[prod_id_str] = current_in_cart + qty_to_add
        else:
            cart[prod_id_str] = stock

        session.modified = True

    return redirect(url_for('shop.shop'))


@shop_bp.route('/cart')
def view_cart():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    cart = session.get('cart', {})
    cart_items = []
    total_price = 0.0

    if cart:
        conn = get_db()
        cursor = conn.cursor()
        format_strings = ','.join(['%s'] * len(cart))
        cursor.execute(f"""
            SELECT p.id, p.name, p.price, ps.stock 
            FROM products p 
            JOIN product_stocks ps ON p.id = ps.product_id 
            WHERE p.id IN ({format_strings})
        """, tuple(cart.keys()))
        products = cursor.fetchall()
        cursor.close()
        conn.close()

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


@shop_bp.route('/remove_from_cart/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    cart = session.get('cart', {})
    prod_id_str = str(product_id)

    if prod_id_str in cart:
        del cart[prod_id_str]
        session.modified = True

    return redirect(url_for('shop.view_cart'))


@shop_bp.route('/checkout', methods=['POST'])
def checkout():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    cart = session.get('cart', {})
    if not cart:
        return redirect(url_for('shop.shop'))

    user_email = session.get('user_email', 'Unknown User')
    conn = get_db()
    cursor = conn.cursor()

    last_transaction_id = None
    order_items = []

    for prod_id, qty in cart.items():
        cursor.execute("SELECT name, price FROM products WHERE id = %s", (prod_id,))
        prod = cursor.fetchone()

        cursor.execute("SELECT stock FROM product_stocks WHERE product_id = %s", (prod_id,))
        stock_item = cursor.fetchone()

        if prod and stock_item and stock_item[0] >= qty:
            p_name = prod[0]
            p_price = float(prod[1])
            subtotal = p_price * qty

            cursor.execute("""
                INSERT INTO shop_transactions 
                (user_email, product_name, quantity, total_amount, status)
                VALUES (%s, %s, %s, %s, 'Pending')
            """, (user_email, p_name, qty, subtotal))

            last_transaction_id = cursor.lastrowid
            order_items.append({'name': p_name, 'qty': qty, 'subtotal': subtotal})

    cursor.close()
    conn.close()

    if last_transaction_id:
        # Clear the cart
        session['cart'] = {}
        session.modified = True
        cache.clear()
        
        # Redirect to the new payment page instead of directly to my_orders
        return redirect(url_for('shop.shop_payment', order_id=last_transaction_id))

    return redirect(url_for('shop.shop'))


@shop_bp.route('/shop/payment/<int:order_id>', methods=['GET'])
def shop_payment(order_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_email, product_name, quantity, total_amount, status 
        FROM shop_transactions WHERE id = %s
    """, (order_id,))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.my_orders'))

    # Get the admin's QR code settings
    cursor.execute("""
        SELECT setting_key, setting_value FROM settings
        WHERE setting_key IN ('payment_qr_filename', 'payment_wallet_name',
                              'payment_wallet_number', 'payment_instructions')
    """)
    settings_rows = dict(cursor.fetchall())

    cursor.close()
    conn.close()

    return render_template(
        'shop_payment.html',
        order=order,
        qr_filename=settings_rows.get('payment_qr_filename'),
        wallet_name=settings_rows.get('payment_wallet_name') or 'GCash',
        wallet_number=settings_rows.get('payment_wallet_number') or '',
        payment_instructions=settings_rows.get('payment_instructions') or '',
    )


@shop_bp.route('/shop/submit-payment/<int:order_id>', methods=['POST'])
def shop_submit_payment(order_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, user_email, product_name, quantity, total_amount FROM shop_transactions WHERE id = %s", (order_id,))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.my_orders'))

    # Handle Cloudinary Upload
    proof_file = request.files.get('payment_proof')
    if not proof_file or not proof_file.filename:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.shop_payment', order_id=order_id))

    try:
        upload_result = cloudinary.uploader.upload(
            proof_file,
            folder="shop_proofs",
            public_id=f"shop_proof_{order_id}",
            quality="auto",
            fetch_format="auto"
        )
        saved_url = upload_result.get("secure_url")
    except Exception as e:
        print(f"[CLOUDINARY ERROR]: {e}")
        saved_url = None

    if not saved_url:
        cursor.close()
        conn.close()
        return redirect(url_for('shop.shop_payment', order_id=order_id))

    payment_reference = request.form.get('payment_reference', '').strip()

    cursor.execute("""
        UPDATE shop_transactions
        SET payment_proof_filename = %s,
            payment_reference = %s
        WHERE id = %s
    """, (saved_url, payment_reference, order_id))

    cursor.close()
    conn.close()
    cache.clear()

    try:
        ref_text = f" Ref No: {payment_reference}." if payment_reference else ""
        notify_all_admins(
            title="Shop Payment Proof Submitted",
            message=(
                f"{order[1]} uploaded payment for Order #{order_id} ({order[2]}). "
                f"Total ₱{float(order[4]):.2f}.{ref_text} Please verify."
            )
        )
    except Exception as e:
        print(f"[NOTIFY ERROR]: {e}")

    return redirect(url_for('shop.my_orders'))


@shop_bp.route('/shop/orders')
@cache.cached(timeout=60, query_string=True, key_prefix=lambda: f"my_orders_{session.get('user_email')}")
def my_orders():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    user_email = session.get('user_email')
    is_admin = session.get('role') == 'admin'

    active_page = max(1, int(request.args.get('mo_active_page', 1)))
    history_page = max(1, int(request.args.get('mo_history_page', 1)))
    active_offset = (active_page - 1) * PER_PAGE
    history_offset = (history_page - 1) * PER_PAGE

    conn = get_db()
    cursor = conn.cursor()

    # ---- Active ----
    if is_admin:
        cursor.execute("""
            SELECT COUNT(*) FROM shop_transactions 
            WHERE status IN ('Pending', 'Verified', 'Shipped')
        """)
    else:
        cursor.execute("""
            SELECT COUNT(*) FROM shop_transactions 
            WHERE user_email = %s AND status IN ('Pending', 'Verified', 'Shipped')
        """, (user_email,))
    total_active = cursor.fetchone()[0]
    total_active_pages = max(1, (total_active + PER_PAGE - 1) // PER_PAGE)

    if is_admin:
        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount, transaction_date, status, payment_proof_filename, payment_reference
            FROM shop_transactions
            WHERE status IN ('Pending', 'Verified', 'Shipped')
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'shipped' THEN 0
                    WHEN 'verified' THEN 1
                    WHEN 'pending' THEN 2
                    ELSE 3
                END,
                transaction_date DESC
            LIMIT %s OFFSET %s
        """, (PER_PAGE, active_offset))
    else:
        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount, transaction_date, status, payment_proof_filename, payment_reference
            FROM shop_transactions
            WHERE user_email = %s AND status IN ('Pending', 'Verified', 'Shipped')
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'shipped' THEN 0
                    WHEN 'verified' THEN 1
                    WHEN 'pending' THEN 2
                    ELSE 3
                END,
                transaction_date DESC
            LIMIT %s OFFSET %s
        """, (user_email, PER_PAGE, active_offset))
    active_orders = cursor.fetchall()

    # ---- History (users only) ----
    history_orders = []
    total_history_pages = 1

    if not is_admin:
        cursor.execute("""
            SELECT COUNT(*) FROM shop_transactions 
            WHERE user_email = %s AND status IN ('Completed', 'Rejected')
        """, (user_email,))
        total_history = cursor.fetchone()[0]
        total_history_pages = max(1, (total_history + PER_PAGE - 1) // PER_PAGE)

        cursor.execute("""
            SELECT id, user_email, product_name, quantity, total_amount, transaction_date, status
            FROM shop_transactions
            WHERE user_email = %s AND status IN ('Completed', 'Rejected')
            ORDER BY 
                CASE LOWER(status)
                    WHEN 'completed' THEN 0
                    WHEN 'rejected' THEN 1
                    ELSE 2
                END,
                transaction_date DESC
            LIMIT %s OFFSET %s
        """, (user_email, PER_PAGE, history_offset))
        history_orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'shop_orders_list.html',
        active_orders=active_orders,
        active_page=active_page,
        total_active_pages=total_active_pages,
        history_orders=history_orders,
        history_page=history_page,
        total_history_pages=total_history_pages,
        is_admin=is_admin
    )