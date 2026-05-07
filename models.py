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


class Bolo(db.Model):
    __tablename__ = 'bolos'

    id = db.Column(db.Integer, primary_key=True)
    bolo_id = db.Column(db.String(64), unique=True, nullable=False)
    subject_name = db.Column(db.String(255))
    reason = db.Column(db.Text)
    vehicle = db.Column(db.String(255))
    plate = db.Column(db.String(64))
    status = db.Column(db.String(64), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OfficerSession(db.Model):
    __tablename__ = 'officer_sessions'

    id = db.Column(db.Integer, primary_key=True)
    officer_name = db.Column(db.String(255))
    badge_number = db.Column(db.String(64))
    department = db.Column(db.String(255))
    status = db.Column(db.String(64), default='10-8')
    started_at = db.Column(db.DateTime, default=datetime.utcnow)


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
