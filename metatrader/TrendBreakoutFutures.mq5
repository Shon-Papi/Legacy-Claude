//+------------------------------------------------------------------+
//|                                      TrendBreakoutFutures.mq5    |
//|  Trend-filtered Donchian breakout EA — port of futures/strategy.py|
//+------------------------------------------------------------------+
//
//  Same rules as the Python bot and the TradingView script in this repo:
//
//    ENTRY (long; short is the mirror)
//      - EMA(50) > EMA(200) and close > EMA(200)       [trend filter]
//      - close breaks the prior 20-bar Donchian high   [breakout]
//      - RSI(14) < 75                                  [don't chase blow-offs]
//    EXIT
//      - initial stop: entry - 2.0 * ATR(14)
//      - breakeven:    stop to entry after +1R
//      - trailing:     chandelier, extreme-since-entry - 2.5 * ATR
//      - time stop:    close after 96 bars
//      - flip:         opposite signal reverses the position
//    RISK
//      - lots sized so the initial stop loses RiskPct of equity
//      - per-position notional leverage cap
//      - daily loss halt + drawdown kill switch (entries only),
//        persisted in terminal global variables across restarts
//
//  USE
//    1. Compile in MetaEditor (F7). Fix nothing silently: if your broker
//       build flags anything, read it.
//    2. Attach to a 15-minute chart of each futures/CFD symbol you want
//       traded (one chart per symbol). Enable "Algo Trading".
//    3. ALWAYS run the built-in Strategy Tester (Ctrl+R, "Every tick
//       based on real ticks") and then a demo account for weeks before
//       any real money. Past results never guarantee future profits.
//
//  Works on any symbol whose contract specs the broker publishes
//  (exchange futures, crypto CFDs/perps, index CFDs) because sizing is
//  derived from tick value / tick size / contract size.
//
#property copyright "Legacy-Claude"
#property version   "1.00"

#include <Trade/Trade.mqh>

//--- inputs: strategy (identical defaults to the Python bot)
input int      InpEmaFast        = 50;     // Fast EMA period
input int      InpEmaSlow        = 200;    // Slow EMA period
input int      InpDonchian       = 20;     // Donchian breakout period
input int      InpRsiPeriod      = 14;     // RSI period
input double   InpRsiLongMax     = 75.0;   // Skip longs above this RSI
input double   InpRsiShortMin    = 25.0;   // Skip shorts below this RSI
input int      InpAtrPeriod      = 14;     // ATR period
input double   InpStopAtrMult    = 2.0;    // Initial stop (ATR multiple)
input double   InpTrailAtrMult   = 2.5;    // Chandelier trail (ATR multiple)
input double   InpBreakevenR     = 1.0;    // Move stop to entry at +R
input int      InpMaxHoldBars    = 96;     // Time stop (bars)
input bool     InpAllowLong      = true;   // Allow long trades
input bool     InpAllowShort     = true;   // Allow short trades

//--- inputs: risk
input double   InpRiskPct        = 0.75;   // Risk per trade (% of equity)
input double   InpMaxLeverage    = 2.0;    // Max position notional / equity
input double   InpDailyLossPct   = 3.0;    // Daily loss halt (% of day-start equity)
input double   InpKillSwitchPct  = 15.0;   // Drawdown kill switch (% from peak equity)

//--- inputs: plumbing
input long     InpMagic          = 770915; // Magic number (this EA's trades only)
input int      InpSlippagePoints = 50;     // Max deviation (points)

CTrade   trade;
int      hEmaFast = INVALID_HANDLE;
int      hEmaSlow = INVALID_HANDLE;
int      hRsi     = INVALID_HANDLE;
int      hAtr     = INVALID_HANDLE;
datetime lastBarTime = 0;

