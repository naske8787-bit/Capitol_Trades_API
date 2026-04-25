import time
import json
import os
import sys
from collections import deque

from broker import Broker
from config import (
    AUTO_RETRAIN_ENABLED,
    AUTO_RETRAIN_INTERVAL_HOURS,
    EVENT_INFLUENCE_REPORT_ENABLED,
    EVENT_INFLUENCE_REPORT_INTERVAL_MINUTES,
    EVENT_INFLUENCE_REPORT_SYMBOLS,
    EVENT_INFLUENCE_REPORT_TOPICS,
    IBKR_WATCHLIST,
    WATCHLIST,
)
from performance_tracker import PerformanceTracker
from strategy import TradingStrategy
from train import retrain_models
from autonomy import AutonomousDecisionEngine
from config import AUTONOMOUS_EXECUTION_ENABLED
from data_fetcher import fetch_external_research_sentiment

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, "shared"))
from scorecard_runtime import build_or_load_setup_scorecard, select_active_candidates, candidate_symbol_set


def _rank_multipliers(rows):
    qualified_rows = []
    for row in rows or []:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        expectancy = float(row.get("expectancy", 0.0) or 0.0)
        sample_size = int(row.get("sample_size", 0) or 0)
        if expectancy < 0.005 or sample_size < 100:
            continue
        qualified_rows.append((symbol, row))

    if not qualified_rows:
        return {}

    # Only allow concentrated sizing when there are at least two independent
    # qualified setups. With one setup, cap to baseline sizing.
    single_setup_cap = len(qualified_rows) < 2
    multipliers = {}
    for idx, (symbol, _row) in enumerate(qualified_rows):
        if idx == 0:
            mult = 1.60
        elif idx == 1:
            mult = 1.30
        elif idx == 2:
            mult = 1.10
        elif idx <= 4:
            mult = 0.90
        else:
            mult = 0.75
        if single_setup_cap:
            mult = min(mult, 1.0)
        multipliers[symbol] = mult
    return multipliers


