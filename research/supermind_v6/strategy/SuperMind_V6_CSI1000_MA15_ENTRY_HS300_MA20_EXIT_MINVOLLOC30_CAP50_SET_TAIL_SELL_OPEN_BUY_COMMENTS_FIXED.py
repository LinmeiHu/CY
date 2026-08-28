import numpy as np
import pandas as pd


# ============================================================
# SuperMind ETF Momentum
# V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_SET
# HYBRID EXECUTION: TAIL SELL + NEXT OPEN BUY
#
# BUY SIDE
# - use the OFFICIAL completed daily close of signal day t
# - evaluate the CSI1000 MA15 entry gate, B60, FULL40, MINVOLLOC30 and
#   cross-sectional 20/60/120 RS after t has fully closed
# - execute new entries / target restoration at t+1 opening auction
# - open_auction() is used when the engine exposes it; enable_open_bar()
#   adds a 09:30 minute callback as the minute-backtest fallback
#
# SELL SIDE
# - at 14:57 on day t, use the causally available 14:57-minute OPEN
#   as today's pseudo-close
# - evaluate ETF MA40 x 2, weekly HS300 MA20 exit and the 2% daily
#   emergency exit
# - submit SELL-ONLY orders at the 15:00 bar and match them at the
#   current bar close through set_execution('close')
# - no ETF is bought or rebalanced at the close
#
# OFFICIAL-CLOSE EXIT FALLBACK
# - if the final close crosses an exit threshold only after 14:57, or a
#   tail sell is not fully completed, before_trading() detects/retries it
#   and sells at the next opening auction
#
# Frozen V6 structure retained:
# - B60: close strictly above the previous 60 trading-day closes
# - FULL40:
#     prior 40-day close range <= 12.5%
#     previous-day MA5/10/20/30 dispersion <= 5%
#     40-day direction efficiency <= 0.40
#     10d / 60d realized-vol ratio <= 0.90
# - MINVOLLOC_L30_C0.50, signal-day volume excluded
# - max 5 ETFs with CAP50_SET allocation:
#     per-ETF target = min(50%, 1 / target-member count)
#     N=1/2/3/4/5 -> 50%/50%/33.33%/25%/20% per ETF
# - rebalance all surviving/desired members only when membership changes;
#   ordinary price drift does not trigger daily rebalancing
# - CSI1000 000852.SH close > MA15 controls NEW ENTRY only
# - HS300 ETF 510300.SH retains portfolio-level exit duties
# - no rank replacement while all five slots are occupied
#
# Important:
# The exact original V6 asset_balanced ranking source is unavailable.
# This runnable version preserves the supplied transparent V5 fallback:
# cross-sectional 20/60/120 relative strength.
#
# SuperMind backtest frequency MUST be MINUTE / 1m.
# ============================================================


def raw_code(symbol):
    s = ''.join([c for c in str(symbol) if c.isdigit()])
    if len(s) >= 6:
        return s[:6]
    return s.zfill(6)


def expected_sm_symbol(raw):
    s = raw_code(raw)
    if s.startswith('5'):
        return s + '.SH'
    if s.startswith('1'):
        return s + '.SZ'
    return s


def init(context):
    set_benchmark('000300.SH')

    # Approximate the frozen V6 research assumption of ~10bp/side:
    # commission 2bp + price slippage about 8bp/side.
    set_commission(PerShare(type='stock', cost=0.0002))
    set_slippage(PriceSlippage(0.0016))
    set_volume_limit(0.25, 0.5)

    # One global minute-backtest execution mode is required.
    # 'close' lets 15:00 SELL orders match the current closing bar.
    # Opening orders are sent from open_auction() when available, or
    # from the special 09:30 bar added by enable_open_bar().
    set_execution('close')
    enable_open_bar()

    # ENTRY and EXIT anchors are intentionally separated.
    # Current configuration: CSI1000 MA15 controls only NEW ENTRY permission;
    # HS300 ETF retains all portfolio-level exit duties.
    context.market_entry_anchor = '000852.SH'
    context.market_exit_anchor = '510300.SH'
    context.market_entry_ma = 15  # CSI1000 market-entry gate
    context.market_exit_ma = 20   # HS300 ETF portfolio-level exit anchor

    context.max_holdings = 5

    # CAP50_SET: when the target member set changes, resize every desired
    # holding to min(50%, 1/N). Between set changes, allow weights to drift.
    context.position_cap = 0.50

    context.breakout_days = 60
    context.box_days = 40
    context.box_width_max = 0.125
    context.ma_dispersion_max = 0.05
    context.direction_efficiency_max = 0.40
    context.vol_ratio_max = 0.90

    # --------------------------------------------------------
    # Horizontal-consolidation volume-position filter
    # --------------------------------------------------------
    # Research rule: MINVOLLOC_L30_C0.50
    #
    # HARD   : block a new entry when the rule fails.
    # SHADOW : calculate and log the rule, but preserve old V6 entries.
    # OFF    : skip the rule entirely.
    #
    # This affects NEW ENTRIES only. It does not force an exit from an
    # existing holding and does not change FULL40 or cross-sectional RS.
    context.minvol_filter_mode = 'HARD'
    context.minvol_lookback = 30
    context.minvol_price_location_max = 0.50

    # ETF-level rules are separate from the CSI1000 MA15 market gate.
    context.entry_ma = 20  # each candidate ETF must close above its own MA20
    context.exit_ma = 40
    context.exit_confirm = 2

    # --------------------------------------------------------
    # Market-level exit settings
    # --------------------------------------------------------
    # Modes:
    #   'WEEKLY'       : original V6 behavior. On the first trading day
    #                    of a new week, inspect the previous trading
    #                    day's 510300 close and MA20.
    #   'DAILY_BUFFER' : inspect every trading day; exit only when
    #                    510300 is sufficiently below MA20.
    #   'BOTH'         : weekly exit OR daily-buffer emergency exit.
    #   'NONE'         : disable market-level liquidation.
    #
    # BUGFIX CONTRACT:
    # The intended behavior is weekly normal liquidation PLUS a 2%
    # daily emergency liquidation.  Therefore BOTH must be used.
    # Use WEEKLY only when deliberately testing the pure-weekly V6.
    context.market_exit_mode = 'BOTH'

    # 0.00 = close < MA20
    # 0.02 = close < MA20 * 0.98 (2% below MA20)
    # 0.03 = close < MA20 * 0.97 (3% below MA20)
    # Official-close weekly rule remains unbuffered. It is used by the
    # next-open fallback when the final close crosses after 14:57.
    context.weekly_exit_buffer = 0.00

    # Separate tail buffer: keep at 0.00 for the pure 'all weekly exits
    # at the tail' test. A later 0.0025/0.005 experiment can change ONLY
    # this value, while formal-close fallback still uses the unbuffered rule.
    context.tail_weekly_exit_buffer = 0.00

    # Used only by DAILY_BUFFER or BOTH.
    context.daily_exit_buffer = 0.02

    # State used to identify the first trading day of a new week.
    # before_trading is called only on trading days, so comparing the
    # previous observed trading day with today handles Monday holidays
    # and long holiday breaks without calling get_trade_days().
    context.prev_trade_date = None

    context.min_turnover20 = 20000000.0

    # Need 121 closes to calculate a 120-day return exactly.
    # The historical methodology required at least 120 observations.
    context.min_history = 121
    context.history_days = 140
    context.history_batch_size = 20

    # July-20 snapshot supplied in this conversation: 152 unique ETFs.
    # Raw 6-digit codes are used here; daily active symbols are resolved
    # from get_all_securities('etf') to avoid future-listed ETFs.
    context.pool_raw = [
        '510300', '588000', '512880', '588200', '159915', '515880',
        '510500', '159516', '512890', '563360', '588170', '512100',
        '159995', '512170', '510880', '510050', '159819', '159949',
        '515050', '512480', '512400', '515450', '515180', '159530',
        '159992', '562500', '512010', '510180', '159326', '510210',
        '512070', '159928', '159201', '159206', '159781', '515220',
        '512690', '159870', '512800', '512760', '159611', '159869',
        '159755', '516650', '159852', '560860', '159307', '159363',
        '512710', '515980', '561980', '159865', '512660', '159263',
        '159851', '512950', '516150', '159967', '515790', '588220',
        '159259', '159796', '159980', '510810', '515300', '159227',
        '562800', '159566', '515230', '159993', '512040', '159938',
        '159859', '515800', '561380', '589720', '159736', '159583',
        '515170', '159399', '159883', '563300', '563230', '515000',
        '159562', '159732', '516160', '512290', '159901', '512980',
        '515900', '562060', '515650', '512200', '159623', '510720',
        '159766', '560280', '560080', '159625', '560050', '515030',
        '159593', '516510', '561580', '159235', '588790', '516350',
        '159667', '159929', '159207', '159209', '589070', '159692',
        '159141', '562550', '159905', '589680', '516820', '560710',
        '561360', '512670', '515400', '562950', '159825', '561550',
        '512940', '159622', '510150', '159758', '159998', '515700',
        '159601', '159680', '159837', '560570', '159997', '588020',
        '588460', '159697', '159876', '515630', '516970', '159638',
        '561420', '159387', '159325', '159790', '516570', '515210',
        '516130', '159880',
    ]

    context.pool_raw_set = set(context.pool_raw)
    context.static_symbols = [expected_sm_symbol(x) for x in context.pool_raw]

    # Minute callbacks / bar_dict coverage. Include both market anchors.
    context.security = list(context.static_symbols)
    for symbol in [context.market_entry_anchor, context.market_exit_anchor]:
        if symbol not in context.security:
            context.security.append(symbol)

    # Sticky exit state. Exits are retried until positions are actually gone.
    context.force_exit_all = False
    context.forced_sells = []

    # Official-close target prepared before t+1 open.
    context.pending_desired = None
    context.pending_reason = ''

    # CAP50_SET bookkeeping. This stores the member set most recently processed
    # by the opening target callback. A 14:57/15:00
    # tail exit changes actual membership without rebalancing survivors; the
    # mismatch is detected next morning and triggers one set-change rebalance.
    # Use a sorted list rather than a set for stable SuperMind context state.
    context.last_target_membership_raw = []

    # Sell-only queue frozen at 14:57 and consumed at the 15:00 close.
    context.pending_close_sells = []
    context.pending_close_reason = ''
    context.pending_close_date = None

    # Minute callback times and one-shot guards.
    context.open_hour = 9
    context.open_minute = 30
    context.signal_hour = 14
    context.signal_minute = 57
    context.close_hour = 15
    context.close_minute = 0
    context.last_open_execution_date = None
    context.last_intraday_signal_date = None
    context.last_close_execution_date = None
    context.minute_callback_seen = False

    log.info('V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_SET_TAIL_SELL_OPEN_BUY initialized')
    log.info('SUPERMIND SAFE MODE = EXPLICIT BAR FIELD ACCESS ONLY')
    log.info('STATIC POOL SIZE = {}'.format(len(context.pool_raw)))
    log.info('RANK MODE = V5_RS_20_60_120_FALLBACK')
    log.info(
        'ALLOCATION = CAP50_SET | cap={:.0%} | N=1/2/3/4/5 -> 50%/50%/33.33%/25%/20% | rebalance=SET_CHANGE_ONLY'
        .format(context.position_cap)
    )
    log.info(
        'ENTRY ANCHOR = {} (CSI1000 INDEX) | RULE = CLOSE > MA{}'
        .format(
            context.market_entry_anchor,
            context.market_entry_ma
        )
    )
    log.info(
        'EXIT ANCHOR = {} (HS300 ETF) | WEEKLY MA{} + DAILY EMERGENCY BUFFER'
        .format(
            context.market_exit_anchor,
            context.market_exit_ma
        )
    )
    log.info(
        'MARKET EXIT MODE = {} | OFFICIAL WEEKLY BUFFER = {:.2%} | TAIL WEEKLY BUFFER = {:.2%} | DAILY EMERGENCY BUFFER = {:.2%}'
        .format(
            context.market_exit_mode,
            context.weekly_exit_buffer,
            context.tail_weekly_exit_buffer,
            context.daily_exit_buffer
        )
    )
    log.info(
        'MINVOL FILTER = {} | FIELD=volume | LOOKBACK={} | MAX PRICE LOCATION={:.2f} | SIGNAL-DAY VOLUME EXCLUDED'
        .format(
            context.minvol_filter_mode,
            context.minvol_lookback,
            context.minvol_price_location_max
        )
    )
    log.info('BUY SIGNAL = OFFICIAL CLOSE | BUY EXECUTION = NEXT OPEN')
    log.info('SELL SIGNAL = 14:57 PSEUDO-CLOSE | SELL EXECUTION = SAME-DAY FINAL CLOSE')
    log.info("SUPERMIND EXECUTION MODE = close | enable_open_bar = ON")
    log.info('FREQUENCY MUST BE MINUTE / 1m')


