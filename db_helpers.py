from database import db
from models import Complaint, Application


def get_all_complaints():
    complaints = Complaint.query.order_by(Complaint.submitted_at.desc()).all()

    return [
        {
            'id': c.complaint_id,
            'complaintDiscord': c.complaint_discord,
            'reportedName': c.reported_name,
            'complaintType': c.complaint_type,
            'incidentDate': c.incident_date,
            'incidentLocation': c.incident_location,
            'witnesses': c.witnesses,
            'evidenceLink': c.evidence_link,
            'description': c.description,
            'resolution': c.resolution,
            'status': c.status,
            'staffNotes': c.staff_notes,
        }
        for c in complaints
    ]


def get_all_applications():
    applications = Application.query.order_by(Application.submitted_at.desc()).all()

    return [
        {
            'id': a.application_id,
            'appDiscord': a.app_discord,
            'appCharacter': a.app_character,
            'applicationType': a.application_type,
            'ageConfirmation': a.age_confirmation,
            'experience': a.experience,
            'roleReason': a.role_reason,
            'availability': a.availability,
            'status': a.status,
            'staffNotes': a.staff_notes,
        }
        for a in applications
    ]
