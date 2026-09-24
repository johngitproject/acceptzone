#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Windows;
using System.Windows.Media;
using System.Xml.Serialization;
using NinjaTrader.Data;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
#endregion

namespace NinjaTrader.NinjaScript.Indicators
{
	/// <summary>
	/// AcceptZone : zones d'acceptation sur triplets Daily (J1/J2/J3).
	/// Balance VAL1 &lt;= POC2 &lt;= VAH1, composite J1+J2 recalcule a 70 %,
	/// acceptation J3 : POC3 au-dela de POC1/POC2 et de VAHc/VALc + BUF
	/// -&gt; REBID long / REOFFER short. Moteur :
	/// - triplet evalue sur barres Daily CLOSES (J3 = Times[1][1], pas la bougie
	///   en formation), warmup 4 seances ;
	/// - profils journaliers mis en cache (1 seul scan 1-min par jour clos),
	///   composite J1+J2 par fusion des dicts (pas de rescan de 2 jours) ;
	/// - profils = Value Area 70 % (defaut) du volume 1-min NT8 (rows de
	///   4 ticks, volume reparti uniformement sur [Low..High]).
	/// Evaluation une fois par jour a la cloture Daily : jamais de recalcul
	/// intra-jour, pas de repeinture (VAH/VAL/POC geles a la creation).
	/// Zones et POC etendus a droite jusqu'au dernier prix (redessines a chaque
	/// cloture H1). Affichage seul : aucun ordre, aucun signal d'entree.
	/// Chart attendu : H1, template ETH. Chargez au moins ~10 jours.
	/// </summary>
	public class AcceptZone : Indicator
	{
		private class DayProfile
		{
			public DateTime Open;                       // open Daily (cle cache)
			public DateTime NextOpen;                   // open Daily suivant (fin fenetre)
			public Dictionary<int, double> Vol;         // volume par row
			public double PHigh = double.NaN;
			public double PLow = double.NaN;
			public double Vah = double.NaN;
			public double Val = double.NaN;
			public double Poc = double.NaN;
			public int NBars;
			public bool Ok;
		}

		private class AcceptZone
		{
			public string Tag;
			public DateTime J1;
			public DateTime J2;
			public DateTime J3;
			public DateTime Start;   // open du jour suivant J3 = debut du trace
			public double Vah = double.NaN; // composite J1+J2
			public double Val = double.NaN;
			public double Poc = double.NaN;
			public double Poc3 = double.NaN;
			public bool IsRebid;     // true = rebid (long), false = reoffer (short)
		}

		private readonly Dictionary<DateTime, DayProfile> _profCache = new Dictionary<DateTime, DayProfile>();
		private readonly List<AcceptZone> _zones = new List<AcceptZone>();
		private DateTime _lastJ3 = DateTime.MinValue;
		private int _cachedRowTicks = -1;
		private bool _warnedHist;
		private bool _beat;
		private int _dbgTriplets;
		private int _dbgZones;
		private string _dbgSkip = "aucun triplet evalue";