# ============================================================
# Generic history helpers
# ============================================================

def normalize_history_result(result, symbols, fields):
    out = {}

    if result is None:
        return out

    # Multi-symbol, df=False, is_panel=False commonly returns:
    # {symbol: data}
    if isinstance(result, dict):
        for symbol in symbols:
            if symbol in result and result[symbol] is not None:
                out[symbol] = result[symbol]

        # Some environments may return a single-symbol field dict directly.
        if len(symbols) == 1 and len(out) == 0:
            ok = True
            for field in fields:
                if field not in result:
                    ok = False
                    break
            if ok:
                out[symbols[0]] = result

        return out

    # Defensive fallback for a single-symbol DataFrame.
    if len(symbols) == 1 and isinstance(result, pd.DataFrame):
        out[symbols[0]] = result

    return out


def load_history_recursive(symbols, fields, count):
    if symbols is None or len(symbols) == 0:
        return {}

    try:
        result = history(
            symbols,
            fields,
            count,
            '1d',
            False,
            'pre',
            False,
            False
        )

        out = normalize_history_result(
            result,
            symbols,
            fields
        )

        if len(out) > 0:
            return out

        raise Exception('history returned no recognized symbol data')

    except Exception as e:
        if len(symbols) == 1:
            log.warn(
                'SKIP HISTORY {} | {}'
                .format(symbols[0], e)
            )
            return {}

        mid = len(symbols) // 2

        left = load_history_recursive(
            symbols[:mid],
            fields,
            count
        )

        right = load_history_recursive(
            symbols[mid:],
            fields,
            count
        )

        left.update(right)
        return left


def load_pool_history(context, symbols):
    result = {}

    batch_size = context.history_batch_size

    for start in range(0, len(symbols), batch_size):
        batch = symbols[start:start + batch_size]

        part = load_history_recursive(
            batch,
            ['close', 'volume', 'turnover'],
            context.history_days
        )

        result.update(part)

    return result


def field_array(data, field):
    try:
        if isinstance(data, pd.DataFrame):
            values = data[field].values
        elif isinstance(data, pd.Series):
            values = data.values
        else:
            values = data[field]

        return np.asarray(values, dtype=float)

    except Exception:
        return np.asarray([], dtype=float)


def clean_close(data):
    arr = field_array(data, 'close')

    if len(arr) == 0:
        return arr

    return arr[np.isfinite(arr)]


# ============================================================
# Point-in-time active ETF universe
# ============================================================


def completed_daily_data(data, today):
    """Keep only completed daily rows strictly earlier than today."""
    if isinstance(data, pd.DataFrame):
        try:
            current_date = pd.Timestamp(today).normalize()
            idx = pd.to_datetime(data.index)
            mask = pd.DatetimeIndex(idx).normalize() < current_date
            return data.loc[mask]
        except Exception:
            return data

    # SuperMind's daily history in a minute callback normally excludes
    # the current, still-forming daily bar. Array results are therefore
    # retained unchanged.
    return data


def get_active_pool(context):
    try:
        sec_info = get_all_securities('etf')

        if sec_info is None or len(sec_info) == 0:
            raise Exception('empty ETF security list')

        by_raw = {}

        for symbol in sec_info.index:
            r = raw_code(symbol)

            if r in context.pool_raw_set:
                by_raw[r] = str(symbol)

        active = []

        for r in context.pool_raw:
            if r in by_raw:
                # Always trade with exchange suffixes in SuperMind.
                active.append(expected_sm_symbol(r))

        return active

    except Exception as e:
        log.warn(
            'get_all_securities(etf) failed, use static symbols | {}'
            .format(e)
        )

        return list(context.static_symbols)


# ============================================================
# Portfolio helpers
# ============================================================

def current_holdings(context):
    try:
        positions = context.portfolio.stock_account.positions
        held = list(positions)
    except Exception:
        held = []

    out = []

    for symbol in held:
        if raw_code(symbol) in context.pool_raw_set:
            out.append(symbol)

    return out


def cleanup_forced_sells(context, current):
    current_raw = set([raw_code(x) for x in current])

    context.forced_sells = [
        x for x in context.forced_sells
        if raw_code(x) in current_raw
    ]


def membership_signature(symbols):
    """Return a stable, de-duplicated raw-code membership signature."""
    seen = set()
    out = []

    for symbol in symbols:
        key = raw_code(symbol)
        if key not in seen:
            seen.add(key)
            out.append(key)

    return sorted(out)


def cap50_set_target_weight(context, desired):
    """CAP50_SET per-name target: min(50%, 1/N)."""
    member_count = len(membership_signature(desired))

    if member_count <= 0:
        return 0.0

    return min(
        float(context.position_cap),
        1.0 / float(member_count)
    )