// Account-level risk state persisted across restarts/charts
#define GV_PEAK    "TBF_peak_equity"
#define GV_DAY     "TBF_day_stamp"
#define GV_DAYEQ   "TBF_day_start_equity"
#define GV_KILLED  "TBF_kill_switch"

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   hEmaFast = iMA(_Symbol, _Period, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEmaSlow = iMA(_Symbol, _Period, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hRsi     = iRSI(_Symbol, _Period, InpRsiPeriod, PRICE_CLOSE);
   hAtr     = iATR(_Symbol, _Period, InpAtrPeriod);
   if(hEmaFast == INVALID_HANDLE || hEmaSlow == INVALID_HANDLE ||
      hRsi == INVALID_HANDLE || hAtr == INVALID_HANDLE)
     {
      Print("Failed to create indicator handles");
      return(INIT_FAILED);
     }
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(hEmaFast != INVALID_HANDLE) IndicatorRelease(hEmaFast);
   if(hEmaSlow != INVALID_HANDLE) IndicatorRelease(hEmaSlow);
   if(hRsi     != INVALID_HANDLE) IndicatorRelease(hRsi);
   if(hAtr     != INVALID_HANDLE) IndicatorRelease(hAtr);
  }

//+------------------------------------------------------------------+
//| Single indicator value at a bar shift (1 = last closed bar)      |
//+------------------------------------------------------------------+
double BufAt(const int handle, const int shift)
  {
   double v[1];
   if(CopyBuffer(handle, 0, shift, 1, v) != 1)
      return(EMPTY_VALUE);
   return(v[0]);
  }

//+------------------------------------------------------------------+
//| This EA's position on this symbol. Returns ticket or 0.          |
//| Works on netting and hedging accounts.                           |
//+------------------------------------------------------------------+
ulong MyPositionTicket()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return(ticket);
     }
   return(0);
  }

//+------------------------------------------------------------------+
//| Track the all-time equity peak (called every closed bar)         |
//+------------------------------------------------------------------+
double UpdatePeakEquity()
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak = GlobalVariableCheck(GV_PEAK) ? GlobalVariableGet(GV_PEAK) : equity;
   if(equity > peak || !GlobalVariableCheck(GV_PEAK))
     {
      peak = MathMax(peak, equity);
      GlobalVariableSet(GV_PEAK, peak);
     }
   return(peak);
  }

