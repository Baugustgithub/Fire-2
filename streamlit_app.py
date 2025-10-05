import math
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# Try Altair for the stacked chart (fallback to table if not available)
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

# Virginia brackets (start-of-bracket style)
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
    """Tax for 'start-of-bracket' style brackets."""
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

def money(x):  # pretty money format
    return f"${x:,.0f}"

def pct(x):
    return f"{x:.1%}"

def normalize_return(r):
    """
    Defensive normalization for user-supplied returns.
    - If r is None/invalid: 0
    - If r > 1.5 and r <= 100, assume percent (30 -> 0.30)
    - If r > 100, divide by 100 too (just in case)
    - Clamp to [-90%, +200%] to keep charts sane (permissive)
    """
    if r is None:
        return 0.0
    try:
        r_float = float(r)
    except Exception:
        return 0.0
    if r_float > 1.5:
        r_float = r_float / 100.0
    return max(-0.90, min(2.00, r_float))

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
        "- **Safe Withdrawal Rate (SWR)** drives FI targets (you control the %).\n"
        "- Simulation horizon uses **Years until retirement = Target age − Current age**.\n"
        "- Simplified model: ignores credits/phaseouts, SS/Medicare, LTCG/qualified dividends, NIIT, etc."
    )

# ---- Sidebar Inputs ----
st.sidebar.header("Filing Status")
filing_status = st.sidebar.selectbox("Select Filing Status", ["Single", "Married Filing Jointly"])

st.sidebar.header("Income & Expenses")
gross_salary = st.sidebar.number_input("Gross Salary ($)", value=150000, step=1000)
pension_percent = st.sidebar.slider("Pension Contribution (% of Salary)", 0, 20, 5) / 100
annual_expenses = st.sidebar.number_input("Annual Expenses ($)", value=45000, step=1000)

# SWR control
swr_percent = st.sidebar.number_input("Safe Withdrawal Rate (%)", min_value=2.0, max_value=7.0, value=4.0, step=0.1)
swr = swr_percent / 100.0

# Horizon inputs (FIX)
st.sidebar.header("Retirement Horizon")
current_age = st.sidebar.number_input("Current age", value=40, step=1, min_value=0)
target_age = st.sidebar.number_input("Target retirement age", value=58, step=1, min_value=0)
years_until_ret = max(1, int(round(target_age - current_age)))  # ≥1 year

# Portfolio-level defaults
current_investments = st.sidebar.number_input("Current Total Investment Value ($)", value=50000, step=1000)
expected_return = st.sidebar.number_input("Default Expected Annual Investment Growth Rate (%)", value=5.0, step=0.1) / 100

# ===========================================
# ---- Accounts (Core vs More, with Crypto) --
# ===========================================

st.sidebar.header("Choose Accounts to Contribute To")

# Core, short list:
with st.sidebar.container():
    st.markdown("**Core account types**")
    core_accounts = {
        "Brokerage": st.checkbox("Brokerage"),
        "Crypto": st.checkbox("Crypto"),
        "Traditional IRA": st.checkbox("Traditional IRA"),
        "Roth IRA": st.checkbox("Roth IRA", value=True),  # pre-check per your scenario
        "457(b) Traditional": st.checkbox("457(b) Traditional", value=True),  # pre-check
        "457(b) Roth": st.checkbox("457(b) Roth"),
        "403(b) Traditional": st.checkbox("403(b) Traditional"),
        "403(b) Roth": st.checkbox("403(b) Roth"),
    }

# Everything else collapsed:
with st.sidebar.expander("More account types (optional)"):
    more_accounts = {
        "401(a) Employee": st.checkbox("401(a) Employee Contribution"),
        "401(a) Employer": st.checkbox("401(a) Employer Contribution"),
        "Solo 401(k) Employee": st.checkbox("Solo 401(k) Employee Contribution"),
        "Solo 401(k) Employer": st.checkbox("Solo 401(k) Employer Contribution"),
        "SEP IRA": st.checkbox("SEP IRA"),
        "SIMPLE IRA": st.checkbox("SIMPLE IRA"),
        "HSA": st.checkbox("HSA"),
        "FSA": st.checkbox("FSA"),
        "529 Plan": st.checkbox("529 Plan"),
        "ESA": st.checkbox("ESA"),
    }

