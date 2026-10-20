from dotenv import load_dotenv
load_dotenv()  # loads .env

from db import get_db
from werkzeug.security import generate_password_hash

conn = get_db()
cursor = conn.cursor()

cursor.execute("DELETE FROM users WHERE email = %s", ('ryokuniven@gmail.com',))
hashed = generate_password_hash('Adminven1!')
cursor.execute("""
    INSERT INTO users (name, email, password_hash, role)
    VALUES (%s, %s, %s, 'admin')
""", ('Admin', 'ryokuniven@gmail.com', hashed))

cursor.execute("SELECT id, email, role FROM users WHERE role = 'admin'")
print("Admin rows:", cursor.fetchall())

cursor.close()
conn.close()