"""Kenyan statutory payroll engine — pure functions, no database.

Computes one employee's monthly payslip: NSSF (Tier I/II), SHIF, the
Affordable Housing Levy, PAYE (graduated bands less personal relief) and the
employer-side costs (NSSF match, Housing Levy match, NITA).

Rules are versioned by effective date (RULESETS below) rather than hard-coded,
because these rates change with nearly every Finance Act. A payroll for a
given month is always computed with the ruleset in force for that month, so
re-printing an old payslip reproduces the numbers that were actually paid.

The current ruleset reflects the law as understood at the time of writing:
  * PAYE bands per the Finance Act 2023; personal relief KES 2,400/month
  * SHIF 2.75% of gross pay, minimum KES 300 (Social Health Insurance Act 2023)
  * Housing Levy 1.5% employee + 1.5% employer (Affordable Housing Act 2024)
  * SHIF, Housing Levy and NSSF are deductible before PAYE (Tax Laws
    (Amendment) Act 2024, from 27 Dec 2024); pension relief cap KES 30,000
  * NSSF Act 2013 year-3 limits from Feb 2025: 6% each side, lower earnings
    limit KES 8,000, upper earnings limit KES 72,000
  * NITA levy KES 50 per employee per month (employer only)
Verify against current KRA/NSSF/SHA guidance before relying on it for filing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")


def q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PayrollRules:
    effective_from: date
    # (upper bound of band, rate); None = no upper bound
    paye_bands: tuple[tuple[Decimal | None, Decimal], ...]
    personal_relief: Decimal
    nssf_rate: Decimal
    nssf_lower_limit: Decimal
    nssf_upper_limit: Decimal
    shif_rate: Decimal
    shif_minimum: Decimal
    housing_levy_rate: Decimal
    nita_per_employee: Decimal
    pension_relief_cap: Decimal
    disability_exemption: Decimal
    statutory_deductions_pre_tax: bool  # SHIF + Housing Levy reduce taxable pay


RULESETS: list[PayrollRules] = [
    PayrollRules(
        effective_from=date(2025, 2, 1),
        paye_bands=(
            (Decimal("24000"), Decimal("0.10")),
            (Decimal("32333"), Decimal("0.25")),
            (Decimal("500000"), Decimal("0.30")),
            (Decimal("800000"), Decimal("0.325")),
            (None, Decimal("0.35")),
        ),
        personal_relief=Decimal("2400"),
        nssf_rate=Decimal("0.06"),
        nssf_lower_limit=Decimal("8000"),
        nssf_upper_limit=Decimal("72000"),
        shif_rate=Decimal("0.0275"),
        shif_minimum=Decimal("300"),
        housing_levy_rate=Decimal("0.015"),
        nita_per_employee=Decimal("50"),
        pension_relief_cap=Decimal("30000"),
        disability_exemption=Decimal("150000"),
        statutory_deductions_pre_tax=True,
    ),
]


def rules_for(period: date) -> PayrollRules:
    applicable = [r for r in RULESETS if r.effective_from <= period]
    if not applicable:
        return RULESETS[0]
    return max(applicable, key=lambda r: r.effective_from)


@dataclass
class PayItem:
    name: str
    amount: Decimal
    taxable: bool = True  # earnings: counts toward gross taxable pay
    pre_tax: bool = False  # deductions: pension-type, deductible before PAYE


@dataclass
class PayslipInput:
    basic_salary: Decimal
    earnings: list[PayItem] = field(default_factory=list)
    deductions: list[PayItem] = field(default_factory=list)
    has_disability_exemption: bool = False
    nssf_exempt: bool = False  # e.g. employees above retirement age
    housing_levy_exempt: bool = False


@dataclass
class PayslipResult:
    gross_pay: Decimal  # every earning, taxable or not
    taxable_earnings: Decimal
    nssf_tier1: Decimal
    nssf_tier2: Decimal
    nssf_employee: Decimal
    nssf_employer: Decimal
    shif: Decimal
    housing_levy_employee: Decimal
    housing_levy_employer: Decimal
    pension_relief: Decimal  # pre-tax pension deductions actually allowed
    taxable_pay: Decimal
    paye_before_relief: Decimal
    personal_relief: Decimal
    paye: Decimal
    other_deductions: Decimal  # post-tax deductions + pre-tax pension deductions
    total_deductions: Decimal
    net_pay: Decimal
    nita: Decimal
    employer_cost: Decimal


def nssf(pensionable: Decimal, rules: PayrollRules) -> tuple[Decimal, Decimal]:
    tier1_base = min(pensionable, rules.nssf_lower_limit)
    tier2_base = max(min(pensionable, rules.nssf_upper_limit) - rules.nssf_lower_limit, ZERO)
    return q2(tier1_base * rules.nssf_rate), q2(tier2_base * rules.nssf_rate)


def paye_on(taxable: Decimal, rules: PayrollRules) -> Decimal:
    tax = ZERO
    lower = ZERO
    for upper, rate in rules.paye_bands:
        if taxable <= lower:
            break
        band_top = taxable if upper is None else min(taxable, upper)
        tax += (band_top - lower) * rate
        if upper is None:
            break
        lower = upper
    return q2(tax)


def compute_payslip(data: PayslipInput, rules: PayrollRules) -> PayslipResult:
    basic = q2(data.basic_salary)
    taxable_earnings = basic + sum((q2(e.amount) for e in data.earnings if e.taxable), ZERO)
    gross_pay = basic + sum((q2(e.amount) for e in data.earnings), ZERO)

    tier1, tier2 = (ZERO, ZERO) if data.nssf_exempt else nssf(taxable_earnings, rules)
    nssf_employee = tier1 + tier2
    nssf_employer = nssf_employee

    shif = ZERO
    if taxable_earnings > 0:
        shif = max(q2(taxable_earnings * rules.shif_rate), rules.shif_minimum)

    housing_employee = ZERO if data.housing_levy_exempt else q2(taxable_earnings * rules.housing_levy_rate)
    housing_employer = housing_employee

    # NSSF and voluntary pension share one relief cap.
    pre_tax_pension = sum((q2(d.amount) for d in data.deductions if d.pre_tax), ZERO)
    pension_room = max(rules.pension_relief_cap - nssf_employee, ZERO)
    pension_relief = min(pre_tax_pension, pension_room)

    deductible = nssf_employee + pension_relief
    if rules.statutory_deductions_pre_tax:
        deductible += shif + housing_employee
    taxable_pay = max(taxable_earnings - deductible, ZERO)

    chargeable = taxable_pay
    if data.has_disability_exemption:
        chargeable = max(chargeable - rules.disability_exemption, ZERO)
    paye_before_relief = paye_on(chargeable, rules)
    relief = min(rules.personal_relief, paye_before_relief)
    paye = paye_before_relief - relief

    other_deductions = sum((q2(d.amount) for d in data.deductions), ZERO)
    total_deductions = paye + nssf_employee + shif + housing_employee + other_deductions
    nita = rules.nita_per_employee

    return PayslipResult(
        gross_pay=gross_pay,
        taxable_earnings=taxable_earnings,
        nssf_tier1=tier1,
        nssf_tier2=tier2,
        nssf_employee=nssf_employee,
        nssf_employer=nssf_employer,
        shif=shif,
        housing_levy_employee=housing_employee,
        housing_levy_employer=housing_employer,
        pension_relief=pension_relief,
        taxable_pay=taxable_pay,
        paye_before_relief=paye_before_relief,
        personal_relief=relief,
        paye=paye,
        other_deductions=other_deductions,
        total_deductions=total_deductions,
        net_pay=gross_pay - total_deductions,
        nita=nita,
        employer_cost=gross_pay + nssf_employer + housing_employer + nita,
    )
