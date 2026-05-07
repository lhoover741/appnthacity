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
    full_name = db.Column(db.String(255))
    date_of_birth = db.Column(db.Date)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(64))
    race = db.Column(db.String(255))
    phone_number = db.Column(db.String(64))
    address = db.Column(db.Text)
    occupation = db.Column(db.String(255))
    gang_affiliation = db.Column(db.String(255))
    risk_level = db.Column(db.String(64), default='Low')
    parole_status = db.Column(db.String(64), default='None')
    probation_status = db.Column(db.String(64), default='None')
    weapon_permit = db.Column(db.Boolean, default=False)
    driver_license_status = db.Column(db.String(64), default='Valid')
    notes = db.Column(db.Text)
    ai_generated = db.Column(db.Boolean, default=False)
    last_known_location = db.Column(db.String(255))
    biography = db.Column(db.Text)
    criminal_background = db.Column(db.Text)
    mental_state_notes = db.Column(db.Text)
    officer_safety_notes = db.Column(db.Text)
    warrant_risk = db.Column(db.String(64), default='Low')
    # Advanced character engine fields
    nickname = db.Column(db.String(255))
    aliases = db.Column(db.Text)  # JSON array
    employment_history = db.Column(db.Text)
    gang_rank = db.Column(db.String(64))
    habits = db.Column(db.Text)  # JSON array
    social_behavior = db.Column(db.Text)
    weapon_access = db.Column(db.String(64), default='None')
    violence_history = db.Column(db.String(64), default='None')
    # Legacy fields kept for backward compatibility
    dob = db.Column(db.String(64))
    phone = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Vehicle(db.Model):
    __tablename__ = 'vehicles'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.String(64), unique=True, nullable=True)
    owner_civilian_id = db.Column(db.String(64))
    plate = db.Column(db.String(64), unique=True, nullable=False)
    vin = db.Column(db.String(255))
    make = db.Column(db.String(255))
    model = db.Column(db.String(255))
    color = db.Column(db.String(255))
    registration_status = db.Column(db.String(64), default='Valid')
    insurance_status = db.Column(db.String(64), default='Valid')
    stolen_flag = db.Column(db.Boolean, default=False)
    impound_status = db.Column(db.String(64), default='None')
    bolo_link = db.Column(db.String(64))
    notes = db.Column(db.Text)
    # Legacy field kept for backward compatibility
    owner_name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class License(db.Model):
    __tablename__ = 'licenses'

    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.String(64), unique=True, nullable=False)
    owner_name = db.Column(db.String(255))
    license_type = db.Column(db.String(255))
    status = db.Column(db.String(64), default='Valid')
    issued_date = db.Column(db.String(64))
    expiry_date = db.Column(db.String(64))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Warrant(db.Model):
    __tablename__ = 'warrants'

    id = db.Column(db.Integer, primary_key=True)
    warrant_id = db.Column(db.String(64), unique=True, nullable=False)
    civilian_id = db.Column(db.String(64))
    warrant_name = db.Column(db.String(255))
    warrant_charges = db.Column(db.Text)
    warrant_issuer = db.Column(db.String(255))
    warrant_notes = db.Column(db.Text)
    warrant_status = db.Column(db.String(64), default='Active')
    expiration_date = db.Column(db.String(64))
    justification = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Arrest(db.Model):
    __tablename__ = 'arrests'

    id = db.Column(db.Integer, primary_key=True)
    arrest_id = db.Column(db.String(64), unique=True, nullable=False)
    civilian_id = db.Column(db.String(64))
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
    officers_involved = db.Column(db.Text)
    suspects = db.Column(db.Text)
    status = db.Column(db.String(64), default='Open')
    priority = db.Column(db.String(64), default='Medium')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Evidence(db.Model):
    __tablename__ = 'evidence'

    id = db.Column(db.Integer, primary_key=True)
    evidence_id = db.Column(db.String(64), unique=True, nullable=False)
    case_number = db.Column(db.String(64))
    evidence_description = db.Column(db.Text)
    collected_by = db.Column(db.String(255))
    location_found = db.Column(db.String(255))
    status = db.Column(db.String(64), default='Active')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class TrafficStop(db.Model):
    __tablename__ = 'traffic_stops'

    id = db.Column(db.Integer, primary_key=True)
    stop_id = db.Column(db.String(64), unique=True, nullable=False)
    driver_name = db.Column(db.String(255))
    plate = db.Column(db.String(64))
    reason = db.Column(db.Text)
    outcome = db.Column(db.String(255))
    officer = db.Column(db.String(255))
    location = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


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
    dispatch_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class ActivityLog(db.Model):
    __tablename__ = 'activity_log'

    id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.String(64), unique=True, nullable=False)
    action = db.Column(db.String(255))
    officer = db.Column(db.String(255))
    details = db.Column(db.Text)
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
    updated_at = db.Column(db.DateTime)


