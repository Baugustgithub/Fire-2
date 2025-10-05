import math
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# Optional (touch-zoom charts)
try:
    import altair as alt
    ALT_AVAILABLE = True
except Exception:
    ALT_AVAILABLE = False

# ----------------------------
# Page & Session
# ----------------------------
st.set_page_config(
    page_title="🔥 FIRE Tax + FI Planner 2025",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Mobile-friendly CSS
st.markdown("""
<style>
.block-container { padding-top: 0.6rem; padding-bottom: 0.6rem; }
@media (max-width: 640px) {
  .stDataFrame { font-size: 0.9rem; }
  .stMetric { font-size: 0.9rem; }
}
[data-baseweb="radio"] label, [data-baseweb="checkbox"] label { line-height: 1.2rem; }
</style>
""", unsafe_allow_html=True)

if "sim" not in st.session_state:
    st.session_state["sim"] = None

# =========================
# ---- Tax Settings ----
# =========================
FEDERAL_BRACKETS_2025_SINGLE = [
    (0, 0.10), (11925, 0.12), (48475, 0.22),
    (103350, 0.24), (197300, 0.32), (250525, 0.35), (626350, 0.37),
]
FEDERAL_BRACKETS_2025_MARRIED = [
    (0, 0.10), (23850, 0.12), (96950, 0.22),
    (206700, 0.24), (394600, 0.32), (501050, 0.35), (752600, 0.37),
]
VIRGINIA_BRACKETS_2025 = [(0, 0.02), (3000, 0.03), (5000, 0.05), (17000, 0.0575)]
STANDARD_DEDUCTION_2025_SINGLE = 15000
STANDARD_DEDUCTION_2025_MARRIED = 30000

# =========================
# ---- Helpers ----
# =========================
def calculate_tax(taxable_income: float, brackets: list[tuple[int, float]]) -> float:
    if taxable_income <= 0: return 0.0
    tax = 0.0
    n = len(brackets)
    for i, (start, rate) in enumerate(brackets):
        end = brackets[i + 1][0] if i + 1 < n else float('inf')
        if taxable_income <= start: break
        span = min(taxable_income, end) - start
        if span > 0: tax += span * rate
    return max(tax, 0.0)

def money(x): return f"${x:,.0f}"
def pct(x):   return f"{x:.1%}"

def normalize_return(r):
    if r is None: return 0.0
    try: r_float = float(r)
    except Exception: return 0.0
    if r_float > 1.5: r_float = r_float / 100.0  # interpret 30 -> 0.30
    return max(-0.90, min(2.00, r_float))        # clamp [-90%, +200%]

def inflate_expense(base_expense: float, cpi: float, years: int) -> float:
    return base_expense * ((1.0 + cpi) ** max(0, years))

def format_eta_decimal(eta_years):
    """Always show a decimal number of years (one decimal)."""
    if eta_years is None:
        return "> capped horizon"
    # round to 0.1 year
    return f"{eta_years:.1f} years"

# =========================
# ---- App ----
# =========================
st.title("🔥 FIRE Tax + FI Planner 2025 (Federal + Virginia) 🔥")

with st.expander("Assumptions", expanded=False):
    st.markdown(
        "- 2025 **federal** & **Virginia** tax brackets (start-of-bracket).\n"
        "- Uses the **standard deduction** by filing status.\n"
        "- Virginia 529 deduction capped at **$4,000**.\n"
        "- **SWR** drives FI targets (you control the %).\n"
        "- **Years until retirement = Target age − Current age**.\n"
        "- Simplified model: ignores credits/phaseouts, SS/Medicare, LTCG/qualified dividends, NIIT, etc."
    )

# ---- Sidebar Inputs ----
st.sidebar.header("Filing Status")
filing_status = st.sidebar.selectbox("Select Filing Status", ["Single", "Married Filing Jointly"])

st.sidebar.header("Income & Expenses")
gross_salary = st.sidebar.number_input("Gross Salary ($)", value=150000, step=1000)
pension_percent = st.sidebar.slider("Pension Contribution (% of Salary)", 0, 20, 5) / 100
annual_expenses = st.sidebar.number_input("Annual Expenses ($)", value=45000, step=1000)

# SWR
swr_percent = st.sidebar.number_input("Safe Withdrawal Rate (%)", min_value=2.0, max_value=7.0, value=4.0, step=0.1)
swr = swr_percent / 100.0

# Inflation controls
st.sidebar.header("Inflation")
inflation_percent = st.sidebar.number_input("Annual CPI (%)", min_value=0.0, max_value=10.0, value=3.0, step=0.1)
inflation = inflation_percent / 100.0
expense_inflation_on = st.sidebar.checkbox(
    "Inflate expenses by CPI for nominal FI targets", value=False,
    help="When ON, FI guide-lines (Lean/Full/Chubby/Obese) use expenses inflated to the snapshot horizon."
)

# Horizon + cap
st.sidebar.header("Retirement Horizon")
current_age = st.sidebar.number_input("Current age", value=40, step=1, min_value=0)
target_age = st.sidebar.number_input("Target retirement age", value=58, step=1, min_value=0)
years_until_ret = max(1, int(round(target_age - current_age)))

st.sidebar.header("Horizon Limit")
sim_until_age = st.sidebar.number_input(
    "Show results until age", value=65, min_value=max(current_age + 1, 1), step=1,
    help="Simulation and charts will stop at this age."
)

# Portfolio-level default return (everything else)
default_return_all_else = 0.08   # 8%

# ===========================================
# ---- Accounts (Core vs More, with Crypto) --
# ===========================================
st.sidebar.header("Choose Accounts to Contribute To")
with st.sidebar.container():
    st.markdown("**Core account types**")
    core_accounts = {
        "Brokerage": st.checkbox("Brokerage", value=False),
        "Crypto": st.checkbox("Crypto", value=True),
        "Traditional IRA": st.checkbox("Traditional IRA", value=True),
        "Roth IRA": st.checkbox("Roth IRA", value=True),
        "457(b) Traditional": st.checkbox("457(b) Traditional", value=True),
        "457(b) Roth": st.checkbox("457(b) Roth", value=False),
        "403(b) Traditional": st.checkbox("403(b) Traditional", value=True),
        "403(b) Roth": st.checkbox("403(b) Roth", value=True),
    }
with st.sidebar.expander("More account types (optional)"):
    more_accounts = {
        "401(a) Employee": st.checkbox("401(a) Employee Contribution", value=False),
        "401(a) Employer": st.checkbox("401(a) Employer Contribution", value=False),
        "Solo 401(k) Employee": st.checkbox("Solo 401(k) Employee Contribution", value=False),
        "Solo 401(k) Employer": st.checkbox("Solo 401(k) Employer Contribution", value=False),
        "SEP IRA": st.checkbox("SEP IRA", value=False),
        "SIMPLE IRA": st.checkbox("SIMPLE IRA", value=False),
        "HSA": st.checkbox("HSA", value=False),
        "FSA": st.checkbox("FSA", value=False),
        "529 Plan": st.checkbox("529 Plan", value=False),
        "ESA": st.checkbox("ESA", value=False),
    }

# Contributions (defaults)
st.sidebar.header("Annual Contributions ($/year)")
contributions = {}
for account, enabled in {**core_accounts, **more_accounts}.items():
    if enabled:
        key = ("core_" if account in core_accounts else "more_") + account
        default_val = 0
        if account == "457(b) Traditional": default_val = 15000
        if account == "403(b) Traditional": default_val = 23500
        if account == "Crypto":             default_val = 15000
        if account == "Roth IRA":           default_val = 5000
        contributions[account] = st.sidebar.number_input(
            f"{account} Contribution ($)", value=default_val, step=500, key=key
        )

# 2025 limit hints (warnings only)
with st.sidebar.expander("Contribution limit tips (2025 — edit if needed)"):
    hints = {
        "IRA (Traditional/Roth) combined": st.number_input("IRA annual limit ($)", value=7000, step=500, key="hint_ira"),
        "457(b) employee deferral": st.number_input("457(b) annual limit ($)", value=23500, step=500, key="hint_457"),
        "403(b) employee deferral": st.number_input("403(b) annual limit ($)", value=23500, step=500, key="hint_403"),
        "HSA (family)": st.number_input("HSA annual limit ($)", value=8550, step=50, key="hint_hsa"),
        "FSA (health)": st.number_input("FSA annual limit ($)", value=3300, step=50, key="hint_fsa"),
        "415(c) overall DC limit": st.number_input("Overall DC limit (§415c) ($)", value=70000, step=1000, key="hint_415c"),
        "529 (VA deduction hint)": st.number_input("VA 529 deductible amount used ($)", value=4000, step=500, key="hint_529"),
    }
    st.caption("These are non-blocking warnings; catch-ups vary by age & plan.")

# ==============================================
# ---- Granular Balances & Per-Account Returns --
# ==============================================
st.sidebar.header("Granular balances & returns (optional)")
granular_mode = st.sidebar.checkbox("Enable granular balances & per-account returns", value=True)

ALL_ACCOUNTS = list(core_accounts.keys()) + list(more_accounts.keys())
account_start_balances = {}
account_returns = {}

DEFAULT_BALANCES = {
    "Crypto": 250_000,
    "403(b) Traditional": 176_000,
    "403(b) Roth": 28_000,
    "457(b) Traditional": 112_000,
    "457(b) Roth": 300,
    "Traditional IRA": 67_000,
    "Roth IRA": 123_000,
}
DEFAULT_RETURNS = {"Crypto": 0.20}  # others default to 8%

default_total_investments = sum(DEFAULT_BALANCES.values())
current_investments = st.sidebar.number_input(
    "Current Total Investment Value ($)", value=default_total_investments, step=1000
)
default_granular_selection = list(DEFAULT_BALANCES.keys())

if granular_mode:
    st.sidebar.caption("Specify starting balances & returns for selected accounts. Remainder → 'Other Investments'.")
    chosen_accounts = st.sidebar.multiselect(
        "Accounts with explicit starting balance & return",
        options=ALL_ACCOUNTS,
        default=default_granular_selection
    )
    for acct in chosen_accounts:
        start_default = DEFAULT_BALANCES.get(acct, 0.0)
        ret_default = DEFAULT_RETURNS.get(acct, default_return_all_else)
        account_start_balances[acct] = st.sidebar.number_input(
            f"{acct} starting balance ($)", min_value=0.0, value=float(start_default), step=1000.0, key=f"bal_{acct}"
        )
        account_returns[acct] = st.sidebar.number_input(
            f"{acct} expected annual return (%)",
            min_value=-50.0, max_value=50.0,
            value=round(ret_default * 100, 1),
            step=0.5, key=f"ret_{acct}"
        ) / 100.0

    with st.sidebar.expander("Set returns for additional accounts (no starting balances)"):
        for acct in [a for a in ALL_ACCOUNTS if a not in chosen_accounts]:
            if st.checkbox(f"Set return for {acct}", key=f"setret_{acct}"):
                account_returns[acct] = st.number_input(
                    f"{acct} expected annual return (%)",
                    min_value=-50.0, max_value=50.0,
                    value=round(default_return_all_else * 100, 1),
                    step=0.5, key=f"ret_only_{acct}"
                ) / 100.0

    specified_total = sum(account_start_balances.values())
    other_start = max(current_investments - specified_total, 0.0)
    other_return = st.sidebar.number_input(
        "Other Investments expected annual return (%)",
        min_value=-50.0, max_value=50.0,
        value=round(default_return_all_else * 100, 1),
        step=0.5, key="ret_other"
    ) / 100.0
else:
    chosen_accounts = []
    specified_total = 0.0
    other_start = current_investments
    other_return = default_return_all_else

# =========================
# ---- Run Simulation ----
# =========================
clicked = st.sidebar.button("🚀 Run / Update FIRE Simulation")

if clicked:
    # Taxes / cash flow
    pension_contribution = gross_salary * pension_percent
    agi = gross_salary - pension_contribution
    agi_reducing_accounts = [
        "403(b) Traditional", "457(b) Traditional",
        "401(a) Employee", "Solo 401(k) Employee",
        "SEP IRA", "SIMPLE IRA", "Traditional IRA", "HSA", "FSA"
    ]
    employer_funded_accounts = ["401(a) Employer"]
    for acct in agi_reducing_accounts:
        agi -= contributions.get(acct, 0)
    va_529_deduction = min(contributions.get("529 Plan", 0), 4000)
    agi -= va_529_deduction

    std_ded = STANDARD_DEDUCTION_2025_SINGLE if filing_status=="Single" else STANDARD_DEDUCTION_2025_MARRIED
    taxable_income = max(agi - std_ded, 0)
    federal_tax = calculate_tax(taxable_income, FEDERAL_BRACKETS_2025_SINGLE if filing_status=="Single" else FEDERAL_BRACKETS_2025_MARRIED)
    state_tax = calculate_tax(taxable_income, VIRGINIA_BRACKETS_2025)
    total_tax = federal_tax + state_tax

    effective_tax_rate = (total_tax / gross_salary) if gross_salary > 0 else 0.0
    after_tax_income = gross_salary - pension_contribution - total_tax

    total_savings = sum(contributions.values())
    pre_tax_sum = sum(contributions.get(a, 0) for a in agi_reducing_accounts) + va_529_deduction
    employer_sum = sum(contributions.get(a, 0) for a in employer_funded_accounts)
    post_tax_savings = total_savings - pre_tax_sum - employer_sum
    disposable_income = after_tax_income - post_tax_savings

    # Warnings
    warn_msgs = []
    ira_total = contributions.get("Traditional IRA", 0) + contributions.get("Roth IRA", 0)
    if ira_total > hints["IRA (Traditional/Roth) combined"]:
        warn_msgs.append(f"IRA combined {money(ira_total)} > {money(hints['IRA (Traditional/Roth) combined'])}")
    def over(a, b, key, label):
        t = contributions.get(a, 0) + contributions.get(b, 0)
        if t > hints[key]: warn_msgs.append(f"{label} {money(t)} > {money(hints[key])}")
    over("457(b) Traditional", "457(b) Roth", "457(b) employee deferral", "457(b)")
    over("403(b) Traditional", "403(b) Roth", "403(b) employee deferral", "403(b)")
    if post_tax_savings > after_tax_income:
        warn_msgs.append("Post-tax savings > after-tax income (negative disposable).")

    # Portfolio build
    portfolio = {}
    if other_start > 0:
        portfolio["Other Investments"] = {"balance": other_start, "return": normalize_return(other_return)}
    for acct, bal in account_start_balances.items():
        if bal > 0:
            r = account_returns.get(acct, default_return_all_else)
            portfolio[acct] = {"balance": bal, "return": normalize_return(r)}
    for acct in contributions.keys():
        if acct not in portfolio:
            r = account_returns.get(acct, default_return_all_else)
            portfolio[acct] = {"balance": 0.0, "return": normalize_return(r)}
    annual_contribs = {acct: contributions.get(acct, 0.0) for acct in portfolio.keys()}

    # FI targets (real baseline)
    if swr <= 0:
        st.error("Safe Withdrawal Rate must be > 0%."); st.stop()
    base_full_fi    = annual_expenses / swr
    base_lean_fi    = (annual_expenses * 0.75) / swr
    base_chubby_fi  = (annual_expenses * 1.20) / swr
    base_fat_fi     = (annual_expenses * 1.50) / swr
    base_obese_fi   = (annual_expenses * 2.00) / swr   # NEW
    base_barista_fi = (annual_expenses * 0.50) / swr
    base_flamingo_fi = 0.50 * base_full_fi
    coast_fi_target  = base_full_fi / ((1 + default_return_all_else) ** years_until_ret) if default_return_all_else > -1 else math.inf

    milestone_defs = [
        ("Coast FI", coast_fi_target),
        ("Flamingo FI (50% of FI #)", base_flamingo_fi),
        ("Barista FI (covers ~50% of expenses)", base_barista_fi),
        ("Lean FI (75% Expenses)", base_lean_fi),
        ("Chubby FI (~120% Expenses)", base_chubby_fi),
        ("Full FI (100% Expenses)", base_full_fi),
        ("Fat FI (150% Expenses)", base_fat_fi),
        ("Obese FI (200% Expenses)", base_obese_fi),  # NEW
    ]

    # Sim loop with age cap + fractional milestone ETAs
    sim_years = max(1, min(50, int(sim_until_age - current_age)))
    years, balances = [], []
    milestone_eta = {name: (0.0 if sum(b["balance"] for b in portfolio.values()) >= target else None)
                     for name, target in milestone_defs}
    snapshot_at_ret = None
    full_fi_first_year = None
    snapshot_full_fi = None
    snapshot_5yr = None
    snapshot_10yr = None

    for year in range(1, sim_years + 1):
        prev_total = sum(b["balance"] for b in portfolio.values())
        # grow & contribute
        for acct in portfolio:
            r = portfolio[acct]["return"]
            portfolio[acct]["balance"] = portfolio[acct]["balance"] * (1 + r) + annual_contribs.get(acct, 0.0)
        total_balance = sum(b["balance"] for b in portfolio.values())
        years.append(year); balances.append(total_balance)

        if year == 5:  snapshot_5yr  = {acct: portfolio[acct]["balance"] for acct in portfolio}
        if year == 10: snapshot_10yr = {acct: portfolio[acct]["balance"] for acct in portfolio}

        if full_fi_first_year is None and total_balance >= base_full_fi:
            full_fi_first_year = year
            snapshot_full_fi = {acct: portfolio[acct]["balance"] for acct in portfolio}

        # fractional crossing time
        span = max(total_balance - prev_total, 1e-9)
        for name, target in milestone_defs:
            if milestone_eta[name] is None and prev_total < target <= total_balance:
                frac = (target - prev_total) / span
                milestone_eta[name] = (year - 1) + frac

        if year == years_until_ret:
            snapshot_at_ret = {acct: portfolio[acct]["balance"] for acct in portfolio}
    if snapshot_at_ret is None:
        snapshot_at_ret = {acct: portfolio[acct]["balance"] for acct in portfolio}

    # Real (today's $) series
    deflator = [(1.0 + inflation) ** y for y in years]
    real_balances = [b / d for b, d in zip(balances, deflator)]

    def discount_snapshot(snap_dict, t_years):
        if snap_dict is None: return None
        return {k: v / ((1.0 + inflation) ** t_years) for k, v in snap_dict.items()}

    real_snapshot_at_ret = discount_snapshot(snapshot_at_ret, min(years_until_ret, sim_years))
    real_snapshot_full_fi = discount_snapshot(snapshot_full_fi, full_fi_first_year) if full_fi_first_year else None
    real_snapshot_5yr  = discount_snapshot(snapshot_5yr, 5)   if snapshot_5yr  else None
    real_snapshot_10yr = discount_snapshot(snapshot_10yr, 10) if snapshot_10yr else None

    # Save to session state
    st.session_state["sim"] = dict(
        # cash/tax
        agi=agi, taxable_income=taxable_income, federal_tax=federal_tax, state_tax=state_tax,
        total_tax=total_tax, effective_tax_rate=effective_tax_rate, after_tax_income=after_tax_income,
        total_savings=total_savings, employer_sum=employer_sum, post_tax_savings=post_tax_savings,
        disposable_income=disposable_income, pension_contribution=pension_contribution, warn_msgs=warn_msgs,
        # series
        years=years, balances=balances, real_balances=real_balances, sim_years=sim_years,
        # targets (real baseline)
        base_full_fi=base_full_fi, base_lean_fi=base_lean_fi, base_chubby_fi=base_chubby_fi,
        base_fat_fi=base_fat_fi, base_obese_fi=base_obese_fi,
        base_barista_fi=base_barista_fi, base_flamingo_fi=base_flamingo_fi, coast_fi_target=coast_fi_target,
        # snapshots nominal + real
        snapshot_at_ret=snapshot_at_ret, snapshot_full_fi=snapshot_full_fi,
        snapshot_5yr=snapshot_5yr, snapshot_10yr=snapshot_10yr,
        real_snapshot_at_ret=real_snapshot_at_ret, real_snapshot_full_fi=real_snapshot_full_fi,
        real_snapshot_5yr=real_snapshot_5yr, real_snapshot_10yr=real_snapshot_10yr,
        # milestone ETAs (decimal years)
        milestone_defs=milestone_defs, milestone_eta=milestone_eta,
        # meta
        swr_percent=swr_percent, swr=swr, annual_expenses=annual_expenses,
        years_until_ret=years_until_ret, inflation=inflation, inflation_percent=inflation_percent,
        expense_inflation_on=expense_inflation_on, sim_until_age=sim_until_age
    )

# =========================
# ---- Show Results (Two Tabs) ----
# =========================
sim = st.session_state["sim"]
if not sim:
    st.info("Set your inputs and tap **🚀 Run / Update FIRE Simulation**.")
else:
    tax_tab, retire_tab = st.tabs(["Tax Planning", "Retirement Planning"])

    # ---------- TAX PLANNING ----------
    with tax_tab:
        st.subheader("📋 Tax Summary")
        c1, c2, c3 = st.columns(3)
        c1.metric("AGI", money(sim["agi"]))
        c2.metric("Total Taxes", money(sim["total_tax"]))
        c3.metric("Effective Tax Rate", pct(sim["effective_tax_rate"]))

        c1.metric("After-Tax Income", money(sim["after_tax_income"]))
        c2.metric("Annual Savings (total)", money(sim["total_savings"]))
        c3.metric("Disposable ($)", money(sim["disposable_income"]))

        for msg in sim["warn_msgs"]:
            st.warning(msg)

        with st.expander("Contribution Impact (vs. no contributions)", expanded=False):
            std_ded = STANDARD_DEDUCTION_2025_SINGLE if filing_status == "Single" else STANDARD_DEDUCTION_2025_MARRIED
            baseline_pension_contribution = sim["pension_contribution"]
            baseline_agi = gross_salary - baseline_pension_contribution
            baseline_taxable_income = max(baseline_agi - std_ded, 0)
            baseline_federal_tax = calculate_tax(baseline_taxable_income, FEDERAL_BRACKETS_2025_SINGLE if filing_status=="Single" else FEDERAL_BRACKETS_2025_MARRIED)
            baseline_state_tax = calculate_tax(baseline_taxable_income, VIRGINIA_BRACKETS_2025)
            baseline_total_tax = baseline_federal_tax + baseline_state_tax
            baseline_after_tax_income = gross_salary - baseline_pension_contribution - baseline_total_tax
            baseline_disposable_income = baseline_after_tax_income

            col1, col2, col3 = st.columns(3)
            col1.metric("Δ Taxes Paid", money(baseline_total_tax - sim["total_tax"]))
            col2.metric("Annual Savings (total)", money(sim["total_savings"]))
            col3.metric("Δ Disposable ($)", money((sim["after_tax_income"] - sim["post_tax_savings"]) - baseline_disposable_income))

    # ---------- RETIREMENT PLANNING ----------
    with retire_tab:
        st.subheader("🏁 FI Milestones (ordered by time)")
        # Ordered milestone table, decimal years everywhere
        ordered = []
        ordered_names = [
            "Coast FI",
            "Flamingo FI (50% of FI #)",
            "Barista FI (covers ~50% of expenses)",
            "Lean FI (75% Expenses)",
            "Chubby FI (~120% Expenses)",
            "Full FI (100% Expenses)",
            "Fat FI (150% Expenses)",
            "Obese FI (200% Expenses)",
        ]
        for name in ordered_names:
            eta = sim["milestone_eta"].get(name)
            if eta is not None and eta > sim["sim_years"] + 1e-6:
                eta = None
            display = format_eta_decimal(eta if eta is not None else None)
            sort_key = 10**9 if eta is None else eta
            ordered.append((name, display, sort_key))
        ordered.sort(key=lambda x: x[2])
        st.table(pd.DataFrame([(n, d) for n, d, _ in ordered], columns=["Milestone", "ETA (years)"]))

        with st.expander("What the milestones mean", expanded=False):
            st.markdown(f"""
- **Coast FI**: Invested today grows to **Full FI** by ~**{sim['years_until_ret']} years** with **no new contributions**.
- **Barista FI**: Portfolio supports **~50%** of expenses at your SWR; rest from part-time/lower-pay work.
- **Flamingo FI**: Build **~50%** of your Full FI number, then **downshift**; compounding finishes the job.
- **Lean FI**: Supports **75%** of expenses.
- **Full FI**: Supports **100%** of expenses.
- **Chubby FI**: **~120%** of expenses (extra cushion).
- **Fat FI**: **150%** of expenses (lux/cushion).
- **Obese FI**: **200%** of expenses (very large margin).
""")

        # ---- Growth chart (Altair if available, with cap) ----
        st.subheader("📈 Investment Growth Over Time")
        chart_units = st.radio(
            "Chart units", ["Nominal ($ at future dates)", "Real (today's $)"],
            index=1, horizontal=True, key="chart_units_mode"
        )
        use_real = (chart_units == "Real (today's $)")
        series = sim["real_balances"] if use_real else sim["balances"]

        guide_year = min(sim["years_until_ret"], sim["sim_years"])

        if ALT_AVAILABLE:
            chart_df = pd.DataFrame({
                "Year": sim["years"],
                "Nominal": sim["balances"],
                "Real": sim["real_balances"],
            })
            y_field = "Real" if use_real else "Nominal"
            base = alt.Chart(chart_df).mark_line().encode(
                x=alt.X("Year:Q", title="Years from today", scale=alt.Scale(domain=(0, sim["sim_years"]))),
                y=alt.Y(f"{y_field}:Q", title="Portfolio Value ($)", axis=alt.Axis(format="~s")),
                tooltip=[alt.Tooltip("Year:Q"), alt.Tooltip(f"{y_field}:Q", title="Value", format="$.2s")]
            ).properties(height=320).interactive()
            st.altair_chart(base, use_container_width=True)
        else:
            fig2, ax2 = plt.subplots()
            years = sim["years"]
            if years and series:
                ax2.plot(years, series, label="Projected Portfolio Value")
                # Vertical markers (within cap)
                for h, label in [(5, "5 yrs"), (10, "10 yrs")]:
                    if h <= sim["sim_years"]:
                        ax2.axvline(h, linestyle=':', alpha=0.35)
                        y_for_text = series[h-1] * 0.02 if series[h-1] > 0 else 1.0
                        ax2.annotate(label, xy=(h, y_for_text), xytext=(h+0.2, y_for_text*1.05), fontsize=8)

                # Guide-lines (Lean/Full/Chubby) — keep chart uncluttered; Obese not drawn to avoid noise
                if use_real:
                    full_line, chubby_line, lean_line = sim["base_full_fi"], sim["base_chubby_fi"], sim["base_lean_fi"]
                    caption_tail = " (real, today's $)"
                else:
                    if sim["expense_inflation_on"]:
                        inflated_exp = inflate_expense(sim["annual_expenses"], sim["inflation"], guide_year)
                    else:
                        inflated_exp = sim["annual_expenses"]
                    full_line   = inflated_exp / sim["swr"]
                    chubby_line = (inflated_exp * 1.20) / sim["swr"]
                    lean_line   = (inflated_exp * 0.75) / sim["swr"]
                    caption_tail = f" (nominal @ ~{guide_year}y; expense inflation {'ON' if sim['expense_inflation_on'] else 'OFF'})"

                ax2.axhline(y=full_line, linestyle='--', label=f'Full FI{caption_tail}')
                ax2.axhline(y=chubby_line, linestyle=':',  label=f'Chubby FI{caption_tail}')
                ax2.axhline(y=lean_line, linestyle='-.',   label=f'Lean FI{caption_tail}')

                # Full FI annotation
                ffi = st.session_state["sim"]["full_fi_first_year"]
                if ffi is not None and 1 <= ffi <= sim["sim_years"]:
                    y = series[ffi-1]
                    ax2.axvline(ffi, linestyle=':', alpha=0.6)
                    ax2.scatter([ffi], [y], zorder=5)
                    right_side = ffi < (len(years) * 0.7)
                    ax2.annotate(f"Full FI in {ffi:.1f} yrs\n{money(y)}",
                                 xy=(ffi, y),
                                 xytext=(ffi + (1 if right_side else -1), y * 1.05),
                                 arrowprops=dict(arrowstyle="->", lw=1),
                                 fontsize=9, ha="left" if right_side else "right")
                ax2.set_xlim(0, sim["sim_years"])
                ax2.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f'${int(x/1000)}k' if x < 1_000_000 else f'${x/1_000_000:.1f}M'))
                ax2.set_xlabel("Years from today"); ax2.set_ylabel("Portfolio Value ($)")
                ax2.legend()
            else:
                ax2.text(0.5, 0.5, "No data to plot", ha='center', va='center')
            st.pyplot(fig2)

        # ---- Snapshots & Buckets ----
        st.subheader("📌 Snapshot & Buckets")
        default_label = f"Retirement horizon (~{sim['years_until_ret']} years)"
        fi_label = "First year you reach Full FI"
        five_label = "5 years from today"
        ten_label  = "10 years from today"

        options = []
        if sim.get("snapshot_5yr") and 5  <= sim["sim_years"]: options.append(five_label)
        if sim.get("snapshot_10yr") and 10 <= sim["sim_years"]: options.append(ten_label)
        options += [default_label, fi_label]

        snapshot_choice = st.radio(
            "Balance snapshot at",
            options,
            index=options.index(default_label) if default_label in options else 0,
            key="snapshot_choice",
        )

        # Pick nominal snapshot & set guide horizon
        if snapshot_choice == five_label and sim.get("snapshot_5yr"):
            snapshot_to_use = sim["snapshot_5yr"]; snapshot_year_text = "(~5 years)"; guide_year = 5
        elif snapshot_choice == ten_label and sim.get("snapshot_10yr"):
            snapshot_to_use = sim["snapshot_10yr"]; snapshot_year_text = "(~10 years)"; guide_year = 10
        elif snapshot_choice == fi_label and sim.get("snapshot_full_fi") is not None:
            snapshot_to_use = sim["snapshot_full_fi"]; snapshot_year_text = f"(year {st.session_state['sim']['full_fi_first_year']})"; guide_year = st.session_state["sim"]["full_fi_first_year"] or sim["years_until_ret"]
        else:
            if snapshot_choice == fi_label and sim.get("snapshot_full_fi") is None:
                st.info("You do not reach Full FI within the capped horizon. Showing retirement-horizon snapshot instead.")
            snapshot_to_use = sim["snapshot_at_ret"]; snapshot_year_text = f"(~{sim['years_until_ret']} years)"; guide_year = sim["years_until_ret"]

        # Real snapshot for same horizon
        if snapshot_choice == five_label and sim.get("real_snapshot_5yr"):
            real_snapshot = sim["real_snapshot_5yr"]
        elif snapshot_choice == ten_label and sim.get("real_snapshot_10yr"):
            real_snapshot = sim["real_snapshot_10yr"]
        elif snapshot_choice == fi_label and sim.get("real_snapshot_full_fi") is not None:
            real_snapshot = sim["real_snapshot_full_fi"]
        else:
            real_snapshot = sim["real_snapshot_at_ret"]

        # Buckets build
        def tax_bucket(acct_name: str) -> str:
            roth = {"Roth IRA", "403(b) Roth", "457(b) Roth"}
            traditional = {
                "Traditional IRA", "403(b) Traditional", "457(b) Traditional",
                "401(a) Employee", "401(a) Employer", "Solo 401(k) Employee",
                "Solo 401(k) Employer", "SEP IRA", "SIMPLE IRA"
            }
            hsa = {"HSA"}; education = {"529 Plan", "ESA"}
            taxable = {"Brokerage", "Crypto", "Other Investments"}
            if acct_name in roth: return "Roth (tax-free withdrawals, rules apply)"
            if acct_name in traditional: return "Traditional / Pre-tax (taxable withdrawals)"
            if acct_name in hsa: return "HSA (triple-advantaged, med. rules)"
            if acct_name in education: return "Education (529/ESA)"
            if acct_name in taxable: return "Taxable / Non-advantaged"
            return "Other / Unclassified"

        bucket_sums, bucket_sums_real = {}, {}
        for acct, bal in snapshot_to_use.items():
            b = tax_bucket(acct); bucket_sums[b] = bucket_sums.get(b, 0.0) + bal
        for acct, bal in real_snapshot.items():
            b = tax_bucket(acct); bucket_sums_real[b] = bucket_sums_real.get(b, 0.0) + bal

        bucket_rows = []
        for b in sorted(set(bucket_sums) | set(bucket_sums_real)):
            bucket_rows.append({
                "Bucket": b,
                "Projected Balance (Nominal)": money(bucket_sums.get(b, 0.0)),
                "Projected Balance (Real)":    money(bucket_sums_real.get(b, 0.0)),
            })
        with st.expander(f"Projected Balances by Tax Bucket {snapshot_year_text}", expanded=True):
            bucket_df = pd.DataFrame(bucket_rows)
            st.dataframe(bucket_df, use_container_width=True)

        acct_rows = []
        for acct in sorted(set(snapshot_to_use.keys()) | set(real_snapshot.keys())):
            acct_rows.append({
                "Account": acct, "Bucket": tax_bucket(acct),
                "Nominal": money(snapshot_to_use.get(acct, 0.0)),
                "Real":    money(real_snapshot.get(acct, 0.0)),
            })
        with st.expander(f"Per-Account Balances {snapshot_year_text}", expanded=False):
            st.dataframe(pd.DataFrame(acct_rows), use_container_width=True)

        # ---- Total Assets Summary (Nominal vs Real) ----
        st.subheader("🧮 Total Assets Summary")
        total_nominal = sum(snapshot_to_use.values())
        total_real = sum(real_snapshot.values())
        c1, c2 = st.columns(2)
        c1.metric("Total Assets (Nominal)", money(total_nominal))
        c2.metric("Total Assets (Real, today's $)", money(total_real))

        if ALT_AVAILABLE:
            sum_df = pd.DataFrame({"Type": ["Nominal", "Real"], "Amount": [total_nominal, total_real]})
            bar = alt.Chart(sum_df).mark_bar().encode(
                x=alt.X("Type:N", title=""),
                y=alt.Y("Amount:Q", title="Total", axis=alt.Axis(format="~s")),
                tooltip=[alt.Tooltip("Type:N"), alt.Tooltip("Amount:Q", title="Total", format="$.2s")]
            ).properties(height=220)
            st.altair_chart(bar, use_container_width=True)

            # Optional: allocation pie by bucket (nominal)
            pie_df = pd.DataFrame({"Bucket": list(bucket_sums.keys()), "Amount": list(bucket_sums.values())})
            if len(pie_df):
                pie = alt.Chart(pie_df).mark_arc().encode(
                    theta="Amount:Q",
                    color=alt.Color("Bucket:N", legend=alt.Legend(title="Bucket")),
                    tooltip=[alt.Tooltip("Bucket:N"), alt.Tooltip("Amount:Q", format="$.2s")]
                ).properties(height=260)
                st.altair_chart(pie, use_container_width=True)
        else:
            st.caption("Install `altair` to see summary charts. Showing totals above.")
