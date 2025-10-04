import math
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# Try Altair for the nice stacked chart (fallback to table if not available)
try:
    import altair as alt
    ALT_AVAILABLE = True
except Exception:
    ALT_AVAILABLE = False

# =========================
# ---- Tax Settings ----
# =========================

FEDERAL_BRACKETS_2025_SINGLE = [
    (0, 0.10),
    (11925, 0.12),
    (48475, 0.22),
    (103350, 0.24),
    (197300, 0.32),
    (250525, 0.35),
    (626350, 0.37),
]

FEDERAL_BRACKETS_2025_MARRIED = [
    (0, 0.10),
    (23850, 0.12),
    (96950, 0.22),
    (206700, 0.24),
    (394600, 0.32),
    (501050, 0.35),
    (752600, 0.37),
]

# Virginia brackets use "start-of-bracket" style as well
VIRGINIA_BRACKETS_2025 = [
    (0, 0.02),
    (3000, 0.03),
    (5000, 0.05),
    (17000, 0.0575),
]

STANDARD_DEDUCTION_2025_SINGLE = 15000
STANDARD_DEDUCTION_2025_MARRIED = 30000

# =========================
# ---- Helpers ----
# =========================

def calculate_tax(taxable_income: float, brackets: list[tuple[int, float]]) -> float:
    """
    Calculates tax for 'start-of-bracket' style brackets:
    brackets: list of (start_income, rate). The last bracket applies to infinity.
    """
    if taxable_income <= 0:
        return 0.0

    tax = 0.0
    n = len(brackets)
    for i, (start, rate) in enumerate(brackets):
        end = brackets[i + 1][0] if i + 1 < n else float('inf')
        if taxable_income <= start:
            break
        span = min(taxable_income, end) - start
        if span > 0:
            tax += span * rate
    return max(tax, 0.0)

def money(x):  # quick pretty money format
    return f"${x:,.0f}"

def pct(x):
    return f"{x:.1%}"

# =========================
# ---- Streamlit App ----
# =========================

st.set_page_config(page_title="🔥 FIRE Tax + FI Planner 2025", layout="wide")
st.title("🔥 FIRE Tax + FI Planner 2025 (Federal + Virginia) 🔥")

with st.expander("Assumptions", expanded=False):
    st.markdown(
        "- 2025 **federal** & **Virginia** tax brackets (start-of-bracket).\n"
        "- Uses the **standard deduction** based on filing status.\n"
        "- Virginia 529 deduction capped at **$4,000**.\n"
        "- Pension contributions reduce AGI (treated like employer/mandatory pre-tax).\n"
        "- **Safe Withdrawal Rate (SWR)** drives FI targets (default 4%).\n"
        "- Simplified model (ignores credits/phaseouts, SS/Medicare, LTCG/qualified dividends, etc.)."
    )

# ---- Sidebar Inputs ----
st.sidebar.header("Filing Status")
filing_status = st.sidebar.selectbox("Select Filing Status", ["Single", "Married Filing Jointly"])

st.sidebar.header("Income & Expenses")
gross_salary = st.sidebar.number_input("Gross Salary ($)", value=100000, step=1000)
pension_percent = st.sidebar.slider("Pension Contribution (% of Salary)", 0, 20, 5) / 100
annual_expenses = st.sidebar.number_input("Annual Expenses ($)", value=40000, step=1000)

# 🔥 NEW: Safe Withdrawal Rate control
swr_percent = st.sidebar.number_input("Safe Withdrawal Rate (%)", min_value=2.0, max_value=7.0, value=4.0, step=0.1)
swr = swr_percent / 100.0  # decimal; e.g., 4% => 0.04

current_investments = st.sidebar.number_input("Current Total Investment Value ($)", value=50000, step=1000)
expected_return = st.sidebar.number_input("Expected Annual Investment Growth Rate (%)", value=5.0, step=0.1) / 100
retirement_age = st.sidebar.number_input("Normal Retirement Age", value=58.5, step=0.5)