def cap50_set_change_required(context, current, desired):
    """
    Rebalance only when membership changed or an earlier set-change order
    still has not made the actual holdings match the desired member set.

    Comparing with last_target_membership_raw is essential for the hybrid
    execution path: a member can be sold at 15:00, leaving surviving weights
    unchanged. The next morning actual==desired, but the last allocated set is
    still the pre-exit set, so survivors must be resized once.
    """
    current_signature = membership_signature(current)
    desired_signature = membership_signature(desired)
    last_signature = membership_signature(
        context.last_target_membership_raw
    )

    return bool(
        desired_signature != current_signature
        or desired_signature != last_signature
    )


def prepare_cap50_set_rebalance(context, current, desired, reason):
    """Queue one next-open CAP50_SET rebalance when a set change exists."""
    desired = list(desired)

    if not cap50_set_change_required(
        context,
        current,
        desired
    ):
        return False

    target_weight = cap50_set_target_weight(
        context,
        desired
    )

    context.pending_desired = desired
    context.pending_reason = str(reason)

    log.info(
        'PREPARE CAP50_SET | reason={} | current_set={} | last_target_set={} | desired_set={} | N={} | per_name_target={:.2%} | total_target={:.2%}'
        .format(
            context.pending_reason,
            membership_signature(current),
            membership_signature(
                context.last_target_membership_raw
            ),
            membership_signature(desired),
            len(membership_signature(desired)),
            target_weight,
            target_weight * len(membership_signature(desired))
        )
    )

    return True


# ============================================================
# CSI1000 MA15 entry gate and HS300 ETF MA20 portfolio-level exit
# ============================================================

def load_market_anchor_closes(context):
    """
    Load the ENTRY and EXIT anchors independently.

    ENTRY anchor:
        000852.SH (CSI1000 index), close > MA15 permits NEW entries.

    EXIT anchor:
        510300.SH (HS300 ETF), weekly MA20 exit plus the 2% daily
        emergency exit. Existing holdings are never liquidated merely
        because CSI1000 falls below MA15.
    """
    symbols = []

    for symbol in [
        context.market_entry_anchor,
        context.market_exit_anchor
    ]:
        if symbol not in symbols:
            symbols.append(symbol)

    required_count = max(
        65,
        int(context.market_entry_ma) + 5,
        int(context.market_exit_ma) + 5
    )

    hist = load_history_recursive(
        symbols,
        ['close'],
        required_count
    )

    entry_close = np.asarray([], dtype=float)
    exit_close = np.asarray([], dtype=float)

    if context.market_entry_anchor in hist:
        entry_close = clean_close(
            hist[context.market_entry_anchor]
        )

    if context.market_exit_anchor in hist:
        exit_close = clean_close(
            hist[context.market_exit_anchor]
        )

    return entry_close, exit_close


def is_new_trading_week(context, today):
    """
    Return True only on the first observed trading day of a new week.

    This deliberately does NOT call get_trade_days(). The prior version
    failed because SuperMind's/Python's isocalendar() object was a tuple
    in this environment while the code expected .year and .week attrs.

    Because before_trading() only runs on trading days, comparing the
    previous observed trading date with today is enough and naturally
    handles Monday holidays and long exchange holidays.
    """
    if context.prev_trade_date is None:
        return False

    try:
        previous_date = pd.Timestamp(
            context.prev_trade_date
        ).normalize()

        current_date = pd.Timestamp(
            today
        ).normalize()

        # W-FRI means each trading week is grouped into a period ending
        # Friday. Friday -> next Monday/Tuesday therefore changes period.
        previous_week = previous_date.to_period('W-FRI')
        current_week = current_date.to_period('W-FRI')

        return previous_week != current_week

    except Exception as e:
        log.warn(
            'week-boundary check failed | {}'
            .format(e)
        )
        return False


def market_state(context, today):
    entry_close, exit_close = load_market_anchor_closes(
        context
    )

    entry_ma_days = int(context.market_entry_ma)
    exit_ma_days = int(context.market_exit_ma)

    entry_valid = (
        len(entry_close) >= entry_ma_days
    )

    exit_valid = (
        len(exit_close) >= exit_ma_days
    )

    entry_close_now = np.nan
    entry_ma_value = np.nan

    if entry_valid:
        entry_close_now = float(entry_close[-1])
        entry_ma_value = float(
            np.mean(entry_close[-entry_ma_days:])
        )

    exit_close_now = np.nan
    exit_ma_value = np.nan

    if exit_valid:
        exit_close_now = float(exit_close[-1])
        exit_ma_value = float(
            np.mean(exit_close[-exit_ma_days:])
        )

    # history(..., fq='pre') in before_trading ends on the previous
    # completed trading day. context.prev_trade_date tracks that date.
    signal_date = context.prev_trade_date
    week_boundary = is_new_trading_week(
        context,
        today
    )

    # CSI1000 MA15 controls only whether vacancies may be filled.
    entry_gate_on = bool(
        entry_valid
        and entry_close_now > entry_ma_value
    )

    weekly_threshold = np.nan
    daily_threshold = np.nan

    if exit_valid:
        weekly_threshold = (
            exit_ma_value
            * (
                1.0
                - float(
                    context.weekly_exit_buffer
                )
            )
        )

        daily_threshold = (
            exit_ma_value
            * (
                1.0
                - float(
                    context.daily_exit_buffer
                )
            )
        )

    weekly_exit = bool(
        exit_valid
        and week_boundary
        and exit_close_now < weekly_threshold
    )

    daily_buffer_exit = bool(
        exit_valid
        and exit_close_now < daily_threshold
    )

    mode = str(
        context.market_exit_mode
    ).upper()

    if mode not in [
        'WEEKLY',
        'DAILY_BUFFER',
        'BOTH',
        'NONE'
    ]:
        log.warn(
            'unknown market_exit_mode={}, fallback to BOTH'
            .format(context.market_exit_mode)
        )
        mode = 'BOTH'

    if mode == 'WEEKLY':
        system_exit = weekly_exit
    elif mode == 'DAILY_BUFFER':
        system_exit = daily_buffer_exit
    elif mode == 'BOTH':
        system_exit = (
            weekly_exit
            or daily_buffer_exit
        )
    else:
        system_exit = False

    # In the deployed BOTH mode, both anchors must be available before
    # the strategy may open a new position. This prevents opening risk
    # on a day when the HS300 liquidation anchor cannot be evaluated.
    exit_data_required = (
        mode != 'NONE'
    )

    market_data_valid = bool(
        entry_valid
        and (
            exit_valid
            or not exit_data_required
        )
    )

    entry_permission = bool(
        market_data_valid
        and entry_gate_on
        and not system_exit
    )

    return {
        # Compatibility fields used by the remaining V6 code.
        'valid': market_data_valid,
        'gate_on': entry_gate_on,
        'close': exit_close_now,
        'ma20': exit_ma_value,

        # Explicit split-anchor fields.
        'entry_anchor': context.market_entry_anchor,
        'entry_valid': bool(entry_valid),
        'entry_close': entry_close_now,
        'entry_ma20': entry_ma_value,
        'entry_gate_on': entry_gate_on,
        'entry_permission': entry_permission,

        'exit_anchor': context.market_exit_anchor,
        'exit_valid': bool(exit_valid),
        'exit_close': exit_close_now,
        'exit_ma20': exit_ma_value,

        'weekly_exit': weekly_exit,
        'daily_buffer_exit': daily_buffer_exit,
        'system_exit': bool(system_exit),
        'weekly_threshold': weekly_threshold,
        'daily_threshold': daily_threshold,
        'signal_date': signal_date,
        'week_boundary': bool(week_boundary),
        'mode': mode
    }



# ============================================================
# Intraday 14:57 exit helpers
# ============================================================

def snapshot_price_1457(bar_dict, symbol):
    """
    Causally available price at the 14:57 trigger.

    The current 14:57 minute has just started when the callback runs, so
    its OPEN is used as the pseudo-close. If unavailable, use the latest
    completed one-minute close.
    """
    try:
        bar = bar_dict[symbol]
        price = float(bar.open)
        if np.isfinite(price) and price > 0:
            return price
    except Exception:
        pass

    try:
        result = history(
            [symbol],
            ['close'],
            1,
            '1m',
            False,
            'pre',
            False,
            False
        )
        out = normalize_history_result(
            result,
            [symbol],
            ['close']
        )
        if symbol in out:
            arr = clean_close(out[symbol])
            if len(arr) > 0:
                price = float(arr[-1])
                if np.isfinite(price) and price > 0:
                    return price
    except Exception as e:
        log.warn(
            '14:57 SNAPSHOT FAILED {} | {}'
            .format(symbol, e)
        )

    return np.nan


