import os
import json
import smtplib
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')

COMPLAINTS_FILE = 'complaints_data.json'


def load_complaints():
    if os.path.exists(COMPLAINTS_FILE):
        with open(COMPLAINTS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_complaint(data):
    complaints = load_complaints()
    data['id'] = f"CMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(complaints)+1:04d}"
    data['submittedAt'] = datetime.now().isoformat()
    complaints.append(data)
    with open(COMPLAINTS_FILE, 'w') as f:
        json.dump(complaints, f, indent=2)
    return data


def send_email_notification(complaint):
    smtp_email = os.environ.get('SMTP_EMAIL')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    notify_email = os.environ.get('NOTIFY_EMAIL', smtp_email)

    if not smtp_email or not smtp_password:
        logger.warning('Email credentials not configured. Complaint saved but no email sent.')
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[NThaCityRP] New Complaint — {complaint['complaintType']} — {complaint['id']}"
        msg['From'] = smtp_email
        msg['To'] = notify_email

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#111;color:#eee;padding:24px;">
          <div style="max-width:600px;margin:0 auto;background:#1a1a1a;border-radius:12px;padding:24px;border:1px solid #333;">
            <h2 style="color:#ff2d2d;margin-top:0;">NThaCityRP — New Complaint Filed</h2>
            <table style="width:100%;border-collapse:collapse;">
              <tr><td style="padding:8px 0;color:#aaa;width:40%;">Complaint ID</td><td style="padding:8px 0;font-weight:bold;">{complaint['id']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Submitted At</td><td style="padding:8px 0;">{complaint['submittedAt']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Discord Username</td><td style="padding:8px 0;">{complaint.get('complaintDiscord','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Reported Person</td><td style="padding:8px 0;">{complaint.get('reportedName','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Complaint Type</td><td style="padding:8px 0;"><strong style="color:#ff2d2d;">{complaint.get('complaintType','N/A')}</strong></td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Incident Date/Time</td><td style="padding:8px 0;">{complaint.get('incidentDate','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Location/Channel</td><td style="padding:8px 0;">{complaint.get('incidentLocation','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Witnesses</td><td style="padding:8px 0;">{complaint.get('witnesses','None')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Evidence Link</td><td style="padding:8px 0;">{complaint.get('evidenceLink','None')}</td></tr>
            </table>
            <hr style="border-color:#333;margin:16px 0;">
            <p style="color:#aaa;margin:4px 0;">Description</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #ff2d2d;">{complaint.get('description','N/A')}</p>
            <p style="color:#aaa;margin:4px 0;">Desired Resolution</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #555;">{complaint.get('resolution','N/A')}</p>
            <p style="color:#555;font-size:12px;margin-top:24px;">NThaCityRP Complaint System — Automated Notification</p>
          </div>
        </body></html>
        """

        plain = f"""
NThaCityRP — New Complaint Filed
=================================
Complaint ID:     {complaint['id']}
Submitted At:     {complaint['submittedAt']}
Discord Username: {complaint.get('complaintDiscord','N/A')}
Reported Person:  {complaint.get('reportedName','N/A')}
Complaint Type:   {complaint.get('complaintType','N/A')}
Incident Date:    {complaint.get('incidentDate','N/A')}
Location:         {complaint.get('incidentLocation','N/A')}
Witnesses:        {complaint.get('witnesses','None')}
Evidence Link:    {complaint.get('evidenceLink','None')}

Description:
{complaint.get('description','N/A')}

Desired Resolution:
{complaint.get('resolution','N/A')}
        """

        msg.attach(MIMEText(plain, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, notify_email, msg.as_string())

        logger.info(f"Email notification sent for complaint {complaint['id']}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


@app.route('/api/complaint', methods=['POST'])
def submit_complaint():
    data = request.get_json(silent=True) or {}

    required = ['complaintDiscord', 'reportedName', 'complaintType', 'incidentDate', 'incidentLocation', 'description', 'resolution']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}), 400

    complaint = save_complaint(data)
    email_sent = send_email_notification(complaint)

    return jsonify({
        'success': True,
        'id': complaint['id'],
        'emailSent': email_sent,
        'message': 'Complaint submitted successfully. Staff will review it shortly.'
    })


@app.route('/api/complaints', methods=['GET'])
def list_complaints():
    complaints = load_complaints()
    return jsonify({'complaints': complaints, 'total': len(complaints)})


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if path == '':
        return send_from_directory('.', 'index.html')
    if os.path.exists(os.path.join('.', path)):
        return send_from_directory('.', path)
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
