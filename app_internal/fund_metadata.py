"""Static fund-restriction metadata for the internal budget dashboard.

Keys match Fund_Name values as they appear in bex_fm_expense / bex_open_encumbrances.
For any fund not in FUND_RESTRICTIONS, callers should fall back to UNKNOWN_FUND.

To extend: add an entry whose key matches exactly the Fund_Name string coming from BEx.
"""
from __future__ import annotations

FUND_RESTRICTIONS: dict[str, dict[str, str]] = {
    "GENERAL FUND": {
        "type": "state-unrestricted",
        "text": (
            "State General Fund — unrestricted operating dollars; subject to the General "
            "Assembly appropriation act. No program-specific spending restrictions beyond "
            "the appropriation line items."
        ),
    },
    "GF-NONRECUR APROP-23": {
        "type": "state-unrestricted",
        "text": (
            "FY2023 non-recurring General Fund appropriation. One-time dollars that "
            "expired at fiscal year close; cannot be carried forward or re-appropriated."
        ),
    },
    "GF-NONRECUR APROP-24": {
        "type": "state-unrestricted",
        "text": (
            "FY2024 non-recurring General Fund appropriation. One-time dollars that "
            "expired at fiscal year close; cannot be carried forward or re-appropriated."
        ),
    },
    "GF-NONRECUR APROP-25": {
        "type": "state-unrestricted",
        "text": (
            "FY2025 non-recurring General Fund appropriation. One-time dollars that "
            "expired at fiscal year close; cannot be carried forward or re-appropriated."
        ),
    },
    "GF-NONRECUR APROP-26": {
        "type": "state-unrestricted",
        "text": (
            "FY2026 non-recurring General Fund appropriation. One-time dollars — "
            "if unexpended at fiscal year close they lapse back to the General Fund."
        ),
    },
    "EARMARKED FUNDS": {
        "type": "other-restricted",
        "text": (
            "Earmarked funds — appropriated for specific programs in the General "
            "Appropriations Act provisos. Use is restricted to the purpose named in "
            "the relevant proviso language. Verify current proviso before re-purposing."
        ),
    },
    "OPERATING REVENUE": {
        "type": "operating",
        "text": (
            "Agency operating revenues (fees, charges, recoveries). Generally available "
            "for the operations that generated them; subject to the Comptroller General's "
            "revenue-expenditure matching requirements."
        ),
    },
    "K-12 SCHOOL TECH": {
        "type": "state-restricted",
        "text": (
            "K-12 School Technology funds — restricted to technology infrastructure and "
            "services for public schools. Derived from the Education Technology Act "
            "recurring appropriation."
        ),
    },
    "INVENTORY REVOLVING": {
        "type": "operating",
        "text": (
            "Inventory revolving fund — self-replenishing fund for procurement and "
            "resale of supplies. Restricted to inventory operations; surpluses "
            "cannot be diverted to general agency operations."
        ),
    },
    "CAP RES FD OPER": {
        "type": "other-restricted",
        "text": (
            "Capital Reserve Fund — restricted to capital projects and major equipment "
            "purchases as defined in the Capital Reserve Fund Act. Expenditures "
            "require separate legislative authorization."
        ),
    },
    "MEDICAID ASST PAY": {
        "type": "federal-restricted",
        "text": (
            "Medicaid Assistance Payments — federal Title XIX pass-through restricted "
            "to Medicaid-eligible health and related services. Subject to federal "
            "Uniform Guidance (2 CFR 200) and DHHS matching requirements."
        ),
    },
    "RESTRICTED FUNDS": {
        "type": "other-restricted",
        "text": (
            "Restricted state funds — earmarked use; refer to budget proviso language "
            "or fund statute for the specific restriction. Contact Financial Services "
            "before obligating for a new purpose."
        ),
    },
    "AFS-SC FIRST STEP-OT": {
        "type": "state-restricted",
        "text": (
            "SC First Steps — state appropriation for early childhood programs "
            "administered by SC First Steps to School Readiness. Restricted to "
            "First Steps statutory purposes (Title 20, Ch. 7)."
        ),
    },
    "EDUCATION LOTTERY": {
        "type": "state-restricted",
        "text": (
            "Education Lottery proceeds — restricted by the SC Education Lottery Act "
            "(Title 59, Ch. 150) to specific education programs such as ETV, K-5 reading, "
            "LIFE scholarships, and capital. May not be used for general operations."
        ),
    },
    "EDUC SCHOLARSHIP FD": {
        "type": "state-restricted",
        "text": (
            "Education Scholarship Fund — restricted to scholarship and award programs "
            "as defined in the fund's enabling statute. Disbursements require "
            "verification of recipient eligibility."
        ),
    },
    "EDUC IMPROVEMENT": {
        "type": "state-restricted",
        "text": (
            "Education Improvement Act (EIA, Title 59, Ch. 21) — restricted to "
            "EIA-eligible programs and teacher-pay enhancements. Statute expressly "
            "prohibits use for non-EIA purposes. EIA funds have separate financial "
            "reporting requirements to the General Assembly."
        ),
    },
    "AFS-FIRST STEPS P&A": {
        "type": "state-restricted",
        "text": (
            "SC First Steps Policy & Accountability sub-fund — restricted to policy, "
            "evaluation, and accountability activities within the First Steps program. "
            "See AFS-SC FIRST STEP-OT for broader First Steps context."
        ),
    },
    "AFS-FIRST STEPS PR4K": {
        "type": "state-restricted",
        "text": (
            "SC First Steps Pre-K sub-fund — restricted to voluntary pre-kindergarten "
            "program services and supports. May not be commingled with K-12 operating funds."
        ),
    },
    "AFS-FIRST STEPS CHIL": {
        "type": "state-restricted",
        "text": (
            "SC First Steps Child Development sub-fund — restricted to child development "
            "services and family support programs operated under the First Steps umbrella."
        ),
    },
    "FEDERAL OPERATING": {
        "type": "federal-restricted",
        "text": (
            "Federal operating funds — pass-through from the U.S. Department of Education "
            "for ongoing federal programs (e.g., Title I Part A, Perkins, McKinney-Vento). "
            "Restricted by grant terms; subject to federal Uniform Guidance (2 CFR 200)."
        ),
    },
    "FEDERAL": {
        "type": "federal-restricted",
        "text": (
            "Federal pass-through funds — restricted by the originating federal grant "
            "terms. Expenditures must satisfy federal allowability, allocability, and "
            "reasonableness standards under 2 CFR 200."
        ),
    },
    "FEDERAL FUNDS": {
        "type": "federal-restricted",
        "text": (
            "Federal Funds — broad federal pass-through category. Each sub-grant has "
            "its own restriction and period of availability. Consult Grant Services "
            "for the specific CFDA/ALN and allowable cost guidance before obligating."
        ),
    },
    "CRRSAA - 2021": {
        "type": "federal-restricted",
        "text": (
            "Coronavirus Response and Relief Supplemental Appropriations Act (CRRSAA) "
            "funds — one-time COVID relief restricted to allowable ESSER II uses. "
            "Obligation and liquidation deadlines have passed; contact Grant Services "
            "if any balance remains."
        ),
    },
    "ARP - ESSER": {
        "type": "federal-restricted",
        "text": (
            "American Rescue Plan ESSER (Elementary and Secondary School Emergency "
            "Relief) — one-time COVID relief. Restricted to allowable ESSER III uses. "
            "Federal obligation deadline: 2024-09-30; liquidation deadline: 2026-01-28. "
            "Any unexpended balance after liquidation must be returned to ED."
        ),
    },
    "SCHOOL FOOD SERV-FED": {
        "type": "federal-restricted",
        "text": (
            "School Food Service — federal reimbursement under the National School "
            "Lunch and School Breakfast programs (USDA). Restricted exclusively to "
            "child nutrition services; may not be transferred to non-food-service uses."
        ),
    },
    "FED INTERFD/AGY - PT": {
        "type": "federal-restricted",
        "text": (
            "Federal inter-fund / inter-agency pass-through — federal dollars "
            "redistributed between state agencies or funds. Spending restrictions "
            "follow the originating federal program's terms."
        ),
    },
    "AFS-FIRST STEPS-FED": {
        "type": "federal-restricted",
        "text": (
            "SC First Steps — federal sub-fund (Head Start match, CCDF, or similar). "
            "Restricted to federal program purposes; requires separate federal "
            "reporting and is subject to 2 CFR 200 Uniform Guidance."
        ),
    },
    "HR PAYROLL TEMP FUND": {
        "type": "unknown",
        "text": (
            "Temporary HR payroll fund — no fund code matched in the SAP fund registry. "
            "No budget or actuals have posted in FY25 or FY26. Treat as a staging "
            "account; consult Financial Services before using for any obligation."
        ),
    },
}