def append_snapshot(close, price):
    close = np.asarray(close, dtype=float)

    if len(close) == 0:
        return close

    if not np.isfinite(price) or price <= 0:
        return close

    return np.concatenate([
        close,
        np.asarray([float(price)], dtype=float)
    ])


def is_last_trading_day_of_week(today):
    """Identify the exchange week's final trading day, including holidays."""
    try:
        current_date = pd.Timestamp(today).normalize()
        end_date = current_date + pd.Timedelta(days=10)

        days = get_trade_days(
            current_date.strftime('%Y%m%d'),
            end_date.strftime('%Y%m%d')
        )

        future_days = []

        for day in days:
            trade_date = pd.Timestamp(day).normalize()
            if trade_date > current_date:
                future_days.append(trade_date)

        if len(future_days) == 0:
            return current_date.weekday() == 4

        next_trade_date = min(future_days)

        return (
            current_date.to_period('W-FRI')
            != next_trade_date.to_period('W-FRI')
        )

    except Exception as e:
        log.warn(
            'LAST-TRADING-DAY-OF-WEEK CHECK FAILED | {}'
            .format(e)
        )

        try:
            return pd.Timestamp(today).weekday() == 4
        except Exception:
            return False


def load_market_anchor_completed_closes(context, today):
    symbols = []

    for symbol in [
        context.market_entry_anchor,
        context.market_exit_anchor
    ]:
        if symbol not in symbols:
            symbols.append(symbol)

    required_count = max(
        65,
        int(context.market_entry_ma) + 5,
        int(context.market_exit_ma) + 5
    )

    hist = load_history_recursive(
        symbols,
        ['close'],
        required_count
    )

    out = {}

    for symbol in symbols:
        if symbol not in hist:
            out[symbol] = np.asarray([], dtype=float)
            continue

        completed = completed_daily_data(
            hist[symbol],
            today
        )
        out[symbol] = clean_close(completed)

    return out


def market_state_1457(context, today, bar_dict):
    """Evaluate split market anchors from completed closes + 14:57 price."""
    completed_map = load_market_anchor_completed_closes(
        context,
        today
    )

    entry_completed = completed_map.get(
        context.market_entry_anchor,
        np.asarray([], dtype=float)
    )
    exit_completed = completed_map.get(
        context.market_exit_anchor,
        np.asarray([], dtype=float)
    )

    entry_snapshot = snapshot_price_1457(
        bar_dict,
        context.market_entry_anchor
    )
    exit_snapshot = snapshot_price_1457(
        bar_dict,
        context.market_exit_anchor
    )

    entry_close = append_snapshot(entry_completed, entry_snapshot)
    exit_close = append_snapshot(exit_completed, exit_snapshot)

    entry_ma_days = int(context.market_entry_ma)
    exit_ma_days = int(context.market_exit_ma)

    entry_valid = bool(
        len(entry_close) > len(entry_completed)
        and len(entry_close) >= entry_ma_days
    )
    exit_valid = bool(
        len(exit_close) > len(exit_completed)
        and len(exit_close) >= exit_ma_days
    )

    entry_close_now = np.nan
    entry_ma_value = np.nan
    exit_close_now = np.nan
    exit_ma_value = np.nan

    if entry_valid:
        entry_close_now = float(entry_close[-1])
        entry_ma_value = float(np.mean(entry_close[-entry_ma_days:]))

    if exit_valid:
        exit_close_now = float(exit_close[-1])
        exit_ma_value = float(np.mean(exit_close[-exit_ma_days:]))

    entry_gate_on = bool(
        entry_valid and entry_close_now > entry_ma_value
    )

    last_week_day = is_last_trading_day_of_week(today)

    weekly_threshold = np.nan
    daily_threshold = np.nan

    if exit_valid:
        weekly_threshold = (
            exit_ma_value
            * (1.0 - float(context.tail_weekly_exit_buffer))
        )
        daily_threshold = (
            exit_ma_value
            * (1.0 - float(context.daily_exit_buffer))
        )

    weekly_exit = bool(
        exit_valid
        and last_week_day
        and exit_close_now < weekly_threshold
    )
    daily_buffer_exit = bool(
        exit_valid
        and exit_close_now < daily_threshold
    )

    mode = str(context.market_exit_mode).upper()

    if mode not in ['WEEKLY', 'DAILY_BUFFER', 'BOTH', 'NONE']:
        log.warn(
            'UNKNOWN MARKET EXIT MODE {} | fallback to BOTH'
            .format(context.market_exit_mode)
        )
        mode = 'BOTH'

    if mode == 'WEEKLY':
        system_exit = weekly_exit
    elif mode == 'DAILY_BUFFER':
        system_exit = daily_buffer_exit
    elif mode == 'BOTH':
        system_exit = weekly_exit or daily_buffer_exit
    else:
        system_exit = False

    exit_data_required = mode != 'NONE'
    market_data_valid = bool(
        entry_valid and (exit_valid or not exit_data_required)
    )

    return {
        'valid': market_data_valid,
        'entry_anchor': context.market_entry_anchor,
        'entry_valid': entry_valid,
        'entry_close': entry_close_now,
        'entry_ma20': entry_ma_value,
        'entry_gate_on': entry_gate_on,
        'exit_anchor': context.market_exit_anchor,
        'exit_valid': exit_valid,
        'exit_close': exit_close_now,
        'exit_ma20': exit_ma_value,
        'weekly_exit': weekly_exit,
        'daily_buffer_exit': daily_buffer_exit,
        'system_exit': bool(system_exit),
        'weekly_threshold': weekly_threshold,
        'daily_threshold': daily_threshold,
        'last_week_day': bool(last_week_day),
        'mode': mode
    }


def queue_close_sells(context, symbols, reason):
    """Merge sell-only instructions for same-day final-close execution."""
    today_key = get_datetime().strftime('%Y-%m-%d')

    merged = []
    seen = set()

    existing = []
    if context.pending_close_date == today_key:
        existing = list(context.pending_close_sells)

    for code in existing + list(symbols):
        key = raw_code(code)
        if key not in seen:
            seen.add(key)
            merged.append(code)

    if len(merged) == 0:
        return

    context.pending_close_sells = merged
    context.pending_close_reason = str(reason)
    context.pending_close_date = today_key

    log.info(
        'QUEUE TAIL SELLS | signal_time={} | reason={} | sells={}'
        .format(
            get_datetime().strftime('%Y-%m-%d %H:%M:%S'),
            context.pending_close_reason,
            context.pending_close_sells
        )
    )


def run_1457_exit_signal(context, bar_dict):
    """Freeze SELL signals only. New entries are never selected at 14:57."""
    today = get_datetime()
    current = current_holdings(context)

    cleanup_forced_sells(context, current)

    if context.force_exit_all and len(current) == 0:
        context.force_exit_all = False

    mkt = market_state_1457(
        context,
        today,
        bar_dict
    )

    log.info(
        'MARKET 14:57 | signal={} | ENTRY[{}] valid={} close={:.4f} MA{}={:.4f} gate_on={} | EXIT[{}] valid={} close={:.4f} MA{}={:.4f} mode={} last_week_day={} weekly_thr={:.4f} weekly_exit={} daily_emergency_thr={:.4f} daily_emergency_exit={} system_exit={}'
        .format(
            today.strftime('%Y-%m-%d'),
            mkt['entry_anchor'],
            mkt['entry_valid'],
            mkt['entry_close'],
            context.market_entry_ma,
            mkt['entry_ma20'],
            mkt['entry_gate_on'],
            mkt['exit_anchor'],
            mkt['exit_valid'],
            mkt['exit_close'],
            context.market_exit_ma,
            mkt['exit_ma20'],
            mkt['mode'],
            mkt['last_week_day'],
            mkt['weekly_threshold'],
            mkt['weekly_exit'],
            mkt['daily_threshold'],
            mkt['daily_buffer_exit'],
            mkt['system_exit']
        )
    )

    if len(current) == 0:
        if mkt['system_exit']:
            log.info('MARKET EXIT ACTIVE 14:57 | portfolio already flat')
        return

    if mkt['system_exit']:
        if mkt['weekly_exit'] and mkt['daily_buffer_exit']:
            reason = 'TAIL_MARKET_EXIT_WEEKLY_AND_DAILY_EMERGENCY_HS300'
        elif mkt['weekly_exit']:
            reason = 'TAIL_MARKET_EXIT_WEEKLY_510300_LT_MA20'
        else:
            reason = 'TAIL_MARKET_EXIT_DAILY_EMERGENCY_510300_LT_MA20'

        context.force_exit_all = True
        queue_close_sells(context, current, reason)
        return

    sells = []
    reasons = []

    # Retry any previous incomplete portfolio liquidation at today's close.
    if context.force_exit_all:
        sells.extend(current)
        reasons.append('RETRY_MARKET_EXIT_ALL_AT_CLOSE')

    forced_raw = set([raw_code(x) for x in context.forced_sells])

    for code in current:
        if raw_code(code) in forced_raw:
            sells.append(code)

    if len(forced_raw) > 0:
        reasons.append('RETRY_OWN_EXIT_AT_CLOSE')

    hist = load_history_recursive(
        current,
        ['close'],
        max(65, int(context.exit_ma) + 5)
    )

    snapshot_missing = []
    own_exit_codes = []

    for code in current:
        if code not in hist:
            if len(snapshot_missing) < 20:
                snapshot_missing.append(code)
            continue

        completed = completed_daily_data(hist[code], today)
        completed_close = clean_close(completed)
        snap = snapshot_price_1457(bar_dict, code)
        close = append_snapshot(completed_close, snap)

        if len(close) <= len(completed_close):
            if len(snapshot_missing) < 20:
                snapshot_missing.append(code)
            continue

        if own_exit_signal(context, close):
            own_exit_codes.append(code)
            sells.append(code)

            if code not in context.forced_sells:
                context.forced_sells.append(code)

            log.info(
                'OWN EXIT SIGNAL 14:57 {} | MA40_C2'
                .format(code)
            )

    if len(own_exit_codes) > 0:
        reasons.append('TAIL_OWN_EXIT_MA40_C2')

    # De-duplicate while preserving order.
    unique_sells = []
    seen = set()
    current_raw = set([raw_code(x) for x in current])

    for code in sells:
        key = raw_code(code)
        if key in current_raw and key not in seen:
            seen.add(key)
            unique_sells.append(code)

    if len(unique_sells) > 0:
        queue_close_sells(
            context,
            unique_sells,
            '|'.join(reasons) if len(reasons) > 0 else 'TAIL_EXIT'
        )

    log.info(
        'TAIL EXIT SCAN 14:57 | holdings={} | own_exit={} | queued_sells={}'
        .format(current, own_exit_codes, unique_sells)
    )

    if len(snapshot_missing) > 0:
        log.info(
            'TAIL EXIT SNAPSHOT/HISTORY MISSING | {}'
            .format(','.join(snapshot_missing))
        )