def wait_for_account_ready(max_retries=10):
    """Wait for Alpaca account to fully initialize (handles ACCOUNT_CLOSED_PENDING status)."""
    for attempt in range(max_retries):
        try:
            broker = Broker()
            balance = broker.get_account_balance()
            portfolio = broker.get_portfolio_value()
            details = broker._alpaca.get_account_details()
            cash = details.get("cash", 0.0)
            print(f"✓ Account ready: buying_power=${balance:.2f}, cash=${cash:.2f}, portfolio=${portfolio:.2f}")
            if balance <= 0:
                print(
                    "⚠️  WARNING: Alpaca buying_power is $0. No new orders will be accepted by Alpaca.\n"
                    "   Cause: paper account balance is negative (cash=$"
                    f"{cash:.2f}).\n"
                    "   Fix:  Go to app.alpaca.markets → Paper Trading → Reset Account\n"
                    "         This takes ~30 seconds and gives you a fresh $100,000 paper balance."
                )
            return broker
        except Exception as e:
            if "ACCOUNT_CLOSED_PENDING" in str(e) or "Pydantic" in str(e.__class__.__name__):
                wait_time = 10 + (attempt * 5)
                print(f"Account still initializing (attempt {attempt + 1}/{max_retries}). Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    
    raise RuntimeError("Account failed to initialize after maximum retries. Check Alpaca account status.")


def _print_influence_report(strategy, symbols):
    state_path = os.path.join(os.path.dirname(__file__), "models", "event_impact_state.json")
    if not os.path.exists(state_path):
        print("Influence report skipped: learner state file not found yet.")
        return

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print(f"Influence report skipped: could not parse learner state ({e}).")
        return

    global_impacts = payload.get("global_topic_impacts", {}) or {}
    symbol_impacts = payload.get("symbol_topic_impacts", {}) or {}

    ranked_global = sorted(global_impacts.items(), key=lambda kv: abs(float(kv[1])), reverse=True)
    ranked_global = ranked_global[: max(1, EVENT_INFLUENCE_REPORT_TOPICS)]

    print("\n=== Learned Influence Report ===")
    if not ranked_global:
        print("Global: no learned topic impacts yet.")
    else:
        global_text = ", ".join(f"{topic}={float(val):+.4f}" for topic, val in ranked_global)
        print(f"Global top impacts: {global_text}")

    shown = 0
    for symbol in symbols:
        impacts = symbol_impacts.get(symbol.upper(), {}) or {}
        if not impacts:
            continue
        ranked = sorted(impacts.items(), key=lambda kv: abs(float(kv[1])), reverse=True)[:3]
        if not ranked:
            continue
        text = ", ".join(f"{topic}={float(val):+.4f}" for topic, val in ranked)
        print(f"{symbol} top factors: {text}")
        shown += 1
        if shown >= max(1, EVENT_INFLUENCE_REPORT_SYMBOLS):
            break

    if shown == 0:
        print("Per-symbol: no symbol-specific impacts populated yet.")
    print("=== End Influence Report ===\n")


def main():
    broker = wait_for_account_ready()
    strategy = TradingStrategy()
    tracker = PerformanceTracker()
    autonomy = AutonomousDecisionEngine(
        trade_log_path=tracker.trade_log_path,
        equity_log_path=tracker.equity_log_path,
    )

    symbols = WATCHLIST + IBKR_WATCHLIST
    if IBKR_WATCHLIST:
        print(f"IBKR international symbols: {IBKR_WATCHLIST}")
    # Avoid immediate full retrain on each restart; wait for configured interval.
    last_retrain_ts = time.time()
    last_influence_report_ts = 0.0
    last_setup_scorecard_ts = 0.0
    setup_expectancy_window = deque(maxlen=30)

    print("Trading bot started. Press Ctrl+C to stop.")
    startup_snapshot = tracker.record_equity_snapshot(broker, note="startup")
    print(
        "Starting portfolio snapshot: "
        f"value=${float(startup_snapshot['portfolio_value']):.2f}, "
        f"cash=${float(startup_snapshot['cash_balance']):.2f}, "
        f"positions={startup_snapshot['open_positions']}"
    )

    while True:
        now = time.time()

        if now - last_setup_scorecard_ts >= 1800:
            try:
                setup_payload = build_or_load_setup_scorecard(force=True, max_age_seconds=1800)
                active_stock_rows = select_active_candidates(setup_payload, asset_class="stock", limit=6, min_score=0.0)
                active_stock_symbols = candidate_symbol_set(active_stock_rows)
                qualifying_rows = [
                    row for row in active_stock_rows
                    if bool(row.get("passed", False))
                    and float(row.get("expectancy", 0.0) or 0.0) >= 0.005
                    and int(row.get("sample_size", 0) or 0) >= 100
                ]
                strategy.apply_setup_candidates(active_stock_symbols)
                strategy.apply_setup_rank_multipliers(_rank_multipliers(active_stock_rows))
                if len(qualifying_rows) == 1:
                    print("Concentration cap active: only one qualified setup, using baseline position sizing.")
                if active_stock_rows:
                    ranked = ", ".join(
                        f"{row['symbol']}({row['setup']} exp={float(row.get('expectancy', 0.0))*100:.2f}% n={int(row.get('sample_size', 0))})"
                        for row in active_stock_rows[:4]
                    )
                    print(f"Active validated stock candidates: {ranked}")
                else:
                    strategy.apply_setup_candidates(set())
                    print("Active validated stock candidates: none")
            except Exception as e:
                print(f"Setup scorecard refresh failed: {e}")
            last_setup_scorecard_ts = now

        if AUTONOMOUS_EXECUTION_ENABLED:
            research = fetch_external_research_sentiment()
            auto_profile = autonomy.evaluate(research_payload=research)
            strategy.apply_autonomy_profile(auto_profile)
            metrics = auto_profile.get("metrics", {})
            print(
                "Autonomy profile: "
                f"mode={auto_profile.get('mode')} "
                f"score={auto_profile.get('score')} "
                f"allow_entries={auto_profile.get('allow_new_entries')} "
                f"risk_mult={auto_profile.get('risk_multiplier')} "
                f"buy_threshold_mult={auto_profile.get('buy_threshold_multiplier')} "
                f"blocked={','.join(auto_profile.get('blocked_symbols', [])) or 'none'} | "
                f"closed_7d={metrics.get('closed_trades_7d', 0)} "
                f"win_7d={float(metrics.get('win_rate_7d', 0.0)):.1%} "
                f"pf_7d={float(metrics.get('profit_factor_7d', 0.0)):.2f} "
                f"pnl_7d={float(metrics.get('realized_pnl_7d', 0.0)):.2f} "
                f"dd_7d={float(metrics.get('max_drawdown_7d', 0.0)):.2%} "
                f"research_score={float(metrics.get('research_score', 0.0)):.2f}"
            )

            # Live drift kill-switch: stop new entries if realized quality degrades.
            closed_7d = int(metrics.get("closed_trades_7d", 0) or 0)
            pf_7d = float(metrics.get("profit_factor_7d", 0.0) or 0.0)
            dd_7d = float(metrics.get("max_drawdown_7d", 0.0) or 0.0)
            if (closed_7d >= 8 and pf_7d < 0.95) or dd_7d > 0.08:
                strategy.apply_autonomy_profile({
                    "allow_new_entries": False,
                    "risk_multiplier": 0.0,
                    "mode": "capital_preservation",
                })
                print(
                    "Risk kill-switch active: pausing new entries "
                    f"(closed_7d={closed_7d}, pf_7d={pf_7d:.2f}, dd_7d={dd_7d:.2%})."
                )
            for reason in auto_profile.get("reasons", [])[:4]:
                print(f"  - {reason}")
            for update in strategy.auto_apply_improvements():
                print(f"Auto-improvement: {update}")

        # Auto-retrain on schedule
        if AUTO_RETRAIN_ENABLED:
            retrain_interval_secs = AUTO_RETRAIN_INTERVAL_HOURS * 3600
            if now - last_retrain_ts >= retrain_interval_secs:
                print(f"Auto-retraining models (every {AUTO_RETRAIN_INTERVAL_HOURS}h)...")
                retrain_models(symbols=symbols)
                # Flush cached models so strategy picks up the fresh weights
                strategy.model_cache.clear()
                last_retrain_ts = time.time()
                print("Auto-retrain complete. Resuming trading loop.")

        for symbol in symbols:
            try:
                signal = strategy.analyze_signal(symbol, broker=broker)
                analysis = strategy.last_analysis.get(symbol, {})
                if bool(analysis.get("setup_passed", False)):
                    setup_expectancy_window.append(float(analysis.get("setup_expectancy_pct", 0.0) or 0.0) / 100.0)
                market_flag = "OK" if analysis.get("market_favorable", True) else "WEAK"
                print(
                    f"{symbol}: {signal} | "
                    f"predicted_change={analysis.get('predicted_change_pct', 0.0):.2f}% | "
                    f"learned_adj={analysis.get('learned_edge_adjustment_pct', 0.0):.2f}% | "
                    f"adaptive_adj={analysis.get('adaptive_policy_adjustment_pct', 0.0):.2f}% | "
                    f"pattern_adj={analysis.get('pattern_edge_adjustment_pct', 0.0):.3f}% "
                    f"({','.join(analysis.get('pattern_hits', [])[:2]) or 'none'}) | "
                    f"setup={analysis.get('validated_setup', 'none')} "
                    f"pass={analysis.get('setup_passed', False)} "
                    f"exp={analysis.get('setup_expectancy_pct', 0.0):.2f}% "
                    f"n={analysis.get('setup_sample_size', 0)} | "
                    f"effective_edge={analysis.get('effective_predicted_change_pct', 0.0):.2f}% | "
                    f"sentiment={analysis.get('sentiment', 0)} | "
                    f"news={analysis.get('news_score', 0):.2f} "
                    f"(sym={analysis.get('symbol_news_score', 0):.2f}, glob={analysis.get('global_news_score', 0):.2f}) | "
                    f"ext={analysis.get('external_research_score', 0):.2f} | "
                    f"vix={analysis.get('vix', 0.0):.1f}({analysis.get('fear_level', '?')}) | "
                    f"sector={analysis.get('sector_etf','?')}({'↑' if analysis.get('sector_tailwind') else '↓'}) | "
                    f"trend={analysis.get('trend_strength_pct', 0.0):.2f}% | "
                    f"market={market_flag} | "
                    f"autonomy={strategy.autonomy_profile.get('mode','normal')}"
                )

                trade_result = strategy.execute_trade(signal, symbol, broker)
                if trade_result:
                    cash_balance = broker.get_account_balance()
                    tracker.record_trade(
                        action=trade_result["action"],
                        symbol=trade_result["symbol"],
                        qty=trade_result["qty"],
                        price=trade_result["price"],
                        cash_balance=cash_balance,
                        analysis=analysis,
                        note="bot_execution",
                    )

                time.sleep(1)
            except Exception as e:
                print(f"Error processing {symbol}: {e}")

        # Setup-decay de-risk: if rolling setup expectancy is negative, remove
        # concentration and tighten entry/risk settings until quality recovers.
        if len(setup_expectancy_window) >= 10:
            rolling_expectancy = sum(setup_expectancy_window) / float(len(setup_expectancy_window))
            if rolling_expectancy < 0.0:
                strategy.apply_setup_rank_multipliers({})
                strategy.apply_autonomy_profile({
                    "mode": "cautious",
                    "risk_multiplier": 0.7,
                    "buy_threshold_multiplier": 1.2,
                })
                print(
                    "Setup-decay de-risk active: rolling validated setup expectancy "
                    f"{rolling_expectancy * 100:.2f}% over {len(setup_expectancy_window)} observations."
                )

        cycle_snapshot = tracker.record_equity_snapshot(broker, note="hourly_cycle")
        print(
            "Portfolio snapshot: "
            f"value=${float(cycle_snapshot['portfolio_value']):.2f}, "
            f"cash=${float(cycle_snapshot['cash_balance']):.2f}, "
            f"positions={cycle_snapshot['open_positions']}"
        )

        if EVENT_INFLUENCE_REPORT_ENABLED:
            report_interval_secs = max(1, EVENT_INFLUENCE_REPORT_INTERVAL_MINUTES) * 60
            if now - last_influence_report_ts >= report_interval_secs:
                _print_influence_report(strategy, symbols)
                last_influence_report_ts = time.time()

        print("Waiting 1 hour before next check...")
        time.sleep(3600)


if __name__ == "__main__":
    main()