//+------------------------------------------------------------------+
//| Account-level circuit breakers. Entries only — exits always run. |
//+------------------------------------------------------------------+
bool EntriesAllowed()
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak   = UpdatePeakEquity();

   if(GlobalVariableCheck(GV_KILLED) && GlobalVariableGet(GV_KILLED) > 0.5)
      return(false);
   if(peak > 0 && (peak - equity) / peak >= InpKillSwitchPct / 100.0)
     {
      GlobalVariableSet(GV_KILLED, 1.0);
      Print("RISK: kill switch — equity ", equity, " is ",
            DoubleToString(100.0 * (peak - equity) / peak, 1),
            "% below peak ", peak, ". No new entries until you delete the ",
            GV_KILLED, " global variable.");
      return(false);
     }

   // Daily loss halt, keyed to the server-time day (persisted)
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   double stamp = dt.year * 10000 + dt.mon * 100 + dt.day;
   if(!GlobalVariableCheck(GV_DAY) || GlobalVariableGet(GV_DAY) != stamp)
     {
      GlobalVariableSet(GV_DAY, stamp);
      GlobalVariableSet(GV_DAYEQ, equity);
     }
   double dayStart = GlobalVariableGet(GV_DAYEQ);
   if(dayStart > 0 && equity - dayStart <= -InpDailyLossPct / 100.0 * dayStart)
     {
      Print("RISK: daily loss halt — equity ", equity, " vs day start ", dayStart);
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Lots so the initial ATR stop loses RiskPct of equity, capped by  |
//| leverage and normalized to the symbol's volume constraints.      |
//+------------------------------------------------------------------+
double CalcLots(const double price, const double stopDist)
  {
   if(price <= 0 || stopDist <= 0) return(0.0);
   double equity    = AccountInfoDouble(ACCOUNT_EQUITY);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double contract  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   if(tickValue <= 0 || tickSize <= 0 || contract <= 0) return(0.0);

   // account money lost per lot for a 1.0 price move against us
   double moneyPerUnit = tickValue / tickSize;
   double lots = (equity * InpRiskPct / 100.0) / (stopDist * moneyPerUnit);

   // leverage cap on notional
   double notionalPerLot = contract * price;
   double maxLots = equity * InpMaxLeverage / notionalPerLot;
   lots = MathMin(lots, maxLots);

   double volMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double volMax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double volStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(volStep > 0)
      lots = MathFloor(lots / volStep) * volStep;
   lots = MathMin(lots, volMax);
   if(lots < volMin)
      return(0.0);   // risk budget too small for this contract — skip, never oversize
   return(NormalizeDouble(lots, 8));
  }

//+------------------------------------------------------------------+
//| Clamp a protective stop to the broker's minimum stop distance.   |
//| Returns 0 if the stop cannot legally be placed (caller skips).   |
//+------------------------------------------------------------------+
double LegalStop(const bool isLong, double sl)
  {
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(isLong  && sl > bid - minDist) sl = bid - minDist;
   if(!isLong && sl < ask + minDist) sl = ask + minDist;
   return(NormalizeDouble(sl, _Digits));
  }

//+------------------------------------------------------------------+
//| Manage the open position on each closed bar (stateless: trailing |
//| data is rebuilt from chart history, so restarts are safe).       |
//+------------------------------------------------------------------+
void ManagePosition(const ulong ticket, const double atrNow, const double closePrev)
  {
   if(!PositionSelectByTicket(ticket)) return;

   bool   isLong    = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
   double entry     = PositionGetDouble(POSITION_PRICE_OPEN);
   double curSL     = PositionGetDouble(POSITION_SL);
   datetime opened  = (datetime)PositionGetInteger(POSITION_TIME);

   int barsHeld = iBarShift(_Symbol, _Period, opened, false);
   if(barsHeld < 0) barsHeld = 0;

   // Time stop
   if(barsHeld >= InpMaxHoldBars)
     {
      trade.PositionClose(ticket);
      Print("EXIT time stop after ", barsHeld, " bars");
      return;
     }

   // Initial risk: ATR at the entry bar * stop multiple (deterministic)
   double atrEntry = BufAt(hAtr, MathMin(barsHeld, iBars(_Symbol, _Period) - 1));
   if(atrEntry == EMPTY_VALUE || atrEntry <= 0) atrEntry = atrNow;
   double initRisk = InpStopAtrMult * atrEntry;
   if(initRisk <= 0) return;

   // Favourable extreme since entry over closed bars
   int lookback = MathMax(barsHeld, 1);
   double extreme;
   if(isLong)
     {
      int hh = iHighest(_Symbol, _Period, MODE_HIGH, lookback, 1);
      extreme = (hh >= 0) ? iHigh(_Symbol, _Period, hh) : entry;
      extreme = MathMax(extreme, entry);
     }
   else
     {
      int ll = iLowest(_Symbol, _Period, MODE_LOW, lookback, 1);
      extreme = (ll >= 0) ? iLow(_Symbol, _Period, ll) : entry;
      extreme = MathMin(extreme, entry);
     }

   // Chandelier trail + breakeven; stops only ever tighten
   double dir   = isLong ? 1.0 : -1.0;
   double newSL = extreme - dir * InpTrailAtrMult * atrNow;
   if((closePrev - entry) * dir / initRisk >= InpBreakevenR)
      newSL = isLong ? MathMax(newSL, entry) : MathMin(newSL, entry);
   if(curSL > 0)
      newSL = isLong ? MathMax(newSL, curSL) : MathMin(newSL, curSL);

   bool improves = (curSL <= 0) || (isLong ? newSL > curSL + _Point : newSL < curSL - _Point);
   if(improves)
     {
      double legal = LegalStop(isLong, newSL);
      bool stillImproves = (curSL <= 0) || (isLong ? legal > curSL : legal < curSL);
      if(legal > 0 && stillImproves && !trade.PositionModify(ticket, legal, 0.0))
         Print("PositionModify failed: ", trade.ResultRetcodeDescription());
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // Act once per closed bar — identical cadence to the backtester
   datetime curBar = iTime(_Symbol, _Period, 0);
   if(curBar == lastBarTime) return;
   lastBarTime = curBar;

   if(iBars(_Symbol, _Period) < InpEmaSlow + InpDonchian + 10) return;

   UpdatePeakEquity();   // keep the kill-switch reference honest every bar

   // --- indicator values at the last CLOSED bar (shift 1)
   double emaFast = BufAt(hEmaFast, 1);
   double emaSlow = BufAt(hEmaSlow, 1);
   double rsi     = BufAt(hRsi, 1);
   double atr     = BufAt(hAtr, 1);
   double closeP  = iClose(_Symbol, _Period, 1);
   if(emaFast == EMPTY_VALUE || emaSlow == EMPTY_VALUE ||
      rsi == EMPTY_VALUE || atr == EMPTY_VALUE || atr <= 0) return;

   // Donchian channel of the prior N bars (shift 2..N+1 — excludes signal bar)
   int hhIdx = iHighest(_Symbol, _Period, MODE_HIGH, InpDonchian, 2);
   int llIdx = iLowest(_Symbol, _Period, MODE_LOW,  InpDonchian, 2);
   if(hhIdx < 0 || llIdx < 0) return;
   double donHigh = iHigh(_Symbol, _Period, hhIdx);
   double donLow  = iLow(_Symbol, _Period, llIdx);

   bool uptrend   = emaFast > emaSlow && closeP > emaSlow;
   bool downtrend = emaFast < emaSlow && closeP < emaSlow;
   bool longSig   = InpAllowLong  && uptrend   && closeP > donHigh && rsi < InpRsiLongMax;
   bool shortSig  = InpAllowShort && downtrend && closeP < donLow  && rsi > InpRsiShortMin;

   // --- manage the open position first (exits always run)
   ulong ticket = MyPositionTicket();
   if(ticket != 0)
     {
      ManagePosition(ticket, atr, closeP);
      ticket = MyPositionTicket();   // may have been closed by the time stop
     }

   // --- flip: opposite signal closes the position
   if(ticket != 0 && PositionSelectByTicket(ticket))
     {
      bool isLong = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      if((isLong && shortSig) || (!isLong && longSig))
        {
         trade.PositionClose(ticket);
         Print("EXIT signal flip");
         ticket = 0;
        }
      else
         return;   // already positioned, nothing more to do
     }

   // --- entries
   if(ticket != 0 || (!longSig && !shortSig)) return;
   if(!EntriesAllowed()) return;

   double stopDist = InpStopAtrMult * atr;
   if(longSig)
     {
      double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double lots = CalcLots(ask, stopDist);
      if(lots <= 0) return;
      double sl = LegalStop(true, ask - stopDist);
      if(sl <= 0) return;
      if(trade.Buy(lots, _Symbol, 0.0, sl, 0.0, "TBF breakout long"))
         Print("ENTER LONG ", lots, " lots, stop ", sl);
      else
         Print("Buy failed: ", trade.ResultRetcodeDescription());
     }
   else if(shortSig)
     {
      double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double lots = CalcLots(bid, stopDist);
      if(lots <= 0) return;
      double sl = LegalStop(false, bid + stopDist);
      if(sl <= 0) return;
      if(trade.Sell(lots, _Symbol, 0.0, sl, 0.0, "TBF breakout short"))
         Print("ENTER SHORT ", lots, " lots, stop ", sl);
      else
         Print("Sell failed: ", trade.ResultRetcodeDescription());
     }
  }
//+------------------------------------------------------------------+