def closing_price(bar_dict, symbol):
    """Reference price for audit logs; it does not become a limit order."""
    try:
        bar = bar_dict[symbol]
        price = float(bar.close)
        if np.isfinite(price) and price > 0:
            return price
    except Exception:
        pass

    try:
        result = history(
            [symbol],
            ['close'],
            1,
            '1m',
            False,
            'pre',
            False,
            False
        )
        out = normalize_history_result(result, [symbol], ['close'])
        if symbol in out:
            arr = clean_close(out[symbol])
            if len(arr) > 0:
                price = float(arr[-1])
                if np.isfinite(price) and price > 0:
                    return price
    except Exception:
        pass

    return np.nan


def execute_pending_close_sells(context, bar_dict):
    """Submit only liquidation orders at the 15:00 current-bar close."""
    if len(context.pending_close_sells) == 0:
        return

    today_key = get_datetime().strftime('%Y-%m-%d')

    if context.pending_close_date != today_key:
        log.warn(
            'DROP STALE TAIL SELL QUEUE | queued={} | now={}'
            .format(context.pending_close_date, today_key)
        )
        context.pending_close_sells = []
        context.pending_close_reason = ''
        context.pending_close_date = None
        return

    current = current_holdings(context)
    held_by_raw = {raw_code(x): x for x in current}

    log.info(
        'EXECUTE FINAL-CLOSE SELLS | time={} | reason={} | current={} | sells={}'
        .format(
            get_datetime().strftime('%Y-%m-%d %H:%M:%S'),
            context.pending_close_reason,
            current,
            context.pending_close_sells
        )
    )

    for requested in context.pending_close_sells:
        key = raw_code(requested)

        if key not in held_by_raw:
            log.info(
                'TAIL SELL SKIPPED {} | no longer held'
                .format(requested)
            )
            continue

        code = held_by_raw[key]
        ref_close = closing_price(bar_dict, code)

        try:
            # price=None is essential: with set_execution('close'), this is
            # matched against the current 15:00 bar close plus slippage.
            order_id = order_target(code, 0)

            if order_id is None:
                log.warn(
                    'TAIL SELL REJECTED {} | reference_close={}'
                    .format(
                        code,
                        '{:.6f}'.format(ref_close)
                        if np.isfinite(ref_close)
                        else 'NA'
                    )
                )
            else:
                log.info(
                    'TAIL SELL SUBMITTED {} | order_id={} | reference_close={}'
                    .format(
                        code,
                        order_id,
                        '{:.6f}'.format(ref_close)
                        if np.isfinite(ref_close)
                        else 'NA'
                    )
                )

        except Exception as e:
            log.warn(
                'TAIL SELL FAILED {} | {}'
                .format(code, e)
            )

    context.pending_close_sells = []
    context.pending_close_reason = ''
    context.pending_close_date = None

# ============================================================
# V6 eligibility
# ============================================================

def is_eligible(context, data):
    close_raw = field_array(data, 'close')
    turnover_raw = field_array(data, 'turnover')

    if len(close_raw) < context.min_history:
        return False

    if len(turnover_raw) < 20:
        return False

    close_tail = close_raw[-context.min_history:]

    if not np.all(np.isfinite(close_tail)):
        return False

    turnover20 = turnover_raw[-20:]

    if not np.all(np.isfinite(turnover20)):
        return False

    if float(np.mean(turnover20)) < context.min_turnover20:
        return False

    return True


# ============================================================
# V6 FULL40 and entry signal
# ============================================================

def full40_signal(context, close):
    if len(close) < context.min_history:
        return False

    # Prior 40 closes, excluding the signal day.
    pre40 = close[-41:-1]

    if len(pre40) != 40:
        return False

    if not np.all(np.isfinite(pre40)):
        return False

    low40 = float(np.min(pre40))
    high40 = float(np.max(pre40))

    if low40 <= 0:
        return False

    box_width = high40 / low40 - 1.0

    if box_width > context.box_width_max:
        return False

    # Previous-day moving-average dispersion.
    pre = close[:-1]

    ma5 = float(np.mean(pre[-5:]))
    ma10 = float(np.mean(pre[-10:]))
    ma20 = float(np.mean(pre[-20:]))
    ma30 = float(np.mean(pre[-30:]))

    ma_values = [ma5, ma10, ma20, ma30]
    ma_min = min(ma_values)
    ma_max = max(ma_values)

    if ma_min <= 0:
        return False

    ma_dispersion = ma_max / ma_min - 1.0

    if ma_dispersion > context.ma_dispersion_max:
        return False

    # Direction efficiency over the prior 40 closes.
    path = float(np.sum(np.abs(np.diff(pre40))))

    if path <= 0:
        direction_efficiency = 0.0
    else:
        direction_efficiency = (
            abs(float(pre40[-1]) - float(pre40[0]))
            / path
        )

    if (
        direction_efficiency
        > context.direction_efficiency_max
    ):
        return False

    # Realized volatility ratio: last 10 returns / last 60 returns,
    # all measured strictly before the signal day.
    if len(pre) < 61:
        return False

    ret = pre[1:] / pre[:-1] - 1.0

    if len(ret) < 60:
        return False

    ret10 = ret[-10:]
    ret60 = ret[-60:]

    if (
        not np.all(np.isfinite(ret10))
        or not np.all(np.isfinite(ret60))
    ):
        return False

    vol10 = float(np.std(ret10, ddof=1))
    vol60 = float(np.std(ret60, ddof=1))

    if not np.isfinite(vol10) or not np.isfinite(vol60):
        return False

    if vol60 <= 0:
        return False

    if vol10 / vol60 > context.vol_ratio_max:
        return False

    return True