# Contributions
st.sidebar.header("Annual Contributions ($/year)")
contributions = {}
for account, enabled in {**core_accounts, **more_accounts}.items():
    if enabled:
        key = ("core_" if account in core_accounts else "more_") + account
        default_val = 0
        if account == "457(b) Traditional":
            default_val = 23500
        if account == "Crypto":
            default_val = 12000
        if account == "Roth IRA":
            default_val = 5000
        contributions[account] = st.sidebar.number_input(f"{account} Contribution ($)", value=default_val, step=500, key=key)

# ---- Contribution limits helper (UPDATED 2025) ----
with st.sidebar.expander("Contribution limit tips (2025, edit if needed)"):
    st.caption("Quick-reference numbers. Verify catch-ups / plan quirks with your provider.")
    hints = {
        # IRS: IRA=7k; 50+ catch-up +$1k
        "IRA (Traditional/Roth) combined": st.number_input("IRA annual limit ($)", value=7000, step=500, key="hint_ira"),
        # IRS: 401k/403b/457b elective deferral = 23,500 (50+ catch-up +7,500; some plans 60–63 higher catch-up)
        "457(b) employee deferral": st.number_input("457(b) annual limit ($)", value=23500, step=500, key="hint_457"),
        "403(b) employee deferral": st.number_input("403(b) annual limit ($)", value=23500, step=500, key="hint_403"),
        # HSA 2025 family = 8,550; self-only 4,300 (55+ catch-up +1,000)
        "HSA (family)": st.number_input("HSA annual limit ($)", value=8550, step=50, key="hint_hsa"),
        # Health FSA 2025 = 3,300; rollover 660
        "FSA (health)": st.number_input("FSA annual limit ($)", value=3300, step=50, key="hint_fsa"),
        # 415(c) overall DC limit 2025 = 70,000 (employee + employer)
        "415(c) overall DC limit": st.number_input("Overall DC limit (§415c) ($)", value=70000, step=1000, key="hint_415c"),
        # VA 529 state deduction hint (per taxpayer, per account rules vary)
        "529 (VA deduction hint)": st.number_input("VA 529 deductible amount used ($)", value=4000, step=500, key="hint_529"),
    }
    st.caption("These are **warnings only** (non-blocking). Catch-ups vary by age & plan; adjust as needed.")

# ---- Brackets & Deduction by Filing Status ----
if filing_status == "Single":
    federal_brackets = FEDERAL_BRACKETS_2025_SINGLE
    standard_deduction = STANDARD_DEDUCTION_2025_SINGLE
else:
    federal_brackets = FEDERAL_BRACKETS_2025_MARRIED
    standard_deduction = STANDARD_DEDUCTION_2025_MARRIED

# ==============================================
# ---- Granular Balances & Per-Account Returns --
# ==============================================

st.sidebar.header("Granular balances & returns (optional)")
granular_mode = st.sidebar.checkbox("Enable granular balances & per-account returns")

ALL_ACCOUNTS = list(core_accounts.keys()) + list(more_accounts.keys())
account_start_balances = {}
account_returns = {}

