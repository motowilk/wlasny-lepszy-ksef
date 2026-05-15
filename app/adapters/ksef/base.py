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

    @abstractmethod
    def fetch_invoices(
        self,
        date_from: str,
        date_to: str,
        subject_type: str = "subject2",
    ) -> list[dict]:
        """
        Fetch invoices from KSeF for a given date range.

        Args:
            date_from: ISO date string (e.g. "2026-05-01T00:00:00").
            date_to: ISO date string (e.g. "2026-05-15T23:59:59").
            subject_type: "subject1" (seller=me) or "subject2" (buyer=me, i.e. purchase).

        Returns:
            List of dicts with keys: ksef_number, xml_content, invoice_ref.
        """
        raise NotImplementedError