def minvol_location_signal(context, data):
    """
    Causal implementation of MINVOLLOC_L30_C0.50.

    The history loaded in before_trading() ends at the latest completed
    trading day, which is the signal day t.  The slice below uses exactly
    [-lookback-1:-1], so it covers t-30 ... t-1 and EXCLUDES t,
    preserving the frozen research definition of pre-breakout volume.

    Price location is measured inside the same trailing-close box:

        location = (close_on_min_volume_day - min(close_window))
                   / (max(close_window) - min(close_window))

    A value of 0 is the bottom of the box and 1 is the top.  The frozen
    research rule passes when location <= 0.50.

    Returns:
        passed: bool
        diagnostic: dict used only for audit logs
    """
    lookback = max(
        1,
        int(context.minvol_lookback)
    )

    threshold = min(
        1.0,
        max(
            0.0,
            float(
                context.minvol_price_location_max
            )
        )
    )

    close_raw = field_array(data, 'close')
    volume_raw = field_array(data, 'volume')

    common = min(
        len(close_raw),
        len(volume_raw)
    )

    base = {
        'valid': False,
        'passed': False,
        'location': np.nan,
        'min_volume': np.nan,
        'min_volume_ratio': np.nan,
        'reason': 'UNKNOWN'
    }

    # Need lookback observations before the signal day, plus the signal day.
    if common < lookback + 1:
        base['reason'] = 'INSUFFICIENT_HISTORY'
        return False, base

    # Align both fields by their common right edge before slicing.
    close_aligned = close_raw[-common:]
    volume_aligned = volume_raw[-common:]

    pre_close = close_aligned[-(lookback + 1):-1]
    pre_volume = volume_aligned[-(lookback + 1):-1]

    if (
        len(pre_close) != lookback
        or len(pre_volume) != lookback
    ):
        base['reason'] = 'WINDOW_LENGTH_MISMATCH'
        return False, base

    if (
        not np.all(np.isfinite(pre_close))
        or not np.all(np.isfinite(pre_volume))
    ):
        base['reason'] = 'NONFINITE_WINDOW'
        return False, base

    # Zero volume usually means a suspension/missing observation.  Treating
    # it as the economically meaningful minimum would create false passes.
    if np.any(pre_close <= 0) or np.any(pre_volume <= 0):
        base['reason'] = 'NONPOSITIVE_PRICE_OR_VOLUME'
        return False, base

    minimum_index = int(
        np.argmin(pre_volume)
    )

    minimum_volume = float(
        pre_volume[minimum_index]
    )

    minimum_volume_close = float(
        pre_close[minimum_index]
    )

    low_close = float(np.min(pre_close))
    high_close = float(np.max(pre_close))

    # A perfectly flat box has no meaningful upper/lower span.  It is
    # treated as location 0 because the minimum-volume close is also at
    # the box floor; this mirrors an epsilon-denominator implementation.
    if high_close <= low_close:
        location = 0.0
    else:
        location = (
            minimum_volume_close
            - low_close
        ) / (
            high_close
            - low_close
        )

    average_volume = float(
        np.mean(pre_volume)
    )

    if average_volume > 0:
        minimum_volume_ratio = (
            minimum_volume
            / average_volume
        )
    else:
        minimum_volume_ratio = np.nan

    passed = bool(
        location <= threshold
    )

    return passed, {
        'valid': True,
        'passed': passed,
        'location': float(location),
        'min_volume': minimum_volume,
        'min_volume_ratio': float(minimum_volume_ratio),
        'reason': (
            'PASS'
            if passed
            else 'MIN_VOLUME_AT_UPPER_HALF'
        )
    }


def entry_signal(context, close):
    if len(close) < context.min_history:
        return False

    signal_close = float(close[-1])

    previous_60_high = float(
        np.max(close[-61:-1])
    )

    if signal_close <= previous_60_high:
        return False

    ma20 = float(
        np.mean(close[-context.entry_ma:])
    )

    if signal_close <= ma20:
        return False

    if not full40_signal(context, close):
        return False

    return True


# ============================================================
# V6 own exit: MA40 x 2
# ============================================================

def own_exit_signal(context, close):
    if len(close) < context.exit_ma + 1:
        return False

    t_close = float(close[-1])
    t_ma40 = float(
        np.mean(close[-context.exit_ma:])
    )

    p_close = float(close[-2])
    p_ma40 = float(
        np.mean(
            close[
                -(context.exit_ma + 1):-1
            ]
        )
    )

    return (
        t_close < t_ma40
        and p_close < p_ma40
    )


# ============================================================
# Transparent fallback ranking:
# V5 cross-sectional 20/60/120 RS
# ============================================================

def momentum_values(close):
    if len(close) < 121:
        return None

    p = float(close[-1])

    p20 = float(close[-21])
    p60 = float(close[-61])
    p120 = float(close[-121])

    if p20 <= 0 or p60 <= 0 or p120 <= 0:
        return None

    return (
        p / p20 - 1.0,
        p / p60 - 1.0,
        p / p120 - 1.0
    )


def build_rs_table(history_map, eligible_codes):
    rows = []

    for code in eligible_codes:
        if code not in history_map:
            continue

        close = clean_close(history_map[code])

        moms = momentum_values(close)

        if moms is None:
            continue

        rows.append({
            'code': code,
            'mom20': moms[0],
            'mom60': moms[1],
            'mom120': moms[2]
        })

    if len(rows) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Percentiles are calculated across the FULL eligible cross-section,
    # not only among today's breakout candidates.
    df['r20'] = df['mom20'].rank(
        method='average',
        pct=True
    )

    df['r60'] = df['mom60'].rank(
        method='average',
        pct=True
    )

    df['r120'] = df['mom120'].rank(
        method='average',
        pct=True
    )

    df['score'] = (
        df['r20']
        + df['r60']
        + df['r120']
    ) / 3.0

    return df


# ============================================================
# Signal preparation: t-1 close
# ============================================================

