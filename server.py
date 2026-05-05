import os
import json
import smtplib
import logging
import secrets
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory, session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.environ.get('FLASK_SECRET', secrets.token_hex(32))

COMPLAINTS_FILE = 'complaints_data.json'
APPLICATIONS_FILE = 'applications_data.json'
SERVER_STATUS_FILE = 'server_status.json'

DEFAULT_STATUS = {
    'cityStatus': 'ACTIVE',
    'playerCount': 0,
    'maxPlayers': 32,
    'customMessage': '24/7 dispatch channel live',
    'lastUpdated': None
}


def load_server_status():
    if os.path.exists(SERVER_STATUS_FILE):
        with open(SERVER_STATUS_FILE, 'r') as f:
            return json.load(f)
    return dict(DEFAULT_STATUS)


def save_server_status(status):
    status['lastUpdated'] = datetime.now().isoformat()
    with open(SERVER_STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)
    return status


def load_applications():
    if os.path.exists(APPLICATIONS_FILE):
        with open(APPLICATIONS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_applications(applications):
    with open(APPLICATIONS_FILE, 'w') as f:
        json.dump(applications, f, indent=2)


def save_application(data):
    applications = load_applications()
    data['id'] = f"APP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(applications)+1:04d}"
    data['submittedAt'] = datetime.now().isoformat()
    data['status'] = 'Pending'
    data['staffNotes'] = ''
    applications.append(data)
    save_applications(applications)
    return data


def send_application_email(app):
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', '465'))
    smtp_email = os.environ.get('SMTP_EMAIL')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    notify_email = os.environ.get('NOTIFY_EMAIL', smtp_email)
    from_name = os.environ.get('SMTP_FROM_NAME', 'NThaCityRP')

    if not smtp_email or not smtp_password:
        logger.warning('Email credentials not configured. Application saved but no email sent.')
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[NThaCityRP] New Application — {app['applicationType']} — {app['id']}"
        msg['From'] = f"{from_name} <{smtp_email}>"
        msg['To'] = notify_email

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#111;color:#eee;padding:24px;">
          <div style="max-width:600px;margin:0 auto;background:#1a1a1a;border-radius:12px;padding:24px;border:1px solid #333;">
            <h2 style="color:#ff2d2d;margin-top:0;">NThaCityRP — New Application Submitted</h2>
            <table style="width:100%;border-collapse:collapse;">
              <tr><td style="padding:8px 0;color:#aaa;width:40%;">Application ID</td><td style="padding:8px 0;font-weight:bold;">{app['id']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Submitted At</td><td style="padding:8px 0;">{app['submittedAt']}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Discord</td><td style="padding:8px 0;">{app.get('appDiscord','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Character Name</td><td style="padding:8px 0;">{app.get('appCharacter','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Role Applied For</td><td style="padding:8px 0;"><strong style="color:#ff2d2d;">{app.get('applicationType','N/A')}</strong></td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Age</td><td style="padding:8px 0;">{app.get('ageConfirmation','N/A')}</td></tr>
              <tr><td style="padding:8px 0;color:#aaa;">Availability</td><td style="padding:8px 0;">{app.get('availability','N/A')}</td></tr>
            </table>
            <hr style="border-color:#333;margin:16px 0;">
            <p style="color:#aaa;margin:4px 0;">RP Experience</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #ff2d2d;">{app.get('experience','N/A')}</p>
            <p style="color:#aaa;margin:4px 0;">Why They Want This Role</p>
            <p style="background:#111;padding:12px;border-radius:8px;border-left:3px solid #555;">{app.get('roleReason','N/A')}</p>
            <p style="color:#555;font-size:12px;margin-top:24px;">NThaCityRP Application System — Automated Notification</p>
          </div>
        </body></html>
        """

        plain = f"""
NThaCityRP — New Application Submitted
=======================================
Application ID: {app['id']}
Submitted At:   {app['submittedAt']}
Discord:        {app.get('appDiscord','N/A')}
Character:      {app.get('appCharacter','N/A')}
Role:           {app.get('applicationType','N/A')}
Age:            {app.get('ageConfirmation','N/A')}
Availability:   {app.get('availability','N/A')}

RP Experience:
{app.get('experience','N/A')}

Why This Role:
{app.get('roleReason','N/A')}
        """

        msg.attach(MIMEText(plain, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as srv:
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())

        logger.info(f"Application email sent for {app['id']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send application email: {e}")
        return False


def send_application_discord(app):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url or 'placeholder' in webhook_url:
        logger.warning('Discord webhook not configured. Skipping Discord notification.')
        return False

    try:
        type_colors = {
            'Police Department': 3447003,
            'EMS': 3066993,
            'Staff': 10181046,
            'Business Owner': 16744272,
            'Gang / Faction': 15158332,
            'Court / Judge / Lawyer': 16776960,
            'DMV Worker': 9807270,
        }
        color = type_colors.get(app.get('applicationType', ''), 3447003)

        payload = {
            "username": "NThaCityRP Applications",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
            "embeds": [{
                "title": f"📋 New Application — {app.get('applicationType', 'Unknown')}",
                "description": f"**RP Experience:**\n{app.get('experience', 'N/A')}\n\n**Why This Role:**\n{app.get('roleReason', 'N/A')}",
                "color": color,
                "fields": [
                    {"name": "Application ID", "value": f"`{app['id']}`", "inline": True},
                    {"name": "Role", "value": app.get('applicationType', 'N/A'), "inline": True},
                    {"name": "Discord", "value": app.get('appDiscord', 'N/A'), "inline": True},
                    {"name": "Character", "value": app.get('appCharacter', 'N/A'), "inline": True},
                    {"name": "Age", "value": app.get('ageConfirmation', 'N/A'), "inline": True},
                    {"name": "Availability", "value": app.get('availability', 'N/A'), "inline": True},
                ],
                "footer": {"text": f"NThaCityRP Application System • {app['submittedAt'][:10]}"},
            }]
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                logger.info(f"Discord notification sent for {app['id']}")
                return True
    except Exception as e:
        logger.error(f"Application Discord webhook failed: {e}")
    return False


def load_complaints():
    if os.path.exists(COMPLAINTS_FILE):
        with open(COMPLAINTS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_complaints(complaints):
    with open(COMPLAINTS_FILE, 'w') as f:
        json.dump(complaints, f, indent=2)


def save_complaint(data):
    complaints = load_complaints()
    data['id'] = f"CMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(complaints)+1:04d}"
    data['submittedAt'] = datetime.now().isoformat()
    data['status'] = 'Open'
    data['staffNotes'] = ''
    complaints.append(data)
    save_complaints(complaints)
    return data


def send_email_notification(complaint):
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', '465'))
    smtp_email = os.environ.get('SMTP_EMAIL')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    notify_email = os.environ.get('NOTIFY_EMAIL', smtp_email)
    from_name = os.environ.get('SMTP_FROM_NAME', 'NThaCityRP')

    if not smtp_email or not smtp_password:
        logger.warning('Email credentials not configured. Complaint saved but no email sent.')
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[NThaCityRP] New Complaint — {complaint['complaintType']} — {complaint['id']}"
        msg['From'] = f"{from_name} <{smtp_email}>"
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

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as srv:
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(smtp_email, smtp_password)
                srv.sendmail(smtp_email, notify_email, msg.as_string())

        logger.info(f"Email notification sent for complaint {complaint['id']}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_discord_notification(complaint):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url or 'placeholder' in webhook_url:
        logger.warning('Discord webhook not configured. Skipping Discord notification.')
        return False

    try:
        type_colors = {
            'Player report': 15158332,
            'Staff complaint': 15105570,
            'Officer complaint': 15548997,
            'Rule break': 16711680,
            'Fail RP': 16744272,
            'RDM / VDM': 16711680,
            'Harassment': 15158332,
            'Evidence submission': 3447003,
        }
        color = type_colors.get(complaint.get('complaintType', ''), 15158332)

        fields = [
            {"name": "Complaint ID", "value": f"`{complaint['id']}`", "inline": True},
            {"name": "Type", "value": complaint.get('complaintType', 'N/A'), "inline": True},
            {"name": "Reported Person", "value": complaint.get('reportedName', 'N/A'), "inline": True},
            {"name": "Discord", "value": complaint.get('complaintDiscord', 'N/A'), "inline": True},
            {"name": "Location", "value": complaint.get('incidentLocation', 'N/A'), "inline": True},
            {"name": "Incident Date", "value": complaint.get('incidentDate', 'N/A'), "inline": True},
        ]
        if complaint.get('witnesses'):
            fields.append({"name": "Witnesses", "value": complaint['witnesses'], "inline": False})
        if complaint.get('evidenceLink'):
            fields.append({"name": "Evidence", "value": complaint['evidenceLink'], "inline": False})

        payload = {
            "username": "NThaCityRP Complaints",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
            "embeds": [{
                "title": f"🚨 New Complaint Filed — {complaint.get('complaintType', 'Unknown')}",
                "description": f"**Description:**\n{complaint.get('description', 'N/A')}\n\n**Desired Resolution:**\n{complaint.get('resolution', 'N/A')}",
                "color": color,
                "fields": fields,
                "footer": {"text": f"NThaCityRP Complaint System • {complaint['submittedAt'][:10]}"},
            }]
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                logger.info(f"Discord notification sent for {complaint['id']}")
                return True
    except Exception as e:
        logger.error(f"Discord webhook failed: {e}")
    return False


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    password = data.get('password', '')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'nthatcityrp2024')
    if password == admin_password:
        session['admin_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid password'}), 401


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/admin/session', methods=['GET'])
def admin_session():
    return jsonify({'loggedIn': bool(session.get('admin_logged_in'))})


@app.route('/api/complaint', methods=['POST'])
def submit_complaint():
    data = request.get_json(silent=True) or {}
    required = ['complaintDiscord', 'reportedName', 'complaintType', 'incidentDate', 'incidentLocation', 'description', 'resolution']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}), 400

    complaint = save_complaint(data)
    email_sent = send_email_notification(complaint)
    send_discord_notification(complaint)

    return jsonify({
        'success': True,
        'id': complaint['id'],
        'emailSent': email_sent,
        'message': 'Complaint submitted successfully. Staff will review it shortly.'
    })


@app.route('/api/complaints', methods=['GET'])
@admin_required
def list_complaints():
    complaints = load_complaints()
    complaints.sort(key=lambda c: c.get('submittedAt', ''), reverse=True)
    return jsonify({'complaints': complaints, 'total': len(complaints)})


@app.route('/api/complaint/<complaint_id>/status', methods=['POST'])
@admin_required
def update_complaint_status(complaint_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    staff_notes = data.get('staffNotes')
    valid_statuses = ['Open', 'Under Review', 'Resolved', 'Dismissed']
    if new_status and new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    complaints = load_complaints()
    for c in complaints:
        if c['id'] == complaint_id:
            if new_status:
                c['status'] = new_status
                c['updatedAt'] = datetime.now().isoformat()
            if staff_notes is not None:
                c['staffNotes'] = staff_notes
            save_complaints(complaints)
            return jsonify({'success': True, 'complaint': c})

    return jsonify({'success': False, 'error': 'Complaint not found'}), 404


@app.route('/api/complaint/<complaint_id>', methods=['DELETE'])
@admin_required
def delete_complaint(complaint_id):
    complaints = load_complaints()
    original_len = len(complaints)
    complaints = [c for c in complaints if c['id'] != complaint_id]
    if len(complaints) == original_len:
        return jsonify({'success': False, 'error': 'Complaint not found'}), 404
    save_complaints(complaints)
    return jsonify({'success': True})


@app.route('/api/application', methods=['POST'])
def submit_application():
    data = request.get_json(silent=True) or {}
    required = ['appDiscord', 'appCharacter', 'applicationType', 'ageConfirmation', 'experience', 'roleReason', 'availability']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}), 400

    application = save_application(data)
    send_application_email(application)
    send_application_discord(application)

    return jsonify({
        'success': True,
        'id': application['id'],
        'message': 'Application submitted successfully. Staff will review it and contact you via Discord.'
    })


@app.route('/api/applications', methods=['GET'])
@admin_required
def list_applications():
    applications = load_applications()
    applications.sort(key=lambda a: a.get('submittedAt', ''), reverse=True)
    return jsonify({'applications': applications, 'total': len(applications)})


@app.route('/api/application/<app_id>/status', methods=['POST'])
@admin_required
def update_application_status(app_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    staff_notes = data.get('staffNotes')
    valid_statuses = ['Pending', 'Under Review', 'Accepted', 'Denied']
    if new_status and new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    applications = load_applications()
    for a in applications:
        if a['id'] == app_id:
            if new_status:
                a['status'] = new_status
                a['updatedAt'] = datetime.now().isoformat()
            if staff_notes is not None:
                a['staffNotes'] = staff_notes
            save_applications(applications)
            return jsonify({'success': True, 'application': a})

    return jsonify({'success': False, 'error': 'Application not found'}), 404


@app.route('/api/application/<app_id>', methods=['DELETE'])
@admin_required
def delete_application(app_id):
    applications = load_applications()
    original_len = len(applications)
    applications = [a for a in applications if a['id'] != app_id]
    if len(applications) == original_len:
        return jsonify({'success': False, 'error': 'Application not found'}), 404
    save_applications(applications)
    return jsonify({'success': True})


@app.route('/api/server-status', methods=['GET'])
def get_server_status():
    return jsonify(load_server_status())


def send_status_discord_notification(old_status, new_status):
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url or 'placeholder' in webhook_url:
        logger.warning('Discord webhook not configured. Skipping status notification.')
        return False

    status_colors = {
        'ACTIVE':      0x4caf50,
        'OFFLINE':     0x555555,
        'MAINTENANCE': 0x4a9eff,
        'WHITELIST':   0xf5a623,
    }
    status_emojis = {
        'ACTIVE':      '🟢',
        'OFFLINE':     '🔴',
        'MAINTENANCE': '🔵',
        'WHITELIST':   '🟡',
    }

    city = new_status.get('cityStatus', 'ACTIVE')
    color = status_colors.get(city, 0x555555)
    emoji = status_emojis.get(city, '⚪')

    old_city = old_status.get('cityStatus', 'ACTIVE')
    changed = old_city != city
    title = f"{emoji} City Status Changed: {old_city} → {city}" if changed else f"{emoji} City Status Updated: {city}"

    fields = [
        {"name": "City Status", "value": city, "inline": True},
        {"name": "Players Online", "value": f"{new_status.get('playerCount', 0)} / {new_status.get('maxPlayers', 32)}", "inline": True},
    ]
    if new_status.get('customMessage'):
        fields.append({"name": "Message", "value": new_status['customMessage'], "inline": False})

    payload = {
        "username": "NThaCityRP Status",
        "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
        "embeds": [{
            "title": title,
            "color": color,
            "fields": fields,
            "footer": {"text": f"NThaCityRP • {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"},
        }]
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info('Status Discord notification sent.')
        return True
    except Exception as e:
        logger.error(f'Failed to send status Discord notification: {e}')
        return False


@app.route('/api/server-status', methods=['POST'])
@admin_required
def update_server_status():
    data = request.get_json(silent=True) or {}
    old_status = load_server_status()
    status = dict(old_status)
    valid_statuses = ['ACTIVE', 'OFFLINE', 'MAINTENANCE', 'WHITELIST']
    if 'cityStatus' in data and data['cityStatus'] in valid_statuses:
        status['cityStatus'] = data['cityStatus']
    if 'playerCount' in data:
        try:
            status['playerCount'] = max(0, int(data['playerCount']))
        except (ValueError, TypeError):
            pass
    if 'maxPlayers' in data:
        try:
            status['maxPlayers'] = max(1, int(data['maxPlayers']))
        except (ValueError, TypeError):
            pass
    if 'customMessage' in data:
        status['customMessage'] = str(data['customMessage'])[:200]
    save_server_status(status)
    send_status_discord_notification(old_status, status)
    return jsonify({'success': True, 'status': status})


@app.route('/api/ai/police-report', methods=['POST'])
def ai_police_report():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured. Add it in your environment secrets.'}), 503

    data = request.get_json(silent=True) or {}
    suspect = data.get('suspectName', 'Unknown')
    charges = data.get('charges', 'Unknown')
    officer = data.get('arrestingOfficer', 'Unknown')
    location = data.get('arrestLocation', 'Unknown')
    evidence = data.get('evidenceAttached', 'None')
    penalty = data.get('penalty', 'Unknown')
    notes = data.get('reportNotes', '')

    prompt = f"""You are a police report writer for the NThaCityRP Discord roleplay community set in Los Santos.
Based on the arrest details below, respond with ONLY a valid JSON object containing exactly two keys:
- "narrative": a formal, professional arrest report narrative (150-220 words, third-person past tense, law enforcement language)
- "suggestedPenalty": a short realistic penalty string (e.g. "3 years / $25,000 fine" or "18 months + community service") based on the charges — if a penalty was already provided, refine and return it as-is

Suspect: {suspect}
Charges: {charges}
Arresting Officer: {officer}
Arrest Location: {location}
Evidence: {evidence}
Current Penalty: {penalty if penalty else 'Not specified'}
Officer Notes: {notes if notes else 'None provided'}

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 500,
            'temperature': 0.7,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'NThaCityRP Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({
                'success': True,
                'narrative': ai_json.get('narrative', ''),
                'suggestedPenalty': ai_json.get('suggestedPenalty', '')
            })
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenAI API error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenAI error {e.code}: check your API key and billing.'}), 502
    except Exception as e:
        logger.error(f'AI report generation failed: {e}')
        return jsonify({'success': False, 'error': 'Report generation failed. Try again.'}), 500


@app.route('/api/ai/dispatch', methods=['POST'])
def ai_dispatch():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    caller = data.get('callerName', 'Unknown')
    location = data.get('location', 'Unknown')
    description = data.get('description', '')

    prompt = f"""You are an LAPD-style 911 dispatch triage AI for the NThaCityRP Discord roleplay community set in Los Santos.
Based on the caller info and description, respond with ONLY a valid JSON object with these exact keys:
- "incidentType": one of exactly ["Robbery", "Assault", "Suspicious activity", "Traffic accident", "Shots fired", "Domestic disturbance", "Drug activity", "Pursuit", "Hostage situation", "Noise complaint"]
- "priority": one of exactly ["Critical", "High", "Medium", "Low"] — Critical=active threat/shots/hostage, High=robbery/assault in progress, Medium=suspicious/drugs, Low=noise/minor
- "assignedUnit": a short realistic unit designation string (e.g. "Unit 4", "Unit 12", "K9-02", "Air-1") based on the incident type
- "status": always return "New"
- "triage": one sentence (max 20 words) summarising the call for the dispatcher log

Caller: {caller}
Location: {location}
Description: {description if description else 'No description provided'}

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 200,
            'temperature': 0.4,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'NThaCityRP Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({
                'success': True,
                'incidentType': ai_json.get('incidentType', ''),
                'priority': ai_json.get('priority', ''),
                'assignedUnit': ai_json.get('assignedUnit', ''),
                'status': ai_json.get('status', 'New'),
                'triage': ai_json.get('triage', '')
            })
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenAI dispatch error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenAI error {e.code}: check your API key.'}), 502
    except Exception as e:
        logger.error(f'AI dispatch triage failed: {e}')
        return jsonify({'success': False, 'error': 'Triage failed. Try again.'}), 500


@app.route('/api/ai/warrant', methods=['POST'])
def ai_warrant():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    suspect = data.get('warrantName', 'Unknown')
    charges = data.get('warrantCharges', 'Unknown')
    issuer = data.get('warrantIssuer', 'Unknown')
    existing_notes = data.get('warrantNotes', '')

    prompt = f"""You are a warrant writer for the NThaCityRP Discord roleplay community set in Los Santos.
Based on the details below, respond with ONLY a valid JSON object with exactly two keys:
- "justification": a formal warrant justification paragraph (80-130 words) explaining the legal basis and probable cause for issuing this warrant, written in official law enforcement language
- "suggestedStatus": always return "Active"

Suspect: {suspect}
Charges: {charges}
Issued By: {issuer}
Additional Notes: {existing_notes if existing_notes else 'None'}

Respond only with the JSON object. No markdown, no extra text."""

    from datetime import timedelta
    expiration_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 300,
            'temperature': 0.7,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'NThaCityRP Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({
                'success': True,
                'justification': ai_json.get('justification', ''),
                'suggestedStatus': ai_json.get('suggestedStatus', 'Active'),
                'suggestedExpiration': expiration_date
            })
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenAI warrant error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenAI error {e.code}: check your API key.'}), 502
    except Exception as e:
        logger.error(f'AI warrant generation failed: {e}')
        return jsonify({'success': False, 'error': 'Warrant generation failed. Try again.'}), 500


@app.route('/api/ai/incident-summary', methods=['POST'])
def ai_incident_summary():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    notes = data.get('notes', '').strip()

    if not notes:
        return jsonify({'success': False, 'error': 'No CAD notes provided.'}), 400

    prompt = f"""You are a law enforcement report writer for the NThaCityRP Los Santos roleplay community.
An officer has provided raw CAD notes from an incident. Generate a clean, professional incident summary formatted for posting in a Discord channel using Discord markdown.

Rules:
- Use **bold** for section labels
- Use a code block only for case number if present
- Keep it concise — max 200 words
- Include these sections if data is available: Incident Type, Location, Time, Officers Involved, Suspect(s), Charges, Outcome, Notes
- End with a horizontal rule line (—————————————)
- Do NOT include ```discord``` wrapper — just the raw Discord-formatted text

Raw CAD Notes:
{notes}

Respond with ONLY a valid JSON object with one key:
- "summary": the full Discord-formatted incident summary string"""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 500,
            'temperature': 0.4,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'NThaCityRP Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({'success': True, 'summary': ai_json.get('summary', '')})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenAI incident summary error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenAI error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI incident summary failed: {e}')
        return jsonify({'success': False, 'error': 'Summary failed. Try again.'}), 500


@app.route('/api/ai/suspect-match', methods=['POST'])
def ai_suspect_match():
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OPENROUTER_API_KEY not configured.'}), 503

    data = request.get_json(silent=True) or {}
    description = data.get('description', '').strip()
    civilians = data.get('civilians', [])

    if not description:
        return jsonify({'success': False, 'error': 'No description provided.'}), 400

    if not civilians:
        return jsonify({'success': True, 'matches': [], 'note': 'No civilians registered in the system yet.'})

    civ_list = '\n'.join([
        f"- Name: {c.get('firstName','?')} {c.get('lastName','?')} | DOB: {c.get('dob','?')} | Gender: {c.get('gender','?')} | Occupation: {c.get('occupation','?')} | Notes: {c.get('notes','')}"
        for c in civilians[:50]
    ])

    prompt = f"""You are a suspect identification assistant for the NThaCityRP Los Santos roleplay community.
An officer has provided a physical description of a suspect. Compare it against the registered civilian database below and identify the top matches.

Respond with ONLY a valid JSON object with one key:
- "matches": an array of up to 3 objects, each with:
  - "name": full name of the civilian
  - "confidence": "High", "Medium", or "Low"
  - "reason": one short sentence (max 15 words) explaining why they match

If no civilians are a reasonable match, return an empty matches array.

Suspect Description: {description}

Registered Civilians:
{civ_list}

Respond only with the JSON object. No markdown, no extra text."""

    try:
        payload = json.dumps({
            'model': 'openai/gpt-4o-mini',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 300,
            'temperature': 0.3,
            'response_format': {'type': 'json_object'}
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'https://nthacityrp.com',
                'X-Title': 'NThaCityRP Police CAD'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            ai_json = json.loads(result['choices'][0]['message']['content'])
            return jsonify({'success': True, 'matches': ai_json.get('matches', [])})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f'OpenAI suspect match error: {e.code} {body}')
        return jsonify({'success': False, 'error': f'OpenAI error {e.code}.'}), 502
    except Exception as e:
        logger.error(f'AI suspect match failed: {e}')
        return jsonify({'success': False, 'error': 'Match failed. Try again.'}), 500


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