if granular_mode:
    st.sidebar.caption("Specify starting balances & expected returns for selected accounts. Remainder → 'Other Investments'.")
    chosen_accounts = st.sidebar.multiselect(
        "Accounts with explicit starting balance & return",
        options=ALL_ACCOUNTS,
        default=["Brokerage", "Crypto"]
    )
    for acct in chosen_accounts:
        account_start_balances[acct] = st.sidebar.number_input(
            f"{acct} starting balance ($)", min_value=0.0, value=0.0, step=1000.0, key=f"bal_{acct}"
        )
        account_returns[acct] = st.sidebar.number_input(
            f"{acct} expected annual return (%)", min_value=-50.0, max_value=50.0,
            value=round(expected_return * 100, 1), step=0.5, key=f"ret_{acct}"
        ) / 100.0

    with st.sidebar.expander("Set returns for additional accounts (no starting balances)"):
        for acct in [a for a in ALL_ACCOUNTS if a not in chosen_accounts]:
            if st.checkbox(f"Set return for {acct}", key=f"setret_{acct}"):
                account_returns[acct] = st.number_input(
                    f"{acct} expected annual return (%)", min_value=-50.0, max_value=50.0,
                    value=round(expected_return * 100, 1), step=0.5, key=f"ret_only_{acct}"
                ) / 100.0

    specified_total = sum(account_start_balances.values())
    other_start = max(current_investments - specified_total, 0)
    other_return = st.sidebar.number_input(
        "Other Investments expected annual return (%)",
        min_value=-50.0, max_value=50.0,
        value=round(expected_return * 100, 1), step=0.5, key="ret_other"
    ) / 100.0
else:
    chosen_accounts = []
    specified_total = 0.0
    other_start = current_investments
    other_return = expected_return

# =========================
# ---- Main Calculations ----
# =========================