def before_trading(context):
    # One-shot state for the new trading day.
    context.last_open_execution_date = None
    context.last_intraday_signal_date = None
    context.last_close_execution_date = None

    # A close queue must never leak into the next session. Sticky exit
    # flags remain, so any failed liquidation is still retried at the open.
    if len(context.pending_close_sells) > 0:
        log.warn(
            'DROP UNEXECUTED PRIOR TAIL SELL QUEUE | date={} | reason={} | sells={}'
            .format(
                context.pending_close_date,
                context.pending_close_reason,
                context.pending_close_sells
            )
        )

    context.pending_close_sells = []
    context.pending_close_reason = ''
    context.pending_close_date = None

    today = get_datetime()

    context.pending_desired = None
    context.pending_reason = ''

    current = current_holdings(context)

    cleanup_forced_sells(
        context,
        current
    )

    # If a prior market liquidation has completed, release the sticky flag.
    if context.force_exit_all and len(current) == 0:
        context.force_exit_all = False
        context.last_target_membership_raw = []

    mkt = market_state(
        context,
        today
    )

    signal_date_text = 'NA'

    if mkt['signal_date'] is not None:
        signal_date_text = (
            mkt['signal_date']
            .strftime('%Y-%m-%d')
        )

    # Save today's trading date immediately. Even if we return below,
    # the next trading day can correctly detect a week boundary.
    context.prev_trade_date = pd.Timestamp(today).normalize()

    log.info(
        'MARKET | signal={} | ENTRY[{}] valid={} close={:.4f} MA{}={:.4f} gate_on={} permission={} | EXIT[{}] valid={} close={:.4f} MA{}={:.4f} mode={} week_boundary={} weekly_thr={:.4f} weekly_exit={} daily_emergency_thr={:.4f} daily_emergency_exit={} system_exit={}'
        .format(
            signal_date_text,
            mkt['entry_anchor'],
            mkt['entry_valid'],
            mkt['entry_close'],
            context.market_entry_ma,
            mkt['entry_ma20'],
            mkt['entry_gate_on'],
            mkt['entry_permission'],
            mkt['exit_anchor'],
            mkt['exit_valid'],
            mkt['exit_close'],
            context.market_exit_ma,
            mkt['exit_ma20'],
            mkt['mode'],
            mkt['week_boundary'],
            mkt['weekly_threshold'],
            mkt['weekly_exit'],
            mkt['daily_threshold'],
            mkt['daily_buffer_exit'],
            mkt['system_exit']
        )
    )

    # Highest priority: market-level liquidation.
    if mkt['system_exit']:
        if (
            mkt['weekly_exit']
            and mkt['daily_buffer_exit']
        ):
            exit_reason = (
                'MARKET_EXIT_WEEKLY_AND_DAILY_EMERGENCY_HS300'
            )
        elif mkt['weekly_exit']:
            exit_reason = (
                'MARKET_EXIT_WEEKLY_510300_LT_BUFFERED_MA20'
            )
        else:
            exit_reason = (
                'MARKET_EXIT_DAILY_EMERGENCY_510300_LT_MA20'
            )

        # Do not submit hundreds of meaningless empty liquidation orders
        # while the account is already flat.  The signal is still logged.
        if len(current) == 0:
            # The account is confirmed flat, so the CAP50_SET target set is
            # also empty. This prevents a stale pre-liquidation set from
            # causing a meaningless future rebalance.
            context.last_target_membership_raw = []
            log.info(
                'MARKET EXIT ACTIVE | portfolio already flat | {}'
                .format(exit_reason)
            )
            return

        context.force_exit_all = True
        context.pending_desired = []
        context.pending_reason = exit_reason

        log.info(
            'PREPARE EXIT ALL | {}'
            .format(context.pending_reason)
        )
        return

    # Retry a previously failed market liquidation.
    if context.force_exit_all:
        context.pending_desired = []
        context.pending_reason = (
            'RETRY_MARKET_EXIT_ALL'
        )
        return

    active = get_active_pool(context)

    # Include currently held ETFs even if a security-list edge case
    # temporarily excludes one of them, so exit logic can still work.
    symbols_to_load = list(active)

    for code in current:
        if code not in symbols_to_load:
            symbols_to_load.append(code)

    hist = load_pool_history(
        context,
        symbols_to_load
    )

    # Own exits are sticky until the position is actually gone.
    for code in current:
        if code not in hist:
            continue

        close = clean_close(hist[code])

        if own_exit_signal(context, close):
            if code not in context.forced_sells:
                context.forced_sells.append(code)

            log.info(
                'OWN EXIT SIGNAL {} | MA40_C2'
                .format(code)
            )

    forced_raw = set([
        raw_code(x)
        for x in context.forced_sells
    ])

    surviving = [
        x for x in current
        if raw_code(x) not in forced_raw
    ]

    # If market data failed, be conservative:
    # allow exits, but block new entries.
    if not mkt['valid']:
        # New entries remain blocked. Any own exit or prior tail exit still
        # changes the member set, so resize the surviving set once.
        prepare_cap50_set_rebalance(
            context,
            current,
            surviving,
            'CAP50_SET_OWN_OR_TAIL_EXIT_MARKET_DATA_INVALID'
        )

        log.warn(
            'MARKET ANCHOR DATA INVALID | entry[{}]={} | exit[{}]={} | new entries blocked'
            .format(
                mkt['entry_anchor'],
                mkt['entry_valid'],
                mkt['exit_anchor'],
                mkt['exit_valid']
            )
        )
        return

    # CSI1000 MA15 entry gate OFF:
    # keep survivors, execute own exits, no new positions.
    # CSI1000 MA15 is NOT a liquidation trigger.
    if not mkt['entry_permission']:
        # The CSI1000 MA15 gate blocks NEW symbols only. CAP50_SET may still
        # resize existing survivors after a member exit because no new ETF
        # is being introduced.
        prepare_cap50_set_rebalance(
            context,
            current,
            surviving,
            'CAP50_SET_OWN_OR_TAIL_EXIT_CSI1000_ENTRY_GATE_OFF'
        )

        log.info(
            'SCAN | active={} | loaded={} | CSI1000_MA15_ENTRY_GATE=OFF | holdings={} | surviving={}'
            .format(
                len(active),
                len(hist),
                current,
                surviving
            )
        )
        return

    vacancies = (
        context.max_holdings
        - len(surviving)
    )

    # Frozen V6 behavior: do not rotate merely because another ETF has
    # a higher current RS score.  This is intentional here, not a bug.
    if vacancies <= 0:
        # No replacement is allowed, but a set change that already happened
        # outside the opening callback (for example a tail exit) must still
        # receive its one CAP50_SET resize.
        prepare_cap50_set_rebalance(
            context,
            current,
            surviving,
            'CAP50_SET_MEMBERSHIP_SYNC_FULL_PORTFOLIO'
        )

        log.info(
            'SCAN | active={} | loaded={} | full portfolio | rank_replacement=OFF_BY_DESIGN | holdings={}'
            .format(
                len(active),
                len(hist),
                current
            )
        )
        return

    eligible = []

    for code in active:
        if code not in hist:
            continue

        if is_eligible(
            context,
            hist[code]
        ):
            eligible.append(code)

    # Ranking must be built across all eligible ETFs.
    rs = build_rs_table(
        hist,
        eligible
    )

    score_map = {}
    mom60_map = {}

    if not rs.empty:
        for row in rs.itertuples(index=False):
            score_map[row.code] = float(row.score)
            mom60_map[row.code] = float(row.mom60)

    current_raw = set([
        raw_code(x)
        for x in current
    ])

    candidates = []

    minvol_mode = str(
        context.minvol_filter_mode
    ).upper()

    if minvol_mode not in [
        'HARD',
        'SHADOW',
        'OFF'
    ]:
        log.warn(
            'UNKNOWN MINVOL MODE {} | fallback to HARD'
            .format(context.minvol_filter_mode)
        )
        minvol_mode = 'HARD'

    price_signal_count = 0
    minvol_checked = 0
    minvol_passed = 0
    minvol_rejected = 0
    minvol_invalid = 0
    minvol_rejected_samples = []

    for code in eligible:
        # Never sell and immediately re-add the same ETF in one auction.
        if raw_code(code) in current_raw:
            continue

        if code not in hist:
            continue

        data = hist[code]
        close = clean_close(data)

        # First preserve the frozen V6 price-structure sequence.
        if not entry_signal(
            context,
            close
        ):
            continue

        price_signal_count += 1

        minvol_location = np.nan
        minvol_volume_ratio = np.nan
        minvol_pass = True
        minvol_reason = 'OFF'

        # The new rule is deliberately evaluated only after B60+FULL40
        # pass. It is an entry-quality filter, not a replacement for FULL40.
        if minvol_mode != 'OFF':
            minvol_checked += 1

            minvol_pass, minvol_diag = (
                minvol_location_signal(
                    context,
                    data
                )
            )

            minvol_location = minvol_diag[
                'location'
            ]
            minvol_volume_ratio = minvol_diag[
                'min_volume_ratio'
            ]
            minvol_reason = minvol_diag[
                'reason'
            ]

            if minvol_pass:
                minvol_passed += 1
            else:
                minvol_rejected += 1

                if not minvol_diag['valid']:
                    minvol_invalid += 1

                if len(minvol_rejected_samples) < 20:
                    if np.isfinite(minvol_location):
                        rejected_text = (
                            '{}[loc={:.3f};{}]'
                            .format(
                                code,
                                minvol_location,
                                minvol_reason
                            )
                        )
                    else:
                        rejected_text = (
                            '{}[loc=NA;{}]'
                            .format(
                                code,
                                minvol_reason
                            )
                        )

                    minvol_rejected_samples.append(
                        rejected_text
                    )

            if (
                minvol_mode == 'HARD'
                and not minvol_pass
            ):
                continue

        if code not in score_map:
            continue

        candidates.append({
            'code': code,
            'score': score_map[code],
            'mom60': mom60_map.get(
                code,
                -999.0
            ),
            'minvol_pass': bool(minvol_pass),
            'minvol_location': minvol_location,
            'minvol_volume_ratio': minvol_volume_ratio
        })

    candidates = sorted(
        candidates,
        key=lambda x: (
            -x['score'],
            -x['mom60'],
            x['code']
        )
    )

    desired = list(surviving)

    for row in candidates:
        code = row['code']

        if code not in desired:
            desired.append(code)

        if (
            len(desired)
            >= context.max_holdings
        ):
            break

    if cap50_set_change_required(
        context,
        current,
        desired
    ):
        new_entries = [
            x for x in desired
            if raw_code(x) not in current_raw
        ]

        reason_parts = []

        if len(context.forced_sells) > 0:
            reason_parts.append(
                'OWN_EXIT_MA40_C2'
            )

        if len(new_entries) > 0:
            if minvol_mode == 'HARD':
                entry_reason = (
                    'ENTRY_B60_FULL40_MINVOLLOC30_RS'
                )
            elif minvol_mode == 'SHADOW':
                entry_reason = (
                    'ENTRY_B60_FULL40_RS_MINVOLLOC30_SHADOW'
                )
            else:
                entry_reason = (
                    'ENTRY_B60_FULL40_RS'
                )

            reason_parts.append(
                entry_reason
            )

        if (
            membership_signature(desired)
            != membership_signature(
                context.last_target_membership_raw
            )
        ):
            reason_parts.append(
                'CAP50_SET_MEMBERSHIP_CHANGE'
            )

        prepare_cap50_set_rebalance(
            context,
            current,
            desired,
            '|'.join(reason_parts)
            if len(reason_parts) > 0
            else 'CAP50_SET_MEMBERSHIP_SYNC'
        )

    candidate_codes = [
        x['code']
        for x in candidates
    ]

    log.info(
        'SCAN | active={} | loaded={} | eligible={} | price_signals={} | minvol_mode={} | minvol_checked={} | minvol_pass={} | minvol_reject={} | minvol_invalid={} | candidates={} | holdings={} | desired={}'
        .format(
            len(active),
            len(hist),
            len(eligible),
            price_signal_count,
            minvol_mode,
            minvol_checked,
            minvol_passed,
            minvol_rejected,
            minvol_invalid,
            len(candidates),
            current,
            desired
        )
    )

    if len(minvol_rejected_samples) > 0:
        log.info(
            'MINVOL REJECTED | {}'
            .format(
                ','.join(minvol_rejected_samples)
            )
        )

    if len(candidate_codes) > 0:
        candidate_audit = []

        for row in candidates[:20]:
            if np.isfinite(row['minvol_location']):
                candidate_audit.append(
                    '{}[loc={:.3f}]'
                    .format(
                        row['code'],
                        row['minvol_location']
                    )
                )
            else:
                candidate_audit.append(
                    '{}[loc=NA]'
                    .format(row['code'])
                )

        log.info(
            'CANDIDATES | {}'
            .format(
                ','.join(candidate_audit)
            )
        )


