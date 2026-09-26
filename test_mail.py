import smtplib
from email.mime.text import MIMEText

sender = "palivinoreyven@gmail.com"        # Replace with your Gmail
app_password = "hdlw suub iizj rjts"     # Replace with 16-char App Password (NO SPACES)
recipient = "palivinoreyven@gmail.com"     # Send test email to yourself

msg = MIMEText("Test OTP Code: 123456")
msg['Subject'] = "EBC Test Mail"
msg['From'] = sender
msg['To'] = recipient

try:
    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(sender, app_password)
    server.sendmail(sender, recipient, msg.as_string())
    server.quit()
    print("SUCCESS: Test email sent!")
except Exception as e:
    print(f"ERROR DETAILS: {repr(e)}")