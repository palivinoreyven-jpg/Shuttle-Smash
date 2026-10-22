import os
from dotenv import load_dotenv
from flask import Flask
from extensions import mail
from helpers import get_booking_end_dt
from routes.auth import auth_bp
from routes.bookings import bookings_bp
from routes.shop import shop_bp
from routes.admin import admin_bp

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'ebc_badminton_secret_key')

# ============================================================
# Mail Config
# ============================================================
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 465))
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

# ============================================================
# Upload Config — max 7 MB per file
# ============================================================
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

# Initialize Mail
mail.init_app(app)

# ============================================================
# Inject utility functions into Jinja2 templates
# ============================================================
@app.context_processor
def utility_processor():
    return dict(get_booking_end_dt=get_booking_end_dt)

# ============================================================
# Register Modular Routes
# ============================================================
app.register_blueprint(auth_bp)
app.register_blueprint(bookings_bp)
app.register_blueprint(shop_bp)
app.register_blueprint(admin_bp)

if __name__ == '__main__':
    app.run(debug=True)