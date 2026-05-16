"""Resolve SWIFT/BIC and bank name from a Polish IBAN sort code.

Source: NBP eWIB registry (plewiba.xml, pub.wer.505, 2026-05-15).
"""

import re

# Mapping: sort-code prefix (first 3 digits of the 8-digit NR) → (BIC-8, bank name)
_PL_BANKS: dict[str, tuple[str, str]] = {
    "101":  ("NBPLPLPW", "Narodowy Bank Polski"),
    "102":  ("BPKOPLPW", "PKO Bank Polski S.A."),
    "103":  ("CITIPLPX", "Bank Handlowy w Warszawie S.A. (Citi Handlowy)"),
    "105":  ("INGBPLPW", "ING Bank Śląski S.A."),
    "106":  ("BPHKPLPK", "Bank BPH S.A."),
    "109":  ("WBKPPLPP", "Santander Bank Polska S.A."),
    "113":  ("GOSKPLPW", "Bank Gospodarstwa Krajowego"),
    "114":  ("BREXPLPW", "mBank S.A."),
    "116":  ("BIGBPLPW", "Bank Millennium S.A."),
    "124":  ("PKOPPLPW", "Bank Pekao S.A."),
    "132":  ("POCZPLP4", "Bank Pocztowy S.A."),
    "154":  ("EBOSPLPW", "Bank Ochrony Środowiska S.A."),
    "161":  ("GBWCPLPP", "SGB-Bank S.A."),
    "168":  ("IVSEPLPP", "Plus Bank S.A."),
    "184":  ("SOGEPLPW", "Société Générale S.A. Oddział w Polsce"),
    "187":  ("NESBPLPW", "Nest Bank S.A."),
    "189":  ("PKOPPLPW", "Pekao Bank Hipoteczny S.A."),
    "191":  ("DEUTPLPX", "Deutsche Bank Polska S.A."),
    "193":  ("POLUPLPR", "Bank Polskiej Spółdzielczości S.A."),
    "194":  ("AGRIPLPR", "Credit Agricole Bank Polska S.A."),
    "203":  ("PPABPLPK", "BNP Paribas Bank Polska S.A."),
    "212":  ("SCFBPLPW", "Santander Consumer Bank S.A."),
    "215":  ("RHBHPLPW", "mBank Hipoteczny S.A."),
    "216":  ("TOBAPLPW", "Toyota Bank Polska S.A."),
    "219":  ("MHBFPLPW", "DNB Bank Polska S.A."),
    "235":  ("BNPAPLPX", "BNP Paribas S.A. Oddział w Polsce"),
    "247":  ("ESSIPLPX", "Haitong Bank S.A. Oddział w Polsce"),
    "248":  ("POLUPLPR", "Getin Noble Bank S.A. (w upadłości)"),
    "249":  ("ALBPPLPW", "Alior Bank S.A."),
    "260":  ("BKCHPLPX", "Bank of China (Europe) S.A. Oddział w Polsce"),
    "269":  ("BPKHPLPG", "PKO Bank Hipoteczny S.A."),
    "273":  ("PCBCPLPW", "China Construction Bank (Europe) S.A. Oddział w Polsce"),
    "279":  ("RCBWPLPW", "Raiffeisen Bank International AG Oddział w Polsce"),
    "280":  ("HSBCPLPW", "HSBC Continental Europe Oddział w Polsce"),
    "286":  ("FBPLPLPW", "CA Auto Bank S.p.A. Oddział w Polsce"),
    "291":  ("BMPBPLPP", "UniCredit S.A. Oddział w Polsce"),
    "293":  ("GBGCPLPK", "VeloBank S.A."),
}


def resolve_iban(raw: str) -> dict[str, str]:
    """Return ``{"swift": ..., "bank_name": ...}`` for a Polish IBAN, or empty strings."""
    cleaned = re.sub(r"[\s\-]", "", raw).upper()
    if cleaned.startswith("PL"):
        cleaned = cleaned[2:]
    # After stripping "PL" we should have 26 digits: 2 check + 8 sort-code + 16 account
    if not re.fullmatch(r"\d{26}", cleaned):
        return {"swift": "", "bank_name": ""}
    sort_prefix = cleaned[2:5]  # first 3 digits of the 8-digit sort code
    entry = _PL_BANKS.get(sort_prefix)
    if entry:
        return {"swift": entry[0], "bank_name": entry[1]}
    return {"swift": "", "bank_name": ""}