if st.sidebar.button("🚀 Run FIRE Simulation"):
    # Pension is pre-tax and always included in both baseline & scenario
    pension_contribution = gross_salary * pension_percent

    # Scenario AGI
    agi = gross_salary - pension_contribution

    # Employee pre-tax (AGI-reducing)
    agi_reducing_accounts = [
        "403(b) Traditional", "457(b) Traditional",
        "401(a) Employee", "Solo 401(k) Employee",
        "SEP IRA", "SIMPLE IRA", "Traditional IRA",
        "HSA", "FSA"
    ]
    # Employer-funded (no AGI / take-home impact)
    employer_funded_accounts = ["401(a) Employer"]

    for acct in agi_reducing_accounts:
        agi -= contributions.get(acct, 0)

    # Virginia 529 deduction up to $4,000
    va_529_deduction = min(contributions.get("529 Plan", 0), 4000)
    agi -= va_529_deduction

    taxable_income = max(agi - standard_deduction, 0)
    federal_tax = calculate_tax(taxable_income, federal_brackets)
    state_tax = calculate_tax(taxable_income, VIRGINIA_BRACKETS_2025)
    total_tax = federal_tax + state_tax

    effective_tax_rate = (total_tax / gross_salary) if gross_salary > 0 else 0.0
    after_tax_income = gross_salary - pension_contribution - total_tax

    total_savings = sum(contributions.values())
    pre_tax_sum = sum(contributions.get(a, 0) for a in agi_reducing_accounts) + va_529_deduction
    employer_sum = sum(contributions.get(a, 0) for a in employer_funded_accounts)

    # Post-tax savings that DO reduce take-home (Roth, Brokerage, Crypto, ESA, etc.)
    post_tax_savings = total_savings - pre_tax_sum - employer_sum
    disposable_income = after_tax_income - post_tax_savings

    # -------------------------
    # Contribution Warnings (non-blocking)
    # -------------------------
    ira_total = contributions.get("Traditional IRA", 0) + contributions.get("Roth IRA", 0)
    if ira_total > hints["IRA (Traditional/Roth) combined"]:
        st.warning(f"IRA combined contributions {money(ira_total)} exceed your 2025 hint of {money(hints['IRA (Traditional/Roth) combined'])}.")

    def warn_pair(a_name, b_name, hint_key, label):
        total = contributions.get(a_name, 0) + contributions.get(b_name, 0)
        limit = hints[hint_key]
        if total > limit:
            st.warning(f"{label} contributions {money(total)} exceed your 2025 hint of {money(limit)}.")
    warn_pair("457(b) Traditional", "457(b) Roth", "457(b) employee deferral", "457(b)")
    warn_pair("403(b) Traditional", "403(b) Roth", "403(b) employee deferral", "403(b)")

    if contributions.get("HSA", 0) > hints["HSA (family)"]:
        st.warning(f"HSA contribution {money(contributions.get('HSA', 0))} exceeds your 2025 hint of {money(hints['HSA (family)'])}.")
    if contributions.get("FSA", 0) > hints["FSA (health)"]:
        st.warning(f"FSA contribution {money(contributions.get('FSA', 0))} exceeds your 2025 hint of {money(hints['FSA (health)'])}.")

    # Optional: overall DC §415(c)
    if total_savings - contributions.get("Brokerage", 0) - contributions.get("Crypto", 0) > hints["415(c) overall DC limit"]:
        st.info("Heads-up: total plan contributions may exceed your §415(c) overall limit hint; verify with plan rules.")

    if post_tax_savings > after_tax_income:
        st.warning("Post-tax savings exceed after-tax income. Disposable income is negative; charts clamp it to $0 where needed.")

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
            "Total Annual Savings (all sources)",
            "Employee-Funded Savings (affects take-home)",
            "Employer-Funded Savings (no take-home impact)",
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
            money(total_savings - employer_sum),
            money(employer_sum),
            pct((total_savings) / gross_salary if gross_salary > 0 else 0.0),
            money(disposable_income)
        ]
    })
    st.dataframe(fire_summary)

    # ---- Contributions Table ----
    st.subheader("📚 Contributions Detail")
    if contributions:
        contribs = sorted([(k, v) for k, v in contributions.items()], key=lambda x: x[0])
        st.dataframe(pd.DataFrame(contribs, columns=["Account", "Annual Contribution ($)"]))
    else:
        st.info("No contributions selected.")

    # =========================
    # ---- Contribution Impact ----
    # =========================
    st.subheader("🚀 Contribution Impact Summary")

    baseline_pension_contribution = pension_contribution
    baseline_agi = gross_salary - baseline_pension_contribution
    baseline_taxable_income = max(baseline_agi - standard_deduction, 0)
    baseline_federal_tax = calculate_tax(baseline_taxable_income, federal_brackets)
    baseline_state_tax = calculate_tax(baseline_taxable_income, VIRGINIA_BRACKETS_2025)
    baseline_total_tax = baseline_federal_tax + baseline_state_tax
    baseline_after_tax_income = gross_salary - baseline_pension_contribution - baseline_total_tax
    baseline_disposable_income = baseline_after_tax_income

    col1, col2, col3 = st.columns(3)
    col1.metric("Δ Taxes Paid", money(baseline_total_tax - total_tax))
    col2.metric("Annual Savings (total, incl. employer)", money(total_savings))
    col3.metric("Δ Disposable Income", money((after_tax_income - post_tax_savings) - baseline_disposable_income))

    # Only employee-funded savings in the allocation (cash-flow)
    savings_for_cashflow = total_savings - employer_sum
    allocation_rows = [
        {"Scenario": "No Contributions",   "Category": "Pension",        "Amount": baseline_pension_contribution},
        {"Scenario": "No Contributions",   "Category": "Federal Taxes",  "Amount": baseline_federal_tax},
        {"Scenario": "No Contributions",   "Category": "State Taxes",    "Amount": baseline_state_tax},
        {"Scenario": "No Contributions",   "Category": "Savings",        "Amount": 0},
        {"Scenario": "No Contributions",   "Category": "Disposable",     "Amount": baseline_disposable_income},

        {"Scenario": "With Contributions", "Category": "Pension",        "Amount": pension_contribution},
        {"Scenario": "With Contributions", "Category": "Federal Taxes",  "Amount": federal_tax},
        {"Scenario": "With Contributions", "Category": "State Taxes",    "Amount": state_tax},
        {"Scenario": "With Contributions", "Category": "Savings",        "Amount": savings_for_cashflow},
        {"Scenario": "With Contributions", "Category": "Disposable",     "Amount": max(disposable_income, 0)},
    ]
    alloc_df = pd.DataFrame(allocation_rows)
    st.caption("Share of gross salary by destination (pension, taxes, **employee-funded** savings, disposable). Employer contributions are excluded from this cash-flow view.")
    try:
        if ALT_AVAILABLE:
            chart = (
                alt.Chart(alloc_df)
                .mark_bar()
                .encode(
                    x=alt.X('Scenario:N', title=None),
                    y=alt.Y('sum(Amount):Q', stack='normalize', axis=alt.Axis(format='%')),
                    color=alt.Color('Category:N', legend=alt.Legend(title='Allocation')),
                    tooltip=[alt.Tooltip('Scenario:N'), alt.Tooltip('Category:N'),
                             alt.Tooltip('Amount:Q', title='Amount', format='$,.0f')]
                )
                .properties(height=300)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.warning("Altair not available. Showing allocation table instead.")
            st.dataframe(alloc_df.pivot_table(index="Category", columns="Scenario", values="Amount"))
    except Exception as e:
        st.warning(f"Allocation chart unavailable ({e}). Showing table instead.")
        st.dataframe(alloc_df.pivot_table(index="Category", columns="Scenario", values="Amount"))

    # =========================
    # ---- Money Flow Pie ----
    # =========================
    st.subheader("📊 Money Flow Pie (Net of Pension)")
    base_after_pension = gross_salary - pension_contribution
    pie_labels = ["Federal Taxes", "State Taxes", "Employee-Funded Savings", "Disposable Income"]
    pie_values = [federal_tax, state_tax, max(savings_for_cashflow, 0), max(disposable_income, 0)]
    fig1, ax1 = plt.subplots()
    if sum(v for v in pie_values) <= 0:
        ax1.text(0.5, 0.5, "No flow to display", ha='center', va='center')
    else:
        ax1.pie(pie_values, labels=pie_labels, autopct='%1.1f%%', startangle=90)
        ax1.axis('equal')
    st.caption(f"Pie represents allocation of **{money(base_after_pension)}** (gross minus pension). Employer contributions are not part of this pie.")
    st.pyplot(fig1)

    # =========================
    # ---- FI Milestones & Growth ----
    # =========================
    st.subheader("🌱 FI Milestones Projection (SWR-driven)")

    # Build per-account portfolio model (normalize returns!)
    portfolio = {}
    if other_start > 0:
        portfolio["Other Investments"] = {"balance": other_start, "return": normalize_return(other_return)}
    for acct, bal in account_start_balances.items():
        if bal > 0:
            r = account_returns.get(acct, expected_return)
            portfolio[acct] = {"balance": bal, "return": normalize_return(r)}
    for acct, contrib in contributions.items():
        if acct not in portfolio:
            r = account_returns.get(acct, expected_return)
            portfolio[acct] = {"balance": 0.0, "return": normalize_return(r)}
    annual_contribs = {acct: contributions.get(acct, 0.0) for acct in portfolio.keys()}

    # Debug: show assumed returns after normalization
    st.caption("Assumed per-account returns (after normalization)")
    st.dataframe(pd.DataFrame(
        [{"Account": a, "Assumed Return": pct(portfolio[a]['return'])} for a in sorted(portfolio.keys())]
    ))

    years = []
    balances = []
    milestone_years = {}   # name -> int years to achieve (0 already), or None
    snapshot_at_ret = None
    full_fi_first_year = None
    snapshot_full_fi = None

    if swr <= 0:
        st.error("Safe Withdrawal Rate must be > 0%.")
        st.stop()

    full_fi_target     = annual_expenses / swr
    lean_fi_target     = (annual_expenses * 0.75) / swr
    chubby_fi_target   = (annual_expenses * 1.20) / swr
    fat_fi_target      = (annual_expenses * 1.50) / swr
    barista_fi_target  = (annual_expenses * 0.50) / swr
    flamingo_fi_target = 0.50 * full_fi_target

    # Coast FI target uses YEARS UNTIL retirement (fixed)
    coast_fi_target = full_fi_target / ((1 + expected_return) ** years_until_ret) if expected_return > -1 else math.inf

    milestone_defs = [
        ("Coast FI", coast_fi_target),
        ("Flamingo FI (50% of FI #)", flamingo_fi_target),
        ("Barista FI (covers ~50% of expenses)", barista_fi_target),
        ("Lean FI (75% Expenses)", lean_fi_target),
        ("Chubby FI (~120% Expenses)", chubby_fi_target),
        ("Full FI (100% Expenses)", full_fi_target),
        ("Fat FI (150% Expenses)", fat_fi_target),
    ]

    starting_total = sum(b["balance"] for b in portfolio.values())
    for name, target in milestone_defs:
        milestone_years[name] = 0 if starting_total >= target else None

    # Sim loop (up to 50 years)
    for year in range(1, 51):
        for acct in portfolio:
            r = portfolio[acct]["return"]
            portfolio[acct]["balance"] = portfolio[acct]["balance"] * (1 + r) + annual_contribs.get(acct, 0.0)

        total_balance = sum(b["balance"] for b in portfolio.values())
        years.append(year)
        balances.append(total_balance)

        if full_fi_first_year is None and total_balance >= full_fi_target:
            full_fi_first_year = year
            snapshot_full_fi = {acct: portfolio[acct]["balance"] for acct in portfolio}

        for name, target in milestone_defs:
            if milestone_years[name] is None and total_balance >= target:
                milestone_years[name] = year

        if year == years_until_ret:
            snapshot_at_ret = {acct: portfolio[acct]["balance"] for acct in portfolio}

    if snapshot_at_ret is None:
        snapshot_at_ret = {acct: portfolio[acct]["balance"] for acct in portfolio}

    # ----- Milestones table ordered by time -----
    ordered = []
    for name, _ in milestone_defs:
        yr = milestone_years[name]
        if yr is None:
            display = ">50 years"; sort_key = 10**9
        elif yr == 0:
            display = "0 years (✅ already)"; sort_key = 0
        else:
            display = f"{yr} years"; sort_key = yr
        ordered.append((name, display, sort_key))
    ordered.sort(key=lambda x: x[2])

    st.subheader(f"🏁 FI Milestones (SWR = {swr_percent:.1f}%) — ordered by time to achieve")
    st.table(pd.DataFrame([(n, d) for n, d, _ in ordered], columns=["Milestone", "Time to Achieve"]))

    # ---- Milestone explanations (typical progression) ----
    st.subheader("📖 What the Milestones Mean (typical progression)")
    st.markdown(f"""
- **Coast FI** *(meta milestone)*: Invested today grows to your **Full FI** target by ~**{years_until_ret} years** from now with **no additional contributions**.
- **Barista FI**: Portfolio supports **~50% of your annual expenses** at your chosen SWR; the remaining ~50% comes from part-time work or a lighter-pay role.
- **Flamingo FI**: Build **~50%** of your Full FI number, then **downshift**—let compounding finish the job while you semi-retire with little/no new savings.
- **Lean FI**: Portfolio can support **75%** of expenses at your chosen SWR.
- **Full FI**: Portfolio supports **100%** of expenses at your chosen SWR.
- **Chubby FI**: Comfortable middle-ground—**~120%** of expenses (extra cushion beyond Full FI).
- **Fat FI**: Portfolio supports **150%** of expenses (even more cushion/luxury).
""")

    # ---- Investment Growth Over Time ----
    st.subheader("📈 Investment Growth Over Time")
    fig2, ax2 = plt.subplots()
    if years and balances:
        ax2.plot(years, balances, label="Projected Portfolio Value")

        if full_fi_first_year is not None and 1 <= full_fi_first_year <= len(years):
            x = full_fi_first_year
            y = balances[x - 1]
            ax2.axvline(x, linestyle=':', alpha=0.6)
            ax2.scatter([x], [y], zorder=5)
            right_side = x < (len(years) * 0.7)
            x_text = x + 1 if right_side else x - 1
            y_text = y * (1.06 if right_side else 1.04)
            ax2.annotate(
                f"Full FI in {x} yrs\n{money(y)}",
                xy=(x, y),
                xytext=(x_text, y_text),
                arrowprops=dict(arrowstyle="->", lw=1),
                fontsize=9,
                ha="left" if right_side else "right"
            )

        ax2.axhline(y=full_fi_target, linestyle='--', label=f'Full FI ({money(full_fi_target)})')
        ax2.axhline(y=chubby_fi_target, linestyle=':', label=f'Chubby FI ({money(chubby_fi_target)})')
        ax2.axhline(y=lean_fi_target, linestyle='-.', label=f'Lean FI ({money(lean_fi_target)})')

        ax2.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f'${int(x/1000)}k' if x < 1_000_000 else f'${x/1_000_000:.1f}M')
        )
        ax2.set_xlabel("Years")
        ax2.set_ylabel("Portfolio Value ($)")
        ax2.legend()
    else:
        ax2.text(0.5, 0.5, "No data to plot", ha='center', va='center')
    st.pyplot(fig2)

    # -----------------------------
    # Snapshot selector (FI vs Ret)
    # -----------------------------
    default_label = f"Retirement horizon (~{years_until_ret} years)"
    fi_label = "First year you reach Full FI"
    snapshot_choice = st.radio(
        "Balance snapshot at",
        [default_label, fi_label],
        index=0,
        help="View balances at your retirement horizon or the first year your portfolio crosses the Full FI target."
    )
    if snapshot_choice == fi_label and snapshot_full_fi is not None:
        snapshot_to_use = snapshot_full_fi
        snapshot_year_text = f"(year {full_fi_first_year})"
    else:
        if snapshot_choice == fi_label and snapshot_full_fi is None:
            st.info("You do not reach Full FI within the 50-year simulation. Showing retirement-horizon snapshot instead.")
        snapshot_to_use = snapshot_at_ret
        snapshot_year_text = f"(~{years_until_ret} years)"

    # =========================
    # ---- Tax Bucket Summary at Selected Snapshot ----
    # =========================
    st.subheader(f"🏦 Projected Balances by Tax Bucket {snapshot_year_text}")

    def tax_bucket(acct_name: str) -> str:
        roth = {"Roth IRA", "403(b) Roth", "457(b) Roth"}
        traditional = {
            "Traditional IRA", "403(b) Traditional", "457(b) Traditional",
            "401(a) Employee", "401(a) Employer", "Solo 401(k) Employee",
            "Solo 401(k) Employer", "SEP IRA", "SIMPLE IRA"
        }
        hsa = {"HSA"}
        education = {"529 Plan", "ESA"}
        taxable = {"Brokerage", "Crypto", "Other Investments"}
        if acct_name in roth:
            return "Roth (tax-free withdrawals, rules apply)"
        if acct_name in traditional:
            return "Traditional / Pre-tax (taxable withdrawals)"
        if acct_name in hsa:
            return "HSA (triple-advantaged, med. rules)"
        if acct_name in education:
            return "Education (529/ESA)"
        if acct_name in taxable:
            return "Taxable / Non-advantaged"
        return "Other / Unclassified"

    bucket_sums = {}
    for acct, bal in snapshot_to_use.items():
        b = tax_bucket(acct)
        bucket_sums[b] = bucket_sums.get(b, 0.0) + bal
    bucket_rows = [{"Bucket": b, "Projected Balance": money(v)} for b, v in bucket_sums.items()]
    bucket_df = pd.DataFrame(bucket_rows).sort_values("Bucket")
    st.dataframe(bucket_df, use_container_width=True)

    st.subheader(f"📋 Per-Account Balances {snapshot_year_text}")
    acct_rows = []
    for acct, bal in sorted(snapshot_to_use.items()):
        acct_rows.append({
            "Account": acct,
            "Bucket": tax_bucket(acct),
            "Projected Balance": money(bal)
        })
    st.dataframe(pd.DataFrame(acct_rows), use_container_width=True)