# Fallback for any Fund_Name not in the dict above
UNKNOWN_FUND: dict[str, str] = {
    "type": "unknown",
    "text": (
        "Restriction details not catalogued. Add an entry to FUND_RESTRICTIONS in "
        "app_internal/fund_metadata.py with the exact Fund_Name string from BEx."
    ),
}


def get_fund_restriction(fund_name: str | None) -> dict[str, str]:
    """Return restriction metadata for a fund name.

    Performs a case-insensitive prefix match so minor trailing variants
    (e.g. extra spaces) still resolve. Falls back to UNKNOWN_FUND.
    """
    if not fund_name:
        return UNKNOWN_FUND
    name = fund_name.strip()
    if name in FUND_RESTRICTIONS:
        return FUND_RESTRICTIONS[name]
    # Case-insensitive fallback
    name_upper = name.upper()
    for key, val in FUND_RESTRICTIONS.items():
        if key.upper() == name_upper:
            return val
    return UNKNOWN_FUND


# Type badge colors for the restriction type field
RESTRICTION_TYPE_CSS: dict[str, str] = {
    "state-unrestricted": "fund-badge-unrestricted",
    "state-restricted":   "fund-badge-state",
    "federal-restricted": "fund-badge-federal",
    "other-restricted":   "fund-badge-other",
    "operating":          "fund-badge-operating",
    "unknown":            "fund-badge-unknown",
}

RESTRICTION_TYPE_LABEL: dict[str, str] = {
    "state-unrestricted": "State — Unrestricted",
    "state-restricted":   "State — Restricted",
    "federal-restricted": "Federal — Restricted",
    "other-restricted":   "Other — Restricted",
    "operating":          "Operating Revenue",
    "unknown":            "Unknown",
}