st.sidebar.header("Choose Accounts to Contribute To")
account_types = {
    "403(b) Traditional": st.sidebar.checkbox("403(b) Traditional"),
    "403(b) Roth": st.sidebar.checkbox("403(b) Roth"),
    "457(b) Traditional": st.sidebar.checkbox("457(b) Traditional"),
    "457(b) Roth": st.sidebar.checkbox("457(b) Roth"),
    "401(a) Employee": st.sidebar.checkbox("401(a) Employee Contribution"),
    "401(a) Employer": st.sidebar.checkbox("401(a) Employer Contribution"),
    "Solo 401(k) Employee": st.sidebar.checkbox("Solo 401(k) Employee Contribution"),
    "Solo 401(k) Employer": st.sidebar.checkbox("Solo 401(k) Employer Contribution"),
    "SEP IRA": st.sidebar.checkbox("SEP IRA"),
    "SIMPLE IRA": st.sidebar.checkbox("SIMPLE IRA"),
    "Traditional IRA": st.sidebar.checkbox("Traditional IRA"),
    "Roth IRA": st.sidebar.checkbox("Roth IRA"),
    "HSA": st.sidebar.checkbox("HSA"),
    "FSA": st.sidebar.checkbox("FSA"),
    "529 Plan": st.sidebar.checkbox("529 Plan"),
    "ESA": st.sidebar.checkbox("ESA"),
    "Taxable Brokerage Account": st.sidebar.checkbox("Taxable Brokerage Savings"),
}

st.sidebar.header("Annual Contributions ($/year)")
contributions = {}
for account, enabled in account_types.items():
    if enabled:
        contributions[account] = st.sidebar.number_input(f"{account} Contribution ($)", value=0, step=500)

# ---- Brackets & Deduction by Filing Status ----
if filing_status == "Single":
    federal_brackets = FEDERAL_BRACKETS_2025_SINGLE
    standard_deduction = STANDARD_DEDUCTION_2025_SINGLE
else:
    federal_brackets = FEDERAL_BRACKETS_2025_MARRIED
    standard_deduction = STANDARD_DEDUCTION_2025_MARRIED

# =========================
# ---- Main Calculations ----
# =========================