		public override string DisplayName => Name;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = @"AcceptZone : zones d'acceptation (triplets Daily J1/J2/J3 closes, VA 1-min 70 %, composite J1+J2). Chart H1, template ETH. Chargez au moins ~10 jours.";
				Name = "AcceptZone";
				Calculate = Calculate.OnBarClose;
				IsOverlay = true;
				DisplayInDataBox = false;
				DrawOnPricePanel = true;
				IsSuspendedWhileInactive = true;
				PaintPriceMarkers = false;
				IsAutoScale = false;
				BarsRequiredToPlot = 2;
				MaximumBarsLookBack = MaximumBarsLookBack.Infinite; // 1-min profond pour les profils journaliers
				BufferTicks = 2;
				ValueAreaPct = 70;
				RowHeightTicks = 4;
				MinDayBars = 600;
				MaxZones = 5;
				ShowRebid = true;
				ShowReoffer = true;
				ShowPoc = true;
				Verbose = false;
				RebidColor = Brushes.Green;
				ReofferColor = Brushes.Red;
				ZoneOpacity = 20;
				ZoneBorderWidth = 1;
			}
			else if (State == State.Configure)
			{
				try { AddDataSeries(BarsPeriodType.Day, 1); }    // BIP 1 : bougies Daily
				catch (Exception ex) { try { Print(Name + " : serie Daily refusee (" + ex.Message + ")."); } catch {} }
				try { AddDataSeries(BarsPeriodType.Minute, 1); } // BIP 2 : volume des profils
				catch (Exception ex) { try { Print(Name + " : serie Minute refusee (" + ex.Message + ")."); } catch {} }
			}
			else if (State == State.DataLoaded)
			{
				_profCache.Clear();
				_zones.Clear();
				_lastJ3 = DateTime.MinValue;
				_cachedRowTicks = -1;
				_warnedHist = false;
				_beat = false;
				_dbgTriplets = 0;
				_dbgZones = 0;
				_dbgSkip = "aucun triplet evalue";
			}
			else if (State == State.Terminated)
			{
				_profCache.Clear();
				_zones.Clear();
			}
		}

		#region Profils (volume 1-min par jour + Value Area 70 %)

		private double RowSize()
		{
			double tick = 0;
			try { tick = Instrument.MasterInstrument.TickSize; } catch {}
			if (tick <= 0) return double.NaN;
			return tick * Math.Max(1, RowHeightTicks);
		}

		// Scan 1-min sur la fenetre [startT, endT) : un seul passage, break precoce
		// (Times[2] trie du plus recent au plus vieux).
		private DayProfile BuildDay(DateTime startT, DateTime endT)
		{
			var dp = new DayProfile { Open = startT, NextOpen = endT, Vol = new Dictionary<int, double>() };
			try
			{
				if (CurrentBars[2] < 1) return dp;
				double rowSize = RowSize();
				if (double.IsNaN(rowSize) || rowSize <= 0) return dp;
				var vol = new Dictionary<int, double>();
				double pHigh = double.MinValue, pLow = double.MaxValue;
				int nBars = 0;
				for (int ago = 0; ago <= CurrentBars[2]; ago++)
				{
					DateTime t;
					try { t = Times[2][ago]; } catch { break; }
					if (t >= endT) continue;   // barres posterieures a la fenetre
					if (t < startT) break;     // plus vieux que la fenetre : fini
					double h = Highs[2][ago], l = Lows[2][ago], v = Volumes[2][ago];
					if (double.IsNaN(h) || double.IsNaN(l) || double.IsNaN(v) || v <= 0) continue;
					nBars++;
					if (h > pHigh) pHigh = h;
					if (l < pLow) pLow = l;
					int lo = (int)Math.Floor(l / rowSize);
					int hi = (int)Math.Floor(h / rowSize);
					int n = Math.Max(1, hi - lo + 1);
					double q = v / n;
					for (int k = lo; k <= hi; k++)
						vol[k] = vol.ContainsKey(k) ? vol[k] + q : q;
				}
				dp.NBars = nBars;
				dp.Vol = vol;
				dp.PHigh = pHigh;
				dp.PLow = pLow;
				if (nBars <= 0 || vol.Count == 0) return dp;
				double vah, val, poc;
				if (!ComputeVA(vol, pHigh, pLow, rowSize, ValueAreaPct, out vah, out val, out poc))
					return dp;
				dp.Vah = vah; dp.Val = val; dp.Poc = poc;
				dp.Ok = !(double.IsNaN(vah) || double.IsNaN(val) || double.IsNaN(poc)) && val < vah;
				return dp;
			} catch { return dp; }
		}

		// Value Area : POC = row max volume (tie-break = plus proche
		// du milieu), expansion par la row voisine la plus volumineuse.
		private static bool ComputeVA(Dictionary<int, double> vol, double pHigh, double pLow,
			double rowSize, double vaPct, out double vah, out double val, out double poc)
		{
			vah = double.NaN; val = double.NaN; poc = double.NaN;
			try
			{
				if (vol == null || vol.Count == 0) return false;
				double mid = (pHigh + pLow) * 0.5;
				int pock = 0; double pv = double.MinValue; bool first = true;
				int minK = int.MaxValue, maxK = int.MinValue;
				double tot = 0;
				foreach (var kv in vol)
				{
					tot += kv.Value;
					if (kv.Key < minK) minK = kv.Key;
					if (kv.Key > maxK) maxK = kv.Key;
					double rowMid = (kv.Key + 0.5) * rowSize;
					if (first || kv.Value > pv || (kv.Value == pv && Math.Abs(rowMid - mid) < Math.Abs((pock + 0.5) * rowSize - mid)))
					{ pock = kv.Key; pv = kv.Value; first = false; }
				}
				if (tot <= 0) return false;
				int loK = pock, hiK = pock;
				double acc = vol[pock];
				double target = tot * vaPct / 100.0;
				int guard = 0;
				while (acc < target && guard++ < 100000)
				{
					double up = (hiK + 1 <= maxK && vol.ContainsKey(hiK + 1)) ? vol[hiK + 1] : -1;
					double dn = (loK - 1 >= minK && vol.ContainsKey(loK - 1)) ? vol[loK - 1] : -1;
					if (up < 0 && dn < 0) break;
					if (up >= dn) { hiK++; if (vol.ContainsKey(hiK)) acc += vol[hiK]; }
					else { loK--; if (vol.ContainsKey(loK)) acc += vol[loK]; }
				}
				vah = (hiK + 1) * rowSize;
				val = loK * rowSize;
				poc = pock * rowSize;
				return true;
			} catch { return false; }
		}

		private DayProfile GetDay(DateTime startT, DateTime endT)
		{
			// Le param RowHeightTicks change la granularite des rows : invalide le cache.
			if (_cachedRowTicks != RowHeightTicks)
			{
				_profCache.Clear();
				_cachedRowTicks = RowHeightTicks;
			}
			DayProfile cached;
			if (_profCache.TryGetValue(startT, out cached) && cached != null && cached.NextOpen == endT)
				return cached;
			DayProfile fresh = BuildDay(startT, endT);
			_profCache[startT] = fresh;
			// Borne anti-fuite memoire : ~120 derniers jours suffisent pour MaxZones=50.
			if (_profCache.Count > 150)
			{
				DateTime oldest = DateTime.MaxValue;
				foreach (var k in _profCache.Keys)
					if (k < oldest) oldest = k;
				_profCache.Remove(oldest);
			}
			return fresh;
		}

		private DayProfile BuildComposite(DayProfile d1, DayProfile d2)
		{
			var c = new DayProfile { Open = d1.Open, NextOpen = d2.NextOpen, Vol = new Dictionary<int, double>() };
			try
			{
				if (d1.Vol == null || d2.Vol == null) return c;
				double rowSize = RowSize();
				if (double.IsNaN(rowSize) || rowSize <= 0) return c;
				var merged = new Dictionary<int, double>(d1.Vol.Count + d2.Vol.Count);
				foreach (var kv in d1.Vol)
					merged[kv.Key] = kv.Value;
				foreach (var kv in d2.Vol)
					merged[kv.Key] = merged.ContainsKey(kv.Key) ? merged[kv.Key] + kv.Value : kv.Value;
				c.Vol = merged;
				c.PHigh = Math.Max(d1.PHigh, d2.PHigh);
				c.PLow = Math.Min(d1.PLow, d2.PLow);
				c.NBars = d1.NBars + d2.NBars;
				double vah, val, poc;
				if (!ComputeVA(merged, c.PHigh, c.PLow, rowSize, ValueAreaPct, out vah, out val, out poc))
					return c;
				c.Vah = vah; c.Val = val; c.Poc = poc;
				c.Ok = !(double.IsNaN(vah) || double.IsNaN(val) || double.IsNaN(poc)) && val < vah;
				return c;
			} catch { return c; }
		}
		#endregion

		#region Detection (une fois par jour, sur Daily closes)

		private bool IsLastDailyBar()
		{
			try
			{
				if (BarsArray[1] == null) return true;
				return CurrentBars[1] >= BarsArray[1].Count - 2;
			} catch { return true; }
		}

		private void Log(string s)
		{
			if (!Verbose) return;
			try { Print(Name + " : " + s); } catch {}
		}

		private void OnDailyClose()
		{
			try
			{
				// Triplet clos J1/J2/J3 + forming : 4 opens Daily requis (marge incluse).
				if (CurrentBars[1] < 4)
				{
					if (!_warnedHist && IsLastDailyBar())
					{
						_warnedHist = true;
						try { Print(Name + " : historique insuffisant — chargez au moins ~10 jours (daily : " + CurrentBars[1] + "/4)."); } catch {}
					}
					return;
				}
				if (CurrentBars[2] < 1) return;

				DateTime jNext, j3open, j2open, j1open;
				try
				{
					jNext = Times[1][0];   // open en formation -> Start du trace
					j3open = Times[1][1];  // J3 : jour qui vient de closer
					j2open = Times[1][2];
					j1open = Times[1][3];
				}
				catch { return; }

				if (j3open == _lastJ3) return;
				_lastJ3 = j3open;
				_dbgTriplets++;

				double tick = 0;
				try { tick = Instrument.MasterInstrument.TickSize; } catch {}
				if (tick <= 0) { _dbgSkip = "ticksize invalide"; return; }

				int minBars = Math.Max(1, MinDayBars);
				DayProfile d1 = GetDay(j1open, j2open);
				if (d1 == null || !d1.Ok) { _dbgSkip = "profil J1 vide (" + j1open.ToString("yyyy-MM-dd") + ")"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }
				if (d1.NBars < minBars) { _dbgSkip = "J1 incomplet (" + d1.NBars + ")"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }
				DayProfile d2 = GetDay(j2open, j3open);
				if (d2 == null || !d2.Ok) { _dbgSkip = "profil J2 vide (" + j2open.ToString("yyyy-MM-dd") + ")"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }
				if (d2.NBars < minBars) { _dbgSkip = "J2 incomplet (" + d2.NBars + ")"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }
				DayProfile d3 = GetDay(j3open, jNext);
				if (d3 == null || !d3.Ok) { _dbgSkip = "profil J3 vide (" + j3open.ToString("yyyy-MM-dd") + ")"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }
				if (d3.NBars < minBars) { _dbgSkip = "J3 incomplet (" + d3.NBars + ")"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }

				// Balance : POC2 dans VA1
				if (!(d1.Val <= d2.Poc && d2.Poc <= d1.Vah))
				{ _dbgSkip = "pas de balance POC2 hors VA1"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }

				// Composite J1+J2 recalcule 70 % (fusion, pas de rescan)
				DayProfile c = BuildComposite(d1, d2);
				if (c == null || !c.Ok) { _dbgSkip = "composite vide"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }

				// Acceptation (BUF = BufferTicks x TickSize)
				double buf = BufferTicks * tick;
				bool isRebid;
				if (d3.Poc > d1.Poc && d3.Poc > d2.Poc && d3.Poc > c.Vah + buf)
					isRebid = true;
				else if (d3.Poc < d1.Poc && d3.Poc < d2.Poc && d3.Poc < c.Val - buf)
					isRebid = false;
				else
				{ _dbgSkip = "pas d'acceptation POC3 dans composite"; Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip); return; }

				string tag = "ACZ_" + j3open.ToString("yyyyMMdd");
				AddSignal(new AcceptZone
				{
					Tag = tag, J1 = j1open, J2 = j2open, J3 = j3open, Start = jNext,
					Vah = c.Vah, Val = c.Val, Poc = c.Poc, Poc3 = d3.Poc, IsRebid = isRebid
				});
				_dbgSkip = "zone " + (isRebid ? "REBID" : "REOFFER") + " " + j3open.ToString("yyyy-MM-dd");
				Log("triplet " + j1open.ToString("yyyy-MM-dd") + " : " + _dbgSkip
					+ " VAH " + c.Vah.ToString("0.##") + " VAL " + c.Val.ToString("0.##") + " POC " + c.Poc.ToString("0.##"));

				if (IsLastDailyBar())
				{
					try
					{
						int nD = 0, nM = 0;
						try { nD = BarsArray[1] != null ? BarsArray[1].Count : 0; } catch {}
						try { nM = BarsArray[2] != null ? BarsArray[2].Count : 0; } catch {}
						Print(Name + " : resume — " + nD + " daily / " + nM + " 1-min, "
							+ _dbgTriplets + " triplets evalues, " + _dbgZones + " zones. Dernier : " + _dbgSkip + ".");
					} catch {}
				}
			} catch {}
		}

		private void AddSignal(AcceptZone z)
		{
			_zones.Add(z);
			_dbgZones++;
			try { Print(Name + " : nouvelle zone " + (z.IsRebid ? "REBID" : "REOFFER") + " " + z.J1.ToString("yyyy-MM-dd") + "->" + z.J3.ToString("yyyy-MM-dd") + " VAH " + z.Vah.ToString("0.##") + " VAL " + z.Val.ToString("0.##") + " POC " + z.Poc.ToString("0.##") + "."); } catch {}
			int max = Math.Max(1, MaxZones);
			while (_zones.Count > max)
			{
				try { RemoveDrawObject(_zones[0].Tag + "_Z"); } catch {}
				try { RemoveDrawObject(_zones[0].Tag + "_P"); } catch {}
				try { RemoveDrawObject(_zones[0].Tag + "_L"); } catch {}
				_zones.RemoveAt(0);
			}
			RedrawAll();
		}
		#endregion

		#region Dessin (rectangles seuls + POC optionnel, extension jusqu'au dernier prix)
		private void RedrawAll()
		{
			try
			{
				if (BarsArray[0] == null || BarsArray[0].Count == 0 || CurrentBars[0] < 0) return;
				foreach (var z in _zones) DrawZone(z);
			} catch {}
		}

		private void DrawZone(AcceptZone z)
		{
			DateTime endT;
			try { endT = Times[0][0]; } catch { return; }
			bool show = (z.IsRebid && ShowRebid) || (!z.IsRebid && ShowReoffer);
			if (!show)
			{
				try { RemoveDrawObject(z.Tag + "_Z"); } catch {}
				try { RemoveDrawObject(z.Tag + "_P"); } catch {}
				try { RemoveDrawObject(z.Tag + "_L"); } catch {}
				return;
			}
			if (double.IsNaN(z.Vah) || double.IsNaN(z.Val) || double.IsNaN(z.Poc)) return;
			if (!(z.Val < z.Vah)) return;
			if (endT <= z.Start) return;
			Brush color = z.IsRebid ? RebidColor : ReofferColor;
			try
			{
				var rect = Draw.Rectangle(this, z.Tag + "_Z", false, z.Start, z.Vah, endT, z.Val, color, color, ZoneOpacity);
				if (rect != null && rect.OutlineStroke != null)
					rect.OutlineStroke = new Stroke(color, DashStyleHelper.Solid, ZoneBorderWidth) { RenderTarget = rect.OutlineStroke.RenderTarget };
			} catch {}
			if (ShowPoc)
			{
				try { Draw.Line(this, z.Tag + "_P", false, z.Start, z.Poc, endT, z.Poc, color, DashStyleHelper.Solid, ZoneBorderWidth); } catch {}
			}
			else { try { RemoveDrawObject(z.Tag + "_P"); } catch {} }
			try
			{
				string label = (z.IsRebid ? "REBID " : "REOFFER ") + z.J1.ToString("yyyy-MM-dd") + "->" + z.J3.ToString("yyyy-MM-dd") + " POC " + z.Poc.ToString("0.##");
				Draw.Text(this, z.Tag + "_L", false, label, 0, z.Poc, 0, color, new Gui.Tools.SimpleFont("Arial", 9), TextAlignment.Right, null, null, 0);
			} catch {}
		}
		#endregion

		protected override void OnBarUpdate()
		{
			try
			{
				if (!_beat)
				{
					_beat = true;
					try
					{
						int nH = 0, nD = 0, nM = 0;
						try { nH = BarsArray[0] != null ? BarsArray[0].Count : 0; } catch {}
						try { nD = BarsArray[1] != null ? BarsArray[1].Count : 0; } catch {}
						try { nM = BarsArray[2] != null ? BarsArray[2].Count : 0; } catch {}
						Print(Name + " : actif — series chargees H1=" + nH + " / Daily=" + nD + " / Min1=" + nM + ".");
					} catch {}
				}
				if (BarsInProgress == 1) { OnDailyClose(); return; }
				if (BarsInProgress != 0) return;
				RedrawAll();
			} catch {}
		}

		#region Properties - Prerequis
		[NinjaScriptProperty]
		[ReadOnly(true)]
		[Display(Name = "Historique minimum requis", Description = "Chargez au moins ~10 jours (Days to load) : detection active apres 4 seances daily.", Order = 1, GroupName = "AcceptZone")]
		public string InfoHistoriqueMinimum
		{
			get { return "Chargez au moins ~10 jours : detection active apres 4 seances daily."; }
			set { }
		}
		#endregion

		#region Properties - Seuils
		[NinjaScriptProperty]
		[Display(Name = "Buffer acceptation (ticks)", Description = "BUF balance/acceptation (2t, defaut backtest).", Order = 10, GroupName = "AcceptZone")]
		[Range(0, 32)]
		public int BufferTicks { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Value Area %", Description = "Part du profil.", Order = 11, GroupName = "AcceptZone")]
		[Range(50, 95)]
		public double ValueAreaPct { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Hauteur row profil (ticks)", Description = "Rows du profil. Changer vide le cache.", Order = 12, GroupName = "AcceptZone")]
		[Range(1, 32)]
		public int RowHeightTicks { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Barres 1-min min/jour", Description = "Barres 1-min minimum par jour valide.", Order = 13, GroupName = "AcceptZone")]
		[Range(100, 5000)]
		public int MinDayBars { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Max zones", Description = "Zones conservees (plus recentes).", Order = 14, GroupName = "AcceptZone")]
		[Range(1, 50)]
		public int MaxZones { get; set; }
		#endregion

		#region Properties - Affichage
		[NinjaScriptProperty]
		[Display(Name = "Afficher Rebid", Order = 20, GroupName = "AcceptZone")]
		public bool ShowRebid { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Afficher Reoffer", Order = 21, GroupName = "AcceptZone")]
		public bool ShowReoffer { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Afficher POC", Order = 22, GroupName = "AcceptZone")]
		public bool ShowPoc { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Verbose (1 ligne/triplet)", Description = "Log Output du verdict de chaque triplet (debug).", Order = 23, GroupName = "AcceptZone")]
		public bool Verbose { get; set; }
		#endregion

		#region Properties - Style
		[NinjaScriptProperty]
		[XmlIgnore]
		[Display(Name = "Couleur Rebid", Order = 30, GroupName = "AcceptZone")]
		public Brush RebidColor { get; set; }

		[Browsable(false)]
		public string RebidColorSerializable
		{
			get { return Serialize.BrushToString(RebidColor); }
			set { RebidColor = Serialize.StringToBrush(value); }
		}

		[NinjaScriptProperty]
		[XmlIgnore]
		[Display(Name = "Couleur Reoffer", Order = 31, GroupName = "AcceptZone")]
		public Brush ReofferColor { get; set; }

		[Browsable(false)]
		public string ReofferColorSerializable
		{
			get { return Serialize.BrushToString(ReofferColor); }
			set { ReofferColor = Serialize.StringToBrush(value); }
		}

		[NinjaScriptProperty]
		[Display(Name = "Opacite zone (0-100)", Order = 32, GroupName = "AcceptZone")]
		[Range(0, 100)]
		public int ZoneOpacity { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Epaisseur bordure zone", Order = 33, GroupName = "AcceptZone")]
		[Range(1, 5)]
		public int ZoneBorderWidth { get; set; }
		#endregion
	}
}