class OfficerSession(db.Model):
    __tablename__ = 'officer_sessions'

    id = db.Column(db.Integer, primary_key=True)
    callsign = db.Column(db.String(64), unique=True, nullable=False)
    officer_name = db.Column(db.String(255))
    badge_number = db.Column(db.String(64))
    department = db.Column(db.String(255), default='LSPD')
    status = db.Column(db.String(64), default='On Duty')
    logged_in_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Alert(db.Model):
    __tablename__ = 'alerts'

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.String(64), unique=True, nullable=False)
    alert_type = db.Column(db.String(64))
    message = db.Column(db.Text)
    issued_by = db.Column(db.String(255))
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
    assigned_unit = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class KnownAssociate(db.Model):
    __tablename__ = 'known_associates'

    id = db.Column(db.Integer, primary_key=True)
    associate_id = db.Column(db.String(64), unique=True, nullable=False)
    civilian_id = db.Column(db.String(64), nullable=False)
    associated_civilian_id = db.Column(db.String(64), nullable=False)
    relationship_type = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Business(db.Model):
    __tablename__ = 'businesses'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.String(64), unique=True, nullable=False)
    owner_civilian_id = db.Column(db.String(64))
    business_name = db.Column(db.String(255), nullable=False)
    business_type = db.Column(db.String(255))
    license_status = db.Column(db.String(64), default='Active')
    address = db.Column(db.Text)
    employees = db.Column(db.Integer, default=0)
    inspection_notes = db.Column(db.Text)
    legal_flags = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class Citation(db.Model):
    __tablename__ = 'citations'

    id = db.Column(db.Integer, primary_key=True)
    citation_id = db.Column(db.String(64), unique=True, nullable=False)
    civilian_id = db.Column(db.String(64), nullable=False)
    issuing_officer = db.Column(db.String(255))
    violation = db.Column(db.String(255))
    location = db.Column(db.String(255))
    fine_amount = db.Column(db.Float)
    status = db.Column(db.String(64), default='Issued')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class JailBooking(db.Model):
    __tablename__ = 'jail_bookings'

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.String(64), unique=True, nullable=False)
    civilian_id = db.Column(db.String(64), nullable=False)
    arrest_id = db.Column(db.String(64))
    charges = db.Column(db.Text)
    booking_officer = db.Column(db.String(255))
    cell_assignment = db.Column(db.String(64))
    bond_amount = db.Column(db.Float)
    sentence_length = db.Column(db.String(255))
    status = db.Column(db.String(64), default='Booked')
    release_date = db.Column(db.DateTime)
    released_by = db.Column(db.String(255))
    release_reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class UseOfForceReport(db.Model):
    __tablename__ = 'use_of_force_reports'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.String(64), unique=True, nullable=False)
    officer_name = db.Column(db.String(255))
    badge_number = db.Column(db.String(64))
    subject_name = db.Column(db.String(255))
    location = db.Column(db.String(255))
    force_type = db.Column(db.String(255))
    weapon_observed = db.Column(db.String(255))
    injuries_observed = db.Column(db.Text)
    charges = db.Column(db.Text)
    narrative = db.Column(db.Text)
    supervisor_review = db.Column(db.Text)
    status = db.Column(db.String(64), default='Pending')
    ai_generated = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class OfficerNote(db.Model):
    __tablename__ = 'officer_notes'

    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.String(64), unique=True, nullable=False)
    officer_name = db.Column(db.String(255))
    civilian_id = db.Column(db.String(64))
    note_type = db.Column(db.String(64))
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class CaseFile(db.Model):
    __tablename__ = 'case_files'

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.String(64), unique=True, nullable=False)
    defendant_civilian_id = db.Column(db.String(64))
    charges = db.Column(db.Text)
    evidence_ids = db.Column(db.Text)
    arrest_id = db.Column(db.String(64))
    assigned_judge = db.Column(db.String(255))
    prosecutor_notes = db.Column(db.Text)
    defense_notes = db.Column(db.Text)
    court_date = db.Column(db.DateTime)
    status = db.Column(db.String(64), default='Open')
    outcome = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)


class AIGenerationLog(db.Model):
    __tablename__ = 'ai_generation_logs'

    id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.String(64), unique=True, nullable=False)
    generation_type = db.Column(db.String(64))
    input_params = db.Column(db.Text)
    output_summary = db.Column(db.Text)
    tokens_used = db.Column(db.Integer)
    cost = db.Column(db.Float)
    status = db.Column(db.String(64), default='Success')
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.String(64), unique=True, nullable=False)
    officer_name = db.Column(db.String(255))
    action = db.Column(db.String(255))
    record_type = db.Column(db.String(64))
    record_id = db.Column(db.String(64))
    before_state = db.Column(db.Text)
    after_state = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
