import uuid

from app.adapters.ksef.base import BaseKsefClient


class MockKsefClient(BaseKsefClient):
    def send_invoice(self, invoice_id: int, xml_content: str) -> dict:
        return {
            "invoice_ref": f"MOCK-INV-{invoice_id}-{uuid.uuid4().hex[:8].upper()}",
            "session_ref": f"MOCK-SES-{uuid.uuid4().hex[:8].upper()}",
        }

    def get_invoice_status(self, session_ref: str, invoice_ref: str) -> dict:
        return {
            "ksefNumber": f"MOCK-KSEF-{invoice_ref}",
            "status": {"code": 200, "description": "Accepted (mock)"},
        }
