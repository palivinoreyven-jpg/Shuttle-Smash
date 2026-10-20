import os
import pymysql

def get_db():
    # Check if we are running locally or in the cloud
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
            ssl={'ssl': {}}  # This is the magic line that allows TiDB to accept the connection
        )