# ============================================================
# Opening auction execution
# ============================================================


# ============================================================
# Next-open execution of official-close targets
# ============================================================

def opening_reference_price(bar_dict, symbol):
    """
    Audit-only opening reference; orders remain market orders.

    SuperMind rejects dynamic reflection during strategy input
    validation. Use explicit bar.open / bar.close access instead.
    """
    try:
        bar = bar_dict[symbol]
    except Exception:
        return np.nan

    try:
        price = float(bar.open)
        if np.isfinite(price) and price > 0:
            return price
    except Exception:
        pass

    try:
        price = float(bar.close)
        if np.isfinite(price) and price > 0:
            return price
    except Exception:
        pass

    return np.nan


def execute_pending_open(context, bar_dict, source):
    if context.pending_desired is None:
        return

    today_key = get_datetime().strftime('%Y-%m-%d')

    if context.last_open_execution_date == today_key:
        return

    context.last_open_execution_date = today_key

    desired = list(context.pending_desired)
    current = current_holdings(context)
    desired_raw = set([raw_code(x) for x in desired])
    desired_signature = membership_signature(desired)
    target_weight = cap50_set_target_weight(
        context,
        desired
    )
    member_count = len(desired_signature)

    log.info(
        'EXECUTE NEXT OPEN | source={} | time={} | reason={} | current={} | desired={} | CAP50_SET_N={} | per_name_target={:.2%} | total_target={:.2%}'
        .format(
            source,
            get_datetime().strftime('%Y-%m-%d %H:%M:%S'),
            context.pending_reason,
            current,
            desired,
            member_count,
            target_weight,
            target_weight * member_count
        )
    )

    order_submission_issue = False

    # Formal-close exit fallback and any failed prior tail sell are handled
    # first. In open_auction(), SuperMind uses auction matching data; if that
    # callback is unavailable in minute mode, the 09:30 open bar is used.
    for code in current:
        if raw_code(code) not in desired_raw:
            ref_open = opening_reference_price(bar_dict, code)

            try:
                order_id = order_target(code, 0)

                if order_id is None:
                    order_submission_issue = True
                    log.warn(
                        'OPEN SELL REJECTED {} | reference_open={}'
                        .format(
                            code,
                            '{:.6f}'.format(ref_open)
                            if np.isfinite(ref_open)
                            else 'NA'
                        )
                    )
                else:
                    log.info(
                        'OPEN SELL SUBMITTED {} | order_id={} | reference_open={}'
                        .format(
                            code,
                            order_id,
                            '{:.6f}'.format(ref_open)
                            if np.isfinite(ref_open)
                            else 'NA'
                        )
                    )

            except Exception as e:
                order_submission_issue = True
                log.warn(
                    'OPEN SELL FAILED {} | {}'
                    .format(code, e)
                )

    # CAP50_SET execution:
    # - every desired member is reset to min(50%, 1/N), but only because a
    #   membership change/retry queued this callback;
    # - between set changes there is no daily target restoration;
    # - desired is ordered survivors first, then new entries, so reductions
    #   such as 2x50% -> 3x33.33% normally release cash before the new buy.
    for code in desired:
        ref_open = opening_reference_price(bar_dict, code)

        try:
            order_id = order_target_percent(
                code,
                target_weight
            )

            if order_id is None:
                order_submission_issue = True
                log.warn(
                    'OPEN CAP50_SET TARGET REJECTED {} = {:.2%} | N={} | reference_open={}'
                    .format(
                        code,
                        target_weight,
                        member_count,
                        '{:.6f}'.format(ref_open)
                        if np.isfinite(ref_open)
                        else 'NA'
                    )
                )
            else:
                log.info(
                    'OPEN CAP50_SET TARGET SUBMITTED {} = {:.2%} | N={} | order_id={} | reference_open={}'
                    .format(
                        code,
                        target_weight,
                        member_count,
                        order_id,
                        '{:.6f}'.format(ref_open)
                        if np.isfinite(ref_open)
                        else 'NA'
                    )
                )

        except Exception as e:
            order_submission_issue = True
            log.warn(
                'OPEN CAP50_SET TARGET FAILED {} | {}'
                .format(code, e)
            )

    # Mark this member set as processed even when an order API returns None.
    # SuperMind may use None both for a rejected order and for a no-op target
    # that is already satisfied. Actual buy/sell membership failures are still
    # detected next morning because current_set != desired_set; ordinary weight
    # drift is deliberately not retried, preserving SET_CHANGE_ONLY behavior.
    context.last_target_membership_raw = list(
        desired_signature
    )

    if order_submission_issue:
        log.warn(
            'CAP50_SET TARGET STATE PROCESSED WITH ORDER WARNINGS | set={} | N={} | per_name_target={:.2%}'
            .format(
                context.last_target_membership_raw,
                member_count,
                target_weight
            )
        )
    else:
        log.info(
            'CAP50_SET TARGET STATE COMMITTED | set={} | N={} | per_name_target={:.2%}'
            .format(
                context.last_target_membership_raw,
                member_count,
                target_weight
            )
        )

    # The current callback is one-shot. Sticky exits or an actual membership
    # mismatch cause a fresh target to be prepared next morning.
    context.pending_desired = None
    context.pending_reason = ''


def open_auction(context, bar_dict):
    # Exact opening-auction path when exposed by the selected engine mode.
    execute_pending_open(
        context,
        bar_dict,
        'OPEN_AUCTION_09:26'
    )


def _minute_dispatch(context, bar_dict):
    now = get_datetime()
    today_key = now.strftime('%Y-%m-%d')

    if not context.minute_callback_seen:
        context.minute_callback_seen = True
        log.info(
            'MINUTE CALLBACK ACTIVE | first_seen={}'
            .format(now.strftime('%Y-%m-%d %H:%M:%S'))
        )

    # Minute-mode fallback for opening-auction execution. enable_open_bar()
    # adds this special 09:30 callback. The guard prevents duplication if
    # open_auction() already executed the same target.
    if (
        now.hour == context.open_hour
        and now.minute == context.open_minute
        and context.pending_desired is not None
        and context.last_open_execution_date != today_key
    ):
        execute_pending_open(
            context,
            bar_dict,
            'OPEN_BAR_09:30_FALLBACK'
        )

    # Freeze exits once at the first callback from 14:57 through 14:59.
    signal_window = (
        now.hour == context.signal_hour
        and now.minute >= context.signal_minute
        and now.minute <= 59
    )

    if (
        signal_window
        and context.last_intraday_signal_date != today_key
    ):
        context.last_intraday_signal_date = today_key

        log.info(
            '14:57 EXIT SIGNAL START | actual_callback={}'
            .format(now.strftime('%Y-%m-%d %H:%M:%S'))
        )

        run_1457_exit_signal(context, bar_dict)

    # Consume the sell-only queue at the first callback at/after 15:00.
    close_window = (
        now.hour == context.close_hour
        and now.minute >= context.close_minute
        and now.minute <= 5
    )

    if (
        close_window
        and len(context.pending_close_sells) > 0
        and context.last_close_execution_date != today_key
    ):
        context.last_close_execution_date = today_key
        execute_pending_close_sells(context, bar_dict)


# SuperMind minute backtests may expose handle_data or handle_bar.
def handle_data(context, data):
    _minute_dispatch(context, data)


def handle_bar(context, bar_dict):
    _minute_dispatch(context, bar_dict)


def after_trading(context):
    account = context.portfolio.stock_account
    holdings = current_holdings(context)

    if context.pending_desired is not None:
        log.warn(
            'OPEN EXECUTION CALLBACK NOT SEEN | reason={} | desired={}'
            .format(context.pending_reason, context.pending_desired)
        )

    if len(context.pending_close_sells) > 0:
        log.warn(
            'FINAL-CLOSE EXECUTION CALLBACK NOT SEEN | date={} | reason={} | sells={}'
            .format(
                context.pending_close_date,
                context.pending_close_reason,
                context.pending_close_sells
            )
        )

    eod_target_weight = cap50_set_target_weight(
        context,
        holdings
    )

    log.info(
        'EOD {} | NAV={:.2f} | cash={:.2f} | holdings={} | actual_set={} | last_target_set={} | CAP50_SET_N={} | nominal_per_name_target={:.2%}'
        .format(
            get_datetime().strftime('%Y-%m-%d'),
            float(account.total_value),
            float(account.available_cash),
            holdings,
            membership_signature(holdings),
            membership_signature(
                context.last_target_membership_raw
            ),
            len(membership_signature(holdings)),
            eod_target_weight
        )
    )