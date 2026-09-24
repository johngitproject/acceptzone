using System;
using System.Collections.Generic;

namespace SwingCore
{
    /// <summary>
    /// Swing reoffer/rebid zones, mirror of backtest_swing_v03 zone creation.
    /// A day D whose RTH range touches a prior swing (lookback 20 calendar days)
    /// becomes a zone day once closed: retest of a Swing High -&gt; reoffer
    /// (short bias), retest of a Swing Low -&gt; rebid (long bias).
    /// Touch: High &gt;= swing - BUF*tick (high) / Low &lt;= swing + BUF*tick (low).
    /// Zone value = day D 70% VA (VAH/VAL/POC supplied by caller, uniform or
    /// native source). One zone per type per day, first touching swing wins
    /// (swings iterated in date order, same as Python). HOLD/freshest logic
    /// counts RTH days, not calendar days (spec S2 fix).
    /// </summary>
    public readonly struct SwingZone
    {
        public SwingZone(DateTime creation, string type, double vah, double val, double poc,
            double swingRef, DateTime swingDate)
        {
            Creation = creation.Date;
            Type = type;
            Vah = vah;
            Val = val;
            Poc = poc;
            SwingRef = swingRef;
            SwingDate = swingDate.Date;
        }

        public DateTime Creation { get; }
        public string Type { get; }       // "reoffer" | "rebid"
        public double Vah { get; }
        public double Val { get; }
        public double Poc { get; }
        public double SwingRef { get; }
        public DateTime SwingDate { get; }
        public double Width => Vah - Val;
        public int Bias => Type == "reoffer" ? 1 : -1;  // 1 = resistance to short, -1 = support to long
    }

    public readonly struct ZoneDayFrame
    {
        public ZoneDayFrame(DateTime day, double open, double high, double low,
            double vah, double val, double poc, bool hasProfile)
        {
            Day = day.Date;
            Open = open;
            High = high;
            Low = low;
            Vah = vah;
            Val = val;
            Poc = poc;
            HasProfile = hasProfile;
        }

        public DateTime Day { get; }
        public double Open { get; }
        public double High { get; }
        public double Low { get; }
        public double Vah { get; }
        public double Val { get; }
        public double Poc { get; }
        public bool HasProfile { get; }
    }

    public sealed class SwingZoneEngine
    {
        private readonly double _tickSize;
        private readonly int _bufTicks;
        private readonly List<SwingZone> _zones = new List<SwingZone>();

        public SwingZoneEngine(double tickSize, int bufTicks = 2)
        {
            if (tickSize <= 0) throw new ArgumentOutOfRangeException(nameof(tickSize));
            _tickSize = tickSize;
            _bufTicks = bufTicks;
        }

        public IReadOnlyList<SwingZone> Zones => _zones;

        /// <summary>Feed one CLOSED day. Returns zones created (0, 1 or 2).</summary>
        public List<SwingZone> FeedDay(ZoneDayFrame frame, IReadOnlyList<SwingMark> activeSwings)
        {
            var made = new List<SwingZone>();
            if (!frame.HasProfile)
                return made;
            var madeTypes = new HashSet<string>();
            foreach (var s in activeSwings)
            {
                string zt;
                bool touched;
                if (s.IsHigh)
                {
                    touched = frame.High >= s.Price - _bufTicks * _tickSize;
                    zt = "reoffer";
                }
                else
                {
                    touched = frame.Low <= s.Price + _bufTicks * _tickSize;
                    zt = "rebid";
                }
                if (touched && !madeTypes.Contains(zt))
                {
                    var z = new SwingZone(frame.Day, zt, frame.Vah, frame.Val, frame.Poc, s.Price, s.Day);
                    _zones.Add(z);
                    made.Add(z);
                    madeTypes.Add(zt);
                }
            }
            return made;
        }

        /// <summary>
        /// Zones active on rthDay: 1 &lt;= fwd &lt;= holdMax where fwd counts RTH days
        /// after creation. isFreshest = creation is the max among actives.
        /// </summary>
        public List<(SwingZone zone, int fwd, bool isFreshest)> ActiveFor(
            DateTime rthDay, IReadOnlyList<DateTime> rthDays, int holdMax)
        {
            var d = rthDay.Date;
            var fwdByZone = new Dictionary<int, int>();
            for (int i = 0; i < _zones.Count; i++)
            {
                var z = _zones[i];
                if (!(z.Creation < d))
                    continue;
                int fwd = 0;
                foreach (var rd in rthDays)
                {
                    var r = rd.Date;
                    if (z.Creation < r && r <= d)
                        fwd++;
                }
                if (fwd >= 1 && fwd <= holdMax)
                    fwdByZone[i] = fwd;
            }
            DateTime newest = DateTime.MinValue;
            foreach (var i in fwdByZone.Keys)
                if (_zones[i].Creation > newest)
                    newest = _zones[i].Creation;
            var out_ = new List<(SwingZone, int, bool)>();
            foreach (var kv in fwdByZone)
                out_.Add((_zones[kv.Key], kv.Value, _zones[kv.Key].Creation == newest));
            return out_;
        }

        public static bool IsGoodSide(string zoneType, string levelName)
        {
            if (zoneType == "reoffer")
                return levelName == "VAH" || levelName == "POC";
            return levelName == "VAL";   // rebid -> long VAL only (spec v04)
        }
    }
}
