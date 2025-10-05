import math
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# Optional (nice stacked chart). App works without it.
try:
    import altair as alt
    ALT_AVAILABLE = True
except Exception:
    ALT_AVAILABLE = False

# ----------------------------
# Session: where we keep sims
# ----------------------------
if "sim" not in st.session_state:
    st.session_state["sim"] = None

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

# Virginia (start-of-bracket style)
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
# ---- App ----
# =========================

st.set_page_config(page_title="🔥 FIRE Tax + FI Planner 2025", layout="wide")
st.title("🔥 FIRE Tax + FI Planner 2025 (Federal + Virginia) 🔥")

with st.expander("Assumptions", expanded=False):
    st.markdown(
        "- 2025 **federal** & **Virginia** tax brackets (start-of-bracket).\n"
        "- Uses the **standard deduction** by filing status.\n"
        "- Virginia 529 deduction capped at **$4,000**.\n"
        "- **SWR** drives FI targets (you control the %).\n"
        "- **Horizon** uses **Years until retirement = target age − current age**.\n"
        "- This is a simplification (ignores credits/phaseouts, SS/Medicare, LTCG/qualified dividends, NIIT, etc.)."
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

# Horizon
st.sidebar.header("Retirement Horizon")
current_age = st.sidebar.number_input("Current age", value=40, step=1, min_value=0)
target_age = st.sidebar.number_input("Target retirement age", value=58, step=1, min_value=0)
years_until_ret = max(1, int(round(target_age - current_age)))  # ≥1

# Portfolio-level default return
default_return_all_else = 0.08   # 8% default for “everything else”

# ===========================================
# ---- Accounts (Core vs More, with Crypto) --
# ===========================================

st.sidebar.header("Choose Accounts to Contribute To")

# Core with your requested defaults CHECKED + default contribution amounts
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
        "403(b) Roth": st.checkbox("403(b) Roth", value=True),  # has a starting balance in defaults
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

# Contributions — defaults as requested
st.sidebar.header("Annual Contributions ($/year)")
contributions = {}
for account, enabled in {**core_accounts, **more_accounts}.items():
    if enabled:
        key = ("core_" if account in core_accounts else "more_") + account
        default_val = 0
        if account == "457(b) Traditional":
            default_val = 15000
        if account == "403(b) Traditional":
            default_val = 23500
        if account == "Crypto":
            default_val = 15000
        if account == "Roth IRA":
            default_val = 5000
        contributions[account] = st.sidebar.number_input(f"{account} Contribution ($)", value=default_val, step=500, key=key)

# ---- 2025 limit hints (warnings only) ----
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

# ---- Brackets & Deduction ----
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
# Default ON per your request
granular_mode = st.sidebar.checkbox("Enable granular balances & per-account returns", value=True)

ALL_ACCOUNTS = list(core_accounts.keys()) + list(more_accounts.keys())
account_start_balances = {}
account_returns = {}

# Your requested default balances & returns:
DEFAULT_BALANCES = {
    "Crypto": 250_000,
    "403(b) Traditional": 176_000,
    "403(b) Roth": 28_000,
    "457(b) Traditional": 112_000,
    "457(b) Roth": 300,
    "Traditional IRA": 67_000,
    "Roth IRA": 123_000,
}
DEFAULT_RETURNS = {
    "Crypto": 0.20,  # 20%
    # everything else -> 8%
}

# Set a default “current total” to match the sum of the defaults so Other=0 by default
default_total_investments = sum(DEFAULT_BALANCES.values())

# Portfolio-level default current total
current_investments = st.sidebar.number_input(
    "Current Total Investment Value ($)",
    value=default_total_investments,
    step=1000
)

# Default selected accounts for granular mode (the ones you gave balances for)
default_granular_selection = list(DEFAULT_BALANCES.keys())

if granular_mode:
    st.sidebar.caption("Specify starting balances & returns for selected accounts. Unassigned remainder → 'Other Investments'.")
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
    # ------ Taxes / cash flow ------
    pension_contribution = gross_salary * pension_percent
    agi = gross_salary - pension_contribution

    agi_reducing_accounts = [
        "403(b) Traditional", "457(b) Traditional",
        "401(a) Employee", "Solo 401(k) Employee",
        "SEP IRA", "SIMPLE IRA", "Traditional IRA",
        "HSA", "FSA"
    ]
    employer_funded_accounts = ["401(a) Employer"]

    for acct in agi_reducing_accounts:
        agi -= contributions.get(acct, 0)

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
    post_tax_savings = total_savings - pre_tax_sum - employer_sum
    disposable_income = after_tax_income - post_tax_savings

    # ------ Warnings (non-blocking) ------
    hints = hints  # from sidebar
    ira_total = contributions.get("Traditional IRA", 0) + contributions.get("Roth IRA", 0)
    warn_msgs = []
    if ira_total > hints["IRA (Traditional/Roth) combined"]:
        warn_msgs.append(f"IRA combined {money(ira_total)} > {money(hints['IRA (Traditional/Roth) combined'])}")
    def over(a, b, key, label):
        t = contributions.get(a, 0) + contributions.get(b, 0)
        if t > hints[key]:
            warn_msgs.append(f"{label} {money(t)} > {money(hints[key])}")
    over("457(b) Traditional", "457(b) Roth", "457(b) employee deferral", "457(b)")
    over("403(b) Traditional", "403(b) Roth", "403(b) employee deferral", "403(b)")
    if post_tax_savings > after_tax_income:
        warn_msgs.append("Post-tax savings > after-tax income (negative disposable).")

    # ------ Portfolio model ------
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

    # Targets
    if swr <= 0:
        st.error("Safe Withdrawal Rate must be > 0%.")
        st.stop()
    full_fi_target     = annual_expenses / swr
    lean_fi_target     = (annual_expenses * 0.75) / swr
    chubby_fi_target   = (annual_expenses * 1.20) / swr
    fat_fi_target      = (annual_expenses * 1.50) / swr
    barista_fi_target  = (annual_expenses * 0.50) / swr
    flamingo_fi_target = 0.50 * full_fi_target
    coast_fi_target    = full_fi_target / ((1 + default_return_all_else) ** years_until_ret) if default_return_all_else > -1 else math.inf

    milestone_defs = [
        ("Coast FI", coast_fi_target),
        ("Flamingo FI (50% of FI #)", flamingo_fi_target),
        ("Barista FI (covers ~50% of expenses)", barista_fi_target),
        ("Lean FI (75% Expenses)", lean_fi_target),
        ("Chubby FI (~120% Expenses)", chubby_fi_target),
        ("Full FI (100% Expenses)", full_fi_target),
        ("Fat FI (150% Expenses)", fat_fi_target),
    ]

    years, balances = [], []
    milestone_years = {name: 0 if sum(b["balance"] for b in portfolio.values()) >= target else None
                       for name, target in milestone_defs}
    snapshot_at_ret = None
    full_fi_first_year = None
    snapshot_full_fi = None

    for year in range(1, 51):
        for acct in portfolio:
            r = portfolio[acct]["return"]
            portfolio[acct]["balance"] = portfolio[acct]["balance"] * (1 + r) + annual_contribs.get(acct, 0.0)
        total_balance = sum(b["balance"] for b in portfolio.values())
        years.append(year); balances.append(total_balance)

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

    # Save everything so toggling radios doesn't wipe results
    st.session_state["sim"] = dict(
        # cash/tax
        agi=agi, taxable_income=taxable_income, federal_tax=federal_tax, state_tax=state_tax,
        total_tax=total_tax, effective_tax_rate=effective_tax_rate, after_tax_income=after_tax_income,
        total_savings=total_savings, employer_sum=employer_sum, post_tax_savings=post_tax_savings,
        disposable_income=disposable_income, pension_contribution=pension_contribution,
        warn_msgs=warn_msgs,
        # portfolio
        portfolio=portfolio, annual_contribs=annual_contribs,
        years=years, balances=balances,
        full_fi_target=full_fi_target, lean_fi_target=lean_fi_target,
        chubby_fi_target=chubby_fi_target, fat_fi_target=fat_fi_target,
        barista_fi_target=barista_fi_target, flamingo_fi_target=flamingo_fi_target,
        years_until_ret=years_until_ret,
        snapshot_at_ret=snapshot_at_ret, snapshot_full_fi=snapshot_full_fi,
        full_fi_first_year=full_fi_first_year,
        milestone_defs=milestone_defs, milestone_years=milestone_years,
        swr_percent=swr_percent, annual_expenses=annual_expenses
    )

# =========================
# ---- Show Results ----
# =========================
sim = st.session_state["sim"]

if not sim:
    st.info("Set your inputs and click **🚀 Run / Update FIRE Simulation**.")
else:
    # Show warnings
    for msg in sim["warn_msgs"]:
        st.warning(msg)

    # Summary
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
            "Employer-Funded Savings (no take-home impact)",
            "Employee-Funded Savings (affects take-home)",
            "Disposable Income (After Taxes & Post-Tax Savings)"
        ],
        "Amount": [
            money(sim["agi"]),
            money(sim["taxable_income"]),
            money(sim["federal_tax"]),
            money(sim["state_tax"]),
            money(sim["total_tax"]),
            pct(sim["effective_tax_rate"]),
            money(sim["after_tax_income"]),
            money(sim["total_savings"]),
            money(sim["employer_sum"]),
            money(sim["total_savings"] - sim["employer_sum"]),
            money(sim["disposable_income"])
        ]
    })
    st.dataframe(fire_summary)

    # Assumed returns (debug)
    st.caption("Assumed per-account returns (after normalization)")
    st.dataframe(pd.DataFrame(
        [{"Account": a, "Assumed Return": pct(sim["portfolio"][a]['return'])}
         for a in sorted(sim["portfolio"].keys())]
    ), use_container_width=True)

    # Milestones table ordered by time
    ordered = []
    for name, _ in sim["milestone_defs"]:
        yr = sim["milestone_years"][name]
        if yr is None:
            display = ">50 years"; sort_key = 10**9
        elif yr == 0:
            display = "0 years (✅ already)"; sort_key = 0
        else:
            display = f"{yr} years"; sort_key = yr
        ordered.append((name, display, sort_key))
    ordered.sort(key=lambda x: x[2])

    st.subheader(f"🏁 FI Milestones (SWR = {sim['swr_percent']:.1f}%) — ordered by time to achieve")
    st.table(pd.DataFrame([(n, d) for n, d, _ in ordered], columns=["Milestone", "Time to Achieve"]))

    # Milestone explanations
    st.subheader("📖 What the Milestones Mean (typical progression)")
    st.markdown(f"""
- **Coast FI** *(meta milestone)*: Invested today grows to your **Full FI** target by ~**{sim['years_until_ret']} years** with **no additional contributions**.
- **Barista FI**: Portfolio supports **~50%** of your annual expenses at your SWR; remaining ~50% from part-time/lower-pay work.
- **Flamingo FI**: Build **~50%** of your Full FI number, then **downshift**—let compounding finish the job.
- **Lean FI**: Portfolio supports **75%** of expenses.
- **Full FI**: Portfolio supports **100%** of expenses.
- **Chubby FI**: Comfortable middle-ground—**~120%** of expenses.
- **Fat FI**: Portfolio supports **150%** of expenses.
""")

    # Growth chart
    st.subheader("📈 Investment Growth Over Time")
    fig2, ax2 = plt.subplots()
    years, balances = sim["years"], sim["balances"]
    if years and balances:
        ax2.plot(years, balances, label="Projected Portfolio Value")
        if sim["full_fi_first_year"] is not None and 1 <= sim["full_fi_first_year"] <= len(years):
            x = sim["full_fi_first_year"]; y = balances[x - 1]
            ax2.axvline(x, linestyle=':', alpha=0.6)
            ax2.scatter([x], [y], zorder=5)
            right_side = x < (len(years) * 0.7)
            x_text = x + 1 if right_side else x - 1
            y_text = y * (1.06 if right_side else 1.04)
            ax2.annotate(
                f"Full FI in {x} yrs\n{money(y)}",
                xy=(x, y), xytext=(x_text, y_text),
                arrowprops=dict(arrowstyle="->", lw=1), fontsize=9,
                ha="left" if right_side else "right"
            )
        ax2.axhline(y=sim["full_fi_target"], linestyle='--', label=f'Full FI ({money(sim["full_fi_target"])})')
        ax2.axhline(y=sim["chubby_fi_target"], linestyle=':', label=f'Chubby FI ({money(sim["chubby_fi_target"])})')
        ax2.axhline(y=sim["lean_fi_target"], linestyle='-.', label=f'Lean FI ({money(sim["lean_fi_target"])})')
        ax2.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f'${int(x/1000)}k' if x < 1_000_000 else f'${x/1_000_000:.1f}M')
        )
        ax2.set_xlabel("Years"); ax2.set_ylabel("Portfolio Value ($)")
        ax2.legend()
    else:
        ax2.text(0.5, 0.5, "No data to plot", ha='center', va='center')
    st.pyplot(fig2)

    # Snapshot selector (persisted; won’t reset sim)
    default_label = f"Retirement horizon (~{sim['years_until_ret']} years)"
    fi_label = "First year you reach Full FI"
    snapshot_choice = st.radio(
        "Balance snapshot at",
        [default_label, fi_label],
        index=0, key="snapshot_choice",
        help="Flip views freely — results are cached so the app won’t reset."
    )
    if snapshot_choice == fi_label and sim["snapshot_full_fi"] is not None:
        snapshot_to_use = sim["snapshot_full_fi"]; snapshot_year_text = f"(year {sim['full_fi_first_year']})"
    else:
        if snapshot_choice == fi_label and sim["snapshot_full_fi"] is None:
            st.info("You do not reach Full FI within the 50-year simulation. Showing retirement-horizon snapshot instead.")
        snapshot_to_use = sim["snapshot_at_ret"]; snapshot_year_text = f"(~{sim['years_until_ret']} years)"

    # ---- Buckets
    st.subheader(f"🏦 Projected Balances by Tax Bucket {snapshot_year_text}")

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
        acct_rows.append({"Account": acct, "Bucket": tax_bucket(acct), "Projected Balance": money(bal)})
    st.dataframe(pd.DataFrame(acct_rows), use_container_width=True)

    # Allocation chart (optional)
    st.subheader("🚀 Contribution Impact Summary")
    baseline_pension_contribution = sim["pension_contribution"]
    baseline_agi = gross_salary - baseline_pension_contribution
    baseline_taxable_income = max(baseline_agi - (STANDARD_DEDUCTION_2025_SINGLE if filing_status=="Single" else STANDARD_DEDUCTION_2025_MARRIED), 0)
    baseline_federal_tax = calculate_tax(baseline_taxable_income, federal_brackets)
    baseline_state_tax = calculate_tax(baseline_taxable_income, VIRGINIA_BRACKETS_2025)
    baseline_total_tax = baseline_federal_tax + baseline_state_tax
    baseline_after_tax_income = gross_salary - baseline_pension_contribution - baseline_total_tax
    baseline_disposable_income = baseline_after_tax_income

    col1, col2, col3 = st.columns(3)
    col1.metric("Δ Taxes Paid", money(baseline_total_tax - sim["total_tax"]))
    col2.metric("Annual Savings (total, incl. employer)", money(sim["total_savings"]))
    col3.metric("Δ Disposable Income", money((sim["after_tax_income"] - sim["post_tax_savings"]) - baseline_disposable_income))

    savings_for_cashflow = sim["total_savings"] - sim["employer_sum"]
    allocation_rows = [
        {"Scenario": "No Contributions",   "Category": "Pension",        "Amount": baseline_pension_contribution},
        {"Scenario": "No Contributions",   "Category": "Federal Taxes",  "Amount": baseline_federal_tax},
        {"Scenario": "No Contributions",   "Category": "State Taxes",    "Amount": baseline_state_tax},
        {"Scenario": "No Contributions",   "Category": "Savings",        "Amount": 0},
        {"Scenario": "No Contributions",   "Category": "Disposable",     "Amount": baseline_disposable_income},

        {"Scenario": "With Contributions", "Category": "Pension",        "Amount": sim["pension_contribution"]},
        {"Scenario": "With Contributions", "Category": "Federal Taxes",  "Amount": sim["federal_tax"]},
        {"Scenario": "With Contributions", "Category": "State Taxes",    "Amount": sim["state_tax"]},
        {"Scenario": "With Contributions", "Category": "Savings",        "Amount": savings_for_cashflow},
        {"Scenario": "With Contributions", "Category": "Disposable",     "Amount": max(sim["disposable_income"], 0)},
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
                  ).properties(height=300)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.dataframe(alloc_df.pivot_table(index="Category", columns="Scenario", values="Amount"))
    except Exception as e:
        st.warning(f"Allocation chart unavailable ({e}). Showing table instead.")
        st.dataframe(alloc_df.pivot_table(index="Category", columns="Scenario", values="Amount"))
