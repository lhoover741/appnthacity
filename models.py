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
