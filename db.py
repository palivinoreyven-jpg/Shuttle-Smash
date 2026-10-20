import os
import pymysql
import socket
import dns.resolver

def get_db():
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
        # Force DNS resolution using Google DNS to bypass Vercel issues
        host = os.getenv('CLOUD_DB_HOST')
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = ['8.8.8.8', '8.8.4.4']
        
        try:
            # Resolve the IP manually
            answers = resolver.resolve(host, 'A')
            resolved_ip = str(answers[0])
        except Exception:
            resolved_ip = host # Fallback if DNS fails

        return pymysql.connect(
            host=resolved_ip,  # Connect using the IP directly
            port=int(os.getenv('CLOUD_DB_PORT', 4000)),
            user=os.getenv('CLOUD_DB_USER'),
            password=os.getenv('CLOUD_DB_PASSWORD'),
            database=os.getenv('CLOUD_DB_NAME'),
            autocommit=True,
            ssl={'ssl': {}} 
        )