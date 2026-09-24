using System;
using System.Globalization;
using System.Text;

namespace SwingCore
{
    /// <summary>
    /// CSV writer shared by the 5 swing strategies. Invariant-culture doubles
    /// (Python writes '.' decimals; ';' separator) so files stay comparable
    /// with scripts/backtest_*.py outputs whatever the Windows locale is.
    /// </summary>
    public static class SwingCsv
    {
        public const string Header =
            "TradeId;Market;Date;Hyp;Dir;EntryRef;ExitPx;Res;Source;ZoneType;Lvl;UT;Kind;Target;Attempt;Prev;Flip;Fresh;InZone;PocPos;EntryBar;StopPx;T1Px;T2Px;T3Px;Qty";

        public static string D(double v)
        {
            return v.ToString("0.##", CultureInfo.InvariantCulture);
        }

        public static string Row(params object[] cols)
        {
            var sb = new StringBuilder();
            for (int i = 0; i < cols.Length; i++)
            {
                if (i > 0) sb.Append(';');
                object c = cols[i];
                if (c is double d) sb.Append(D(d));
                else if (c is DateTime dt) sb.Append(dt.ToString("yyyy-MM-dd"));
                else sb.Append(c);
            }
            return sb.ToString();
        }
    }
}
