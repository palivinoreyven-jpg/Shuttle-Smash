import os
import pymysql

def get_db():
    return pymysql.connect(
        host=os.getenv('LOCAL_DB_HOST') or os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('LOCAL_DB_PORT') or os.getenv('DB_PORT', 3306)),
        user=os.getenv('LOCAL_DB_USER') or os.getenv('DB_USER', 'root'),
        password=os.getenv('LOCAL_DB_PASSWORD') or os.getenv('DB_PASSWORD', ''),
        database=os.getenv('LOCAL_DB_NAME') or os.getenv('DB_NAME', 'flask_app_db'),
        autocommit=True
    )