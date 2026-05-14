from abc import ABC, abstractmethod


class BaseKsefClient(ABC):
    @abstractmethod
    def send_invoice(self, invoice_id: int, xml_content: str) -> dict:
        """Send XML to KSeF. Returns dict with invoice_ref and session_ref."""
        raise NotImplementedError

    @abstractmethod
    def get_invoice_status(self, session_ref: str, invoice_ref: str) -> dict:
        """Poll KSeF for invoice acceptance status."""
        raise NotImplementedError
