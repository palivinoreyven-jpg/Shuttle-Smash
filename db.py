import os
import socket
import pymysql

def get_db():
    # Force IPv4 resolution to avoid Vercel's "Device or resource busy" error
    original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = lambda host, port, family=0, type=0, proto=0, flags=0: original_getaddrinfo(
        host, port, socket.AF_INET, type, proto, flags
    )

    db_mode = os.getenv('DB_MODE', 'local')
    
    if db_mode == 'local':
        return pymysql.connect(
            host=os.getenv('LOCAL_DB_HOST', '127.0.0.1'),
            port=int(os.getenv('LOCAL_DB_PORT', 3306)),
            user=os.getenv('LOCAL_DB_USER', 'root'),
            password=os.getenv('LOCAL_DB_PASSWORD', ''),
            database=os.getenv('LOCAL_DB_NAME', 'flask_app_db'),
            autocommit=True
        )
    else:
        # TiDB Cloud Connection (Requires SSL)
        return pymysql.connect(
            host=os.getenv('CLOUD_DB_HOST'),
            port=int(os.getenv('CLOUD_DB_PORT', 4000)),
            user=os.getenv('CLOUD_DB_USER'),
            password=os.getenv('CLOUD_DB_PASSWORD'),
            database=os.getenv('CLOUD_DB_NAME'),
            autocommit=True,
            ssl={'ssl': {}} 
        )