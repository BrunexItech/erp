"""Hand-worked examples for the statutory engine. Each figure is computed in
the comment beside it so a reviewer can check the arithmetic, not just trust
the code."""

from datetime import date
from decimal import Decimal

from app.modules.hr.kenya_payroll import PayItem, PayslipInput, compute_payslip, nssf, paye_on, rules_for

RULES = rules_for(date(2026, 9, 1))


def test_nssf_tiers():
    assert nssf(Decimal("5000"), RULES) == (Decimal("300.00"), Decimal("0.00"))  # 6% of 5,000
    assert nssf(Decimal("50000"), RULES) == (Decimal("480.00"), Decimal("2520.00"))  # 6% of 8,000 / 42,000
    assert nssf(Decimal("200000"), RULES) == (Decimal("480.00"), Decimal("3840.00"))  # capped at 72,000


def test_paye_bands():
    assert paye_on(Decimal("24000"), RULES) == Decimal("2400.00")
    # 2,400 + 8,333 x 25% (2,083.25) + 7,667 x 30% (2,300.10)
    assert paye_on(Decimal("40000"), RULES) == Decimal("6783.35")
    # up to 500,000: 2,400 + 2,083.25 + 467,667 x 30% (140,300.10) = 144,783.35
    # + 300,000 x 32.5% = 97,500 ; + 200,000 x 35% = 70,000
    assert paye_on(Decimal("1000000"), RULES) == Decimal("312283.35")


def test_mid_income_payslip():
    """Basic 50,000 + taxable house allowance 10,000 = 60,000 taxable."""
    result = compute_payslip(
        PayslipInput(
            basic_salary=Decimal("50000"),
            earnings=[PayItem("House allowance", Decimal("10000"))],
            deductions=[PayItem("SACCO", Decimal("2000"))],
        ),
        RULES,
    )
    assert result.gross_pay == Decimal("60000.00")
    # NSSF: 480 + 6% x 52,000 = 3,120 -> 3,600
    assert result.nssf_employee == Decimal("3600.00")
    assert result.shif == Decimal("1650.00")  # 2.75% x 60,000
    assert result.housing_levy_employee == Decimal("900.00")  # 1.5% x 60,000
    # taxable = 60,000 - 3,600 - 1,650 - 900 = 53,850
    assert result.taxable_pay == Decimal("53850.00")
    # 2,400 + 2,083.25 + (53,850 - 32,333) x 30% = 6,455.10 -> 10,938.35 ; less 2,400
    assert result.paye_before_relief == Decimal("10938.35")
    assert result.paye == Decimal("8538.35")
    # net = 60,000 - (8,538.35 + 3,600 + 1,650 + 900 + 2,000)
    assert result.net_pay == Decimal("43311.65")
    assert result.employer_cost == Decimal("64550.00")  # + 3,600 NSSF + 900 AHL + 50 NITA


def test_low_income_has_no_paye_and_shif_minimum():
    result = compute_payslip(PayslipInput(basic_salary=Decimal("10000")), RULES)
    assert result.shif == Decimal("300")  # 2.75% = 275, below the 300 floor
    assert result.paye == Decimal("0")  # 1,000-ish tax fully covered by personal relief
    assert result.personal_relief <= Decimal("2400")


def test_non_taxable_earnings_and_pension_relief():
    result = compute_payslip(
        PayslipInput(
            basic_salary=Decimal("100000"),
            earnings=[PayItem("Mileage reimbursement", Decimal("5000"), taxable=False)],
            deductions=[PayItem("Pension", Decimal("40000"), pre_tax=True)],
        ),
        RULES,
    )
    assert result.gross_pay == Decimal("105000.00")
    assert result.taxable_earnings == Decimal("100000.00")
    # NSSF 4,320 uses part of the 30,000 cap -> pension relief 25,680
    assert result.pension_relief == Decimal("25680.00")
    # taxable = 100,000 - 4,320 - 25,680 - 2,750 SHIF - 1,500 AHL
    assert result.taxable_pay == Decimal("65750.00")


def test_disability_exemption():
    result = compute_payslip(
        PayslipInput(basic_salary=Decimal("120000"), has_disability_exemption=True), RULES
    )
    assert result.paye == Decimal("0")