if st.sidebar.button("🚀 Run FIRE Simulation"):
    # Pension is pre-tax and always included in both baseline & scenario
    pension_contribution = gross_salary * pension_percent

    # --- Scenario with user-selected contributions ---
    agi = gross_salary - pension_contribution

    # Pre-tax (AGI-reducing) contributions
    agi_reducing_accounts = [
        "403(b) Traditional", "457(b) Traditional",
        "401(a) Employee", "Solo 401(k) Employee",
        "SEP IRA", "SIMPLE IRA", "Traditional IRA",
        "HSA", "FSA"
    ]
    for acct in agi_reducing_accounts:
        agi -= contributions.get(acct, 0)

    # Virginia 529 (deduct up to $4,000)
    va_529_deduction = min(contributions.get("529 Plan", 0), 4000)
    agi -= va_529_deduction

    taxable_income = max(agi - standard_deduction, 0)

    federal_tax = calculate_tax(taxable_income, federal_brackets)
    state_tax = calculate_tax(taxable_income, VIRGINIA_BRACKETS_2025)
    total_tax = federal_tax + state_tax

    effective_tax_rate = (total_tax / gross_salary) if gross_salary > 0 else 0.0
    after_tax_income = gross_salary - pension_contribution - total_tax

    total_savings = sum(contributions.values())

    # Post-tax savings = total elective savings NOT counted as AGI-reducing (i.e., Roth/taxable/etc.)
    post_tax_savings = total_savings - sum(contributions.get(a, 0) for a in agi_reducing_accounts) - va_529_deduction
    disposable_income = after_tax_income - post_tax_savings

    # =========================
    # ---- FIRE Summary ----
    # =========================
    st.subheader("📋 FIRE Financial Summary")
    fire_summary = pd.DataFrame({
        "Metric": [
            "Adjusted Gross Income (AGI)",
            "Taxable Income",
            "Federal Taxes Paid",
            "Virginia State Taxes Paid",
            "Total Taxes Paid",
            "Effective Tax Rate (on Gross Salary)",
            "After-Tax Income (after pension & taxes)",
            "Total Annual Savings (all accounts)",
            "Savings Rate (on Gross Salary)",
            "Disposable Income (After Taxes & Post-Tax Savings)"
        ],
        "Amount": [
            money(agi),
            money(taxable_income),
            money(federal_tax),
            money(state_tax),
            money(total_tax),
            pct(effective_tax_rate),
            money(after_tax_income),
            money(total_savings),
            pct(total_savings / gross_salary if gross_salary > 0 else 0.0),
            money(disposable_income)
        ]
    })
    st.dataframe(fire_summary)

    # ---- Contributions Table ----
    st.subheader("📚 Contributions Detail")
    contribs = sorted([(k, v) for k, v in contributions.items()], key=lambda x: x[0])
    st.dataframe(pd.DataFrame(contribs, columns=["Account", "Annual Contribution ($)"]))

    # =========================
    # ---- Contribution Impact (Fixed) ----
    # =========================
    st.subheader("🚀 Contribution Impact Summary")

    # Baseline keeps pension but removes elective contributions
    baseline_pension_contribution = pension_contribution
    baseline_agi = gross_salary - baseline_pension_contribution
    baseline_taxable_income = max(baseline_agi - standard_deduction, 0)
    baseline_federal_tax = calculate_tax(baseline_taxable_income, federal_brackets)
    baseline_state_tax = calculate_tax(baseline_taxable_income, VIRGINIA_BRACKETS_2025)
    baseline_total_tax = baseline_federal_tax + baseline_state_tax
    baseline_after_tax_income = gross_salary - baseline_pension_contribution - baseline_total_tax
    baseline_post_tax_savings = 0
    baseline_disposable_income = baseline_after_tax_income

    # KPIs
    col1, col2, col3 = st.columns(3)
    col1.metric("Δ Taxes Paid", money(baseline_total_tax - total_tax))
    col2.metric("Annual Savings (with contributions)", money(total_savings))
    col3.metric("Δ Disposable Income", money((after_tax_income - post_tax_savings) - baseline_disposable_income))

    # Stacked allocation of gross salary (how each $ is split)
    allocation_rows = [
        {"Scenario": "No Contributions",   "Category": "Pension",        "Amount": baseline_pension_contribution},
        {"Scenario": "No Contributions",   "Category": "Federal Taxes",  "Amount": baseline_federal_tax},
        {"Scenario": "No Contributions",   "Category": "State Taxes",    "Amount": baseline_state_tax},
        {"Scenario": "No Contributions",   "Category": "Savings",        "Amount": 0},
        {"Scenario": "No Contributions",   "Category": "Disposable",     "Amount": baseline_disposable_income},

        {"Scenario": "With Contributions", "Category": "Pension",        "Amount": pension_contribution},
        {"Scenario": "With Contributions", "Category": "Federal Taxes",  "Amount": federal_tax},
        {"Scenario": "With Contributions", "Category": "State Taxes",    "Amount": state_tax},
        {"Scenario": "With Contributions", "Category": "Savings",        "Amount": total_savings},
        {"Scenario": "With Contributions", "Category": "Disposable",     "Amount": disposable_income},
    ]
    alloc_df = pd.DataFrame(allocation_rows)

    st.caption("Share of gross salary by destination (pension, taxes, savings, disposable).")
    if ALT_AVAILABLE:
        chart = (
            alt.Chart(alloc_df)
            .mark_bar()
            .encode(
                x=alt.X('Scenario:N', title=None),
                y=alt.Y('sum(Amount):Q', stack='normalize', axis=alt.Axis(format='%')),
                color=alt.Color('Category:N', legend=alt.Legend(title='Allocation')),
                tooltip=[
                    alt.Tooltip('Scenario:N'),
                    alt.Tooltip('Category:N'),
                    alt.Tooltip('Amount:Q', title='Amount', format='$,.0f')
                ]
            )
            .properties(height=300)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.warning("Altair not available. Showing allocation table instead.")
        st.dataframe(alloc_df.pivot_table(index="Category", columns="Scenario", values="Amount"))

    # Optional: Waterfall from Gross -> Disposable (With Contributions)
    with st.expander("💧 Show Waterfall: Gross → Disposable (With Contributions)", expanded=False):
        steps = [
            ("Gross Salary", gross_salary),
            ("− Pension", -pension_contribution),
            ("− Federal Taxes", -federal_tax),
            ("− State Taxes", -state_tax),
            ("= After-Tax Income", after_tax_income),
            ("− Post-Tax Savings", -post_tax_savings),
            ("= Disposable Income", disposable_income),
        ]

        wf_labels = [s[0] for s in steps]
        wf_values = [s[1] for s in steps]

        running = 0
        starts = []
        for v in wf_values:
            starts.append(running)
            running += v

        fig_wf, ax_wf = plt.subplots()
        for i, (label, value) in enumerate(steps):
            color = 'tab:green' if value >= 0 else 'tab:red'
            ax_wf.bar(i, value, bottom=starts[i], width=0.6, color=color)
            ax_wf.text(i, starts[i] + value / 2, money(abs(value)), ha='center', va='center', fontsize=9)

        ax_wf.set_xticks(range(len(wf_labels)))
        ax_wf.set_xticklabels(wf_labels, rotation=20, ha='right')
        ax_wf.set_ylabel("Dollars ($)")
        ax_wf.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f'${int(x):,}'))
        ax_wf.set_title("Gross → Disposable (With Contributions)")
        st.pyplot(fig_wf)

    # =========================
    # ---- Money Flow Pie ----
    # =========================
    st.subheader("📊 Money Flow Pie (Net of Pension)")
    base_after_pension = gross_salary - pension_contribution
    pie_labels = ["Federal Taxes", "State Taxes", "Savings", "Disposable Income"]
    pie_values = [federal_tax, state_tax, total_savings, max(disposable_income, 0)]

    if disposable_income < 0:
        st.warning(
            "Your post-tax savings exceed your after-tax income. Disposable income is negative; "
            "the pie clamps it to $0 for display."
        )

    fig1, ax1 = plt.subplots()
    if sum(v for v in pie_values) <= 0:
        ax1.text(0.5, 0.5, "No flow to display", ha='center', va='center')
    else:
        ax1.pie(pie_values, labels=pie_labels, autopct='%1.1f%%', startangle=90)
        ax1.axis('equal')
    st.caption(f"Pie represents allocation of **{money(base_after_pension)}** (gross minus pension).")
    st.pyplot(fig1)

    # =========================
    # ---- FI Milestones ----
    # =========================
    st.subheader("🌱 FI Milestones Projection (SWR-driven)")

    invest_value = current_investments
    annual_contrib = total_savings
    years = []
    balances = []

    # ---- SWR-driven FI targets ----
    # Full FI target is expenses divided by SWR (e.g., 25x for 4%).
    if swr <= 0:
        st.error("Safe Withdrawal Rate must be > 0%.")
        st.stop()

    full_fi_target = annual_expenses / swr
    lean_fi_target = (annual_expenses * 0.75) / swr
    chubby_fi_target = (annual_expenses * 1.20) / swr         # NEW: between Lean and Fat
    fat_fi_target = (annual_expenses * 1.50) / swr
    barista_fi_target = (annual_expenses * 0.50) / swr
    flamingo_fi_target = 0.50 * full_fi_target                 # NEW: hit 50% of Full FI

    # Coast FI: enough today to hit Full FI by retirement age with zero new contributions
    # years_to_retirement is treated as "retirement_age" years from now in this simplified model.
    years_to_retirement = retirement_age if retirement_age > 0 else 0
    coast_fi_target = full_fi_target / ((1 + expected_return) ** years_to_retirement) if expected_return > -1 else math.inf

    milestones = {
        "Coast FI": False,
        "Flamingo FI (50% of FI #)": False,       # NEW
        "Barista FI (50% Expenses)": False,
        "Lean FI (75% Expenses)": False,
        "Chubby FI (~120% Expenses)": False,      # NEW
        "Full FI (100% Expenses)": False,
        "Fat FI (150% Expenses)": False,
    }

    for year in range(1, 51):
        invest_value = invest_value * (1 + expected_return) + annual_contrib
        balances.append(invest_value)
        years.append(year)

        if not milestones["Coast FI"] and invest_value >= coast_fi_target:
            milestones["Coast FI"] = "✅ Already Achieved" if year == 1 else f"{year} years"

        if not milestones["Flamingo FI (50% of FI #)"] and invest_value >= flamingo_fi_target:
            milestones["Flamingo FI (50% of FI #)"] = "✅ Already Achieved" if year == 1 else f"{year} years"

        if not milestones["Barista FI (50% Expenses)"] and invest_value >= barista_fi_target:
            milestones["Barista FI (50% Expenses)"] = "✅ Already Achieved" if year == 1 else f"{year} years"

        if not milestones["Lean FI (75% Expenses)"] and invest_value >= lean_fi_target:
            milestones["Lean FI (75% Expenses)"] = "✅ Already Achieved" if year == 1 else f"{year} years"

        if not milestones["Chubby FI (~120% Expenses)"] and invest_value >= chubby_fi_target:
            milestones["Chubby FI (~120% Expenses)"] = "✅ Already Achieved" if year == 1 else f"{year} years"

        if not milestones["Full FI (100% Expenses)"] and invest_value >= full_fi_target:
            milestones["Full FI (100% Expenses)"] = "✅ Already Achieved" if year == 1 else f"{year} years"

        if not milestones["Fat FI (150% Expenses)"] and invest_value >= fat_fi_target:
            milestones["Fat FI (150% Expenses)"] = "✅ Already Achieved" if year == 1 else f"{year} years"

    milestone_table = pd.DataFrame(list(milestones.items()), columns=["Milestone", "Time to Achieve"])
    st.table(milestone_table)

    # ---- Milestone Explanations ----
    st.subheader("📖 What the Milestones Mean (SWR = " + f"{swr_percent:.1f}%" + ")")
    st.markdown(f"""
    - **Coast FI**: Invested today grows to your **Full FI** target by age **{retirement_age}** with no additional contributions.
    - **Flamingo FI**: Reach **~50%** of your Full FI number, then let compounding do the rest while you downshift to part-time/semi-retirement.
    - **Barista FI**: Portfolio covers **50%** of expenses; part-time work covers the rest.
    - **Lean FI**: Portfolio can support **75%** of expenses at your chosen SWR.
    - **Chubby FI**: Comfortable middle-ground—**~120%** of expenses (between Lean and Fat).
    - **Full FI**: Portfolio supports **100%** of expenses at your chosen SWR.
    - **Fat FI**: Portfolio supports **150%** of expenses (extra cushion/luxury).
    """)

    # ---- Investment Growth Over Time ----
    st.subheader("📈 Investment Growth Over Time")
    fig2, ax2 = plt.subplots()
    ax2.plot(years, balances, label="Projected Portfolio Value")

    # Show FI targets as reference lines (Full + Chubby + Lean)
    ax2.axhline(y=full_fi_target, linestyle='--', label=f'Full FI ({money(full_fi_target)})')
    ax2.axhline(y=chubby_fi_target, linestyle=':', label=f'Chubby FI ({money(chubby_fi_target)})')
    ax2.axhline(y=lean_fi_target, linestyle='-.', label=f'Lean FI ({money(lean_fi_target)})')

    ax2.yaxis.set_major_formatter(
        ticker.FuncFormatter(lambda x, _: f'${int(x/1000)}k' if x < 1_000_000 else f'${x/1_000_000:.1f}M')
    )
    ax2.set_xlabel("Years")
    ax2.set_ylabel("Portfolio Value ($)")
    ax2.legend()
    st.pyplot(fig2)
