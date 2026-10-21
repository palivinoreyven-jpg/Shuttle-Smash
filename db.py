import os
import mysql.connector
import dns.resolver

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
        # 1. Manually resolve the TiDB hostname using Google DNS
        host = os.getenv('CLOUD_DB_HOST')
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = ['8.8.8.8', '8.8.4.4']
        resolver.timeout = 2.0
        resolver.lifetime = 2.0
        
        try:
            # Get the IP address (A record)
            answers = resolver.resolve(host, 'A')
            resolved_ip = str(answers[0])
        except Exception as e:
            print(f"DNS Resolution failed: {e}")
            resolved_ip = host # Fallback to original host if it fails

        # 2. Connect to the resolved IP directly
        return mysql.connector.connect(
            host=resolved_ip,
            port=int(os.getenv('CLOUD_DB_PORT', 4000)),
            user=os.getenv('CLOUD_DB_USER'),
            password=os.getenv('CLOUD_DB_PASSWORD'),
            database=os.getenv('CLOUD_DB_NAME'),
            autocommit=True,
            ssl_disabled=False  # TiDB requires SSL
        )