import os
import mysql.connector

def get_db():
    db_mode = os.getenv('DB_MODE', 'local')
    
    if db_mode == 'local':
        return mysql.connector.connect(
            host=os.getenv('LOCAL_DB_HOST', '127.0.0.1'),
            port=int(os.getenv('LOCAL_DB_PORT', 3306)),
            user=os.getenv('LOCAL_DB_USER', 'root'),
            password=os.getenv('LOCAL_DB_PASSWORD', ''),
            database=os.getenv('LOCAL_DB_NAME', 'flask_app_db'),
            autocommit=True
        )
    else:
        return mysql.connector.connect(
            host=os.getenv('CLOUD_DB_HOST'),
            port=int(os.getenv('CLOUD_DB_PORT', 4000)),
            user=os.getenv('CLOUD_DB_USER'),
            password=os.getenv('CLOUD_DB_PASSWORD'),
            database=os.getenv('CLOUD_DB_NAME'),
            autocommit=True,
            ssl_disabled=False  # TiDB requires SSL
        )