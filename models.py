from datetime import datetime
from database import db


class Complaint(db.Model):
    __tablename__ = 'complaints'

    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.String(64), unique=True, nullable=False)
    complaint_discord = db.Column(db.String(255))
    reported_name = db.Column(db.String(255))
    complaint_type = db.Column(db.String(255))
    incident_date = db.Column(db.String(255))
    incident_location = db.Column(db.String(255))
    witnesses = db.Column(db.Text)
    evidence_link = db.Column(db.Text)
    description = db.Column(db.Text)
    resolution = db.Column(db.Text)
    status = db.Column(db.String(64), default='Open')
    staff_notes = db.Column(db.Text, default='')
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Application(db.Model):
    __tablename__ = 'applications'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.String(64), unique=True, nullable=False)
    app_discord = db.Column(db.String(255))
    app_character = db.Column(db.String(255))
    application_type = db.Column(db.String(255))
    age_confirmation = db.Column(db.String(255))
    experience = db.Column(db.Text)
    role_reason = db.Column(db.Text)
    availability = db.Column(db.Text)
    status = db.Column(db.String(64), default='Pending')
    staff_notes = db.Column(db.Text, default='')
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Civilian(db.Model):
    __tablename__ = 'civilians'

    id = db.Column(db.Integer, primary_key=True)
    civilian_id = db.Column(db.String(64), unique=True, nullable=False)
    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    dob = db.Column(db.String(64))
    phone = db.Column(db.String(64))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Vehicle(db.Model):
    __tablename__ = 'vehicles'

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(64), unique=True, nullable=False)
    owner_name = db.Column(db.String(255))
    model = db.Column(db.String(255))
    color = db.Column(db.String(255))
    registration_status = db.Column(db.String(64), default='Valid')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class License(db.Model):
    __tablename__ = 'licenses'

    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.String(64), unique=True, nullable=False)
    owner_name = db.Column(db.String(255))
    license_type = db.Column(db.String(255))
    status = db.Column(db.String(64), default='Valid')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Warrant(db.Model):
    __tablename__ = 'warrants'

    id = db.Column(db.Integer, primary_key=True)
    warrant_id = db.Column(db.String(64), unique=True, nullable=False)
    warrant_name = db.Column(db.String(255))
    warrant_charges = db.Column(db.Text)
    warrant_status = db.Column(db.String(64), default='Active')
    warrant_issuer = db.Column(db.String(255))
    warrant_notes = db.Column(db.Text)
    expiration_date = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Arrest(db.Model):
    __tablename__ = 'arrests'

    id = db.Column(db.Integer, primary_key=True)
    arrest_id = db.Column(db.String(64), unique=True, nullable=False)
    suspect_name = db.Column(db.String(255))
    charges = db.Column(db.Text)
    arresting_officer = db.Column(db.String(255))
    arrest_location = db.Column(db.String(255))
    evidence_attached = db.Column(db.Text)
    penalty = db.Column(db.String(255))
    report_notes = db.Column(db.Text)
    narrative = db.Column(db.Text)
    status = db.Column(db.String(64), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Incident(db.Model):
    __tablename__ = 'incidents'

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.String(64), unique=True, nullable=False)
    incident_type = db.Column(db.String(255))
    location = db.Column(db.String(255))
    description = db.Column(db.Text)
    officer = db.Column(db.String(255))
    status = db.Column(db.String(64), default='Open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Evidence(db.Model):
    __tablename__ = 'evidence'

    id = db.Column(db.Integer, primary_key=True)
    evidence_id = db.Column(db.String(64), unique=True, nullable=False)
    case_number = db.Column(db.String(64))
    evidence_description = db.Column(db.Text)
    officer = db.Column(db.String(255))
    status = db.Column(db.String(64), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TrafficStop(db.Model):
    __tablename__ = 'traffic_stops'

    id = db.Column(db.Integer, primary_key=True)
    stop_id = db.Column(db.String(64), unique=True, nullable=False)
    driver_name = db.Column(db.String(255))
    plate = db.Column(db.String(64))
    reason = db.Column(db.Text)
    outcome = db.Column(db.String(255))
    officer = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Call911(db.Model):
    __tablename__ = 'calls_911'

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.String(64), unique=True, nullable=False)
    caller_name = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    location = db.Column(db.Text)
    description = db.Column(db.Text)
    incident_type = db.Column(db.String(255))
    priority = db.Column(db.String(64), default='Medium')
    assigned_unit = db.Column(db.String(64))
    status = db.Column(db.String(64), default='New')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class ActivityLog(db.Model):
    __tablename__ = 'activity_log'

    id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.String(64), unique=True, nullable=False)
    action = db.Column(db.Text)
    officer = db.Column(db.String(255))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RadioLog(db.Model):
    __tablename__ = 'radio_log'

    id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.String(64), unique=True, nullable=False)
    unit = db.Column(db.String(255))
    channel = db.Column(db.String(64), default='Primary')
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ServerStatus(db.Model):
    __tablename__ = 'server_status'

    id = db.Column(db.Integer, primary_key=True)
    city_status = db.Column(db.String(64), default='ACTIVE')
    player_count = db.Column(db.Integer, default=0)
    max_players = db.Column(db.Integer, default=32)
    custom_message = db.Column(db.String(255), default='24/7 dispatch channel live')
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)


class Alert(db.Model):
    __tablename__ = 'alerts'

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.String(64), unique=True, nullable=False)
    alert_type = db.Column(db.String(64))
    message = db.Column(db.Text)
    issued_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Bolo(db.Model):
    __tablename__ = 'bolos'

    id = db.Column(db.Integer, primary_key=True)
    bolo_id = db.Column(db.String(64), unique=True, nullable=False)
    suspect_name = db.Column(db.String(255))
    description = db.Column(db.Text)
    last_location = db.Column(db.String(255))
    vehicle = db.Column(db.String(255))
    charges = db.Column(db.Text)
    threat_level = db.Column(db.String(64), default='Medium')
    issued_by = db.Column(db.String(255))
    status = db.Column(db.String(64), default='Active')
    auto_generated = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OfficerSession(db.Model):
    __tablename__ = 'officer_sessions'

    id = db.Column(db.Integer, primary_key=True)
    callsign = db.Column(db.String(64), unique=True, nullable=False)
    officer_name = db.Column(db.String(255))
    department = db.Column(db.String(255), default='LSPD')
    status = db.Column(db.String(64), default='On Duty')
    logged_in_at = db.Column(db.DateTime, default=datetime.utcnow)


class Inmate(db.Model):
    __tablename__ = 'inmates'

    id = db.Column(db.Integer, primary_key=True)
    inmate_id = db.Column(db.String(64), unique=True, nullable=False)
    suspect_name = db.Column(db.String(255))
    charges = db.Column(db.Text)
    penalty = db.Column(db.String(255))
    cell = db.Column(db.String(64))
    booked_by = db.Column(db.String(255))
    arrest_id = db.Column(db.String(64))
    estimated_release = db.Column(db.String(64))
    notes = db.Column(db.Text)
    status = db.Column(db.String(64), default='In Custody')
    booked_at = db.Column(db.DateTime, default=datetime.utcnow)
    released_at = db.Column(db.DateTime)
    released_by = db.Column(db.String(255))
    release_reason = db.Column(db.Text)
    updated_at = db.Column(db.DateTime)


class Hearing(db.Model):
    __tablename__ = 'hearings'

    id = db.Column(db.Integer, primary_key=True)
    hearing_id = db.Column(db.String(64), unique=True, nullable=False)
    suspect_name = db.Column(db.String(255))
    charges = db.Column(db.Text)
    hearing_type = db.Column(db.String(64), default='Arraignment')
    scheduled_at = db.Column(db.String(64))
    judge = db.Column(db.String(255))
    notes = db.Column(db.Text)
    arrest_id = db.Column(db.String(64))
    filing_officer = db.Column(db.String(255))
    outcome = db.Column(db.Text)
    status = db.Column(db.String(64), default='Scheduled')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class DispatchCall(db.Model):
    __tablename__ = 'dispatch_calls'

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.String(64), unique=True, nullable=False)
    caller_name = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    location = db.Column(db.Text)
    description = db.Column(db.Text)
    priority = db.Column(db.String(64), default='Normal')
    status = db.Column(db.String(64), default='Open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
