"""Write the bootstrap snapshots for 2025-Q3, 2025-Q4, 2026-Q1.

Numbers are Berkshire Hathaway's 13F holdings cross-checked on valuesider.com
against the SEC filings named in META below. This seed exists for provenance
and reproducibility; the live pipeline will overwrite each period with the raw
EDGAR information table on its first successful fetch (run.py skips a period
only while its snapshot is already present, so delete a folder to refresh it).

Run:  python tools/seed_bootstrap.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

NAMES = {
    "ALLE": "Allegion plc", "ALLY": "Ally Financial Inc",
    "GOOGL": "Alphabet Inc", "GOOG": "Alphabet Inc",
    "AMZN": "Amazon.com Inc", "AXP": "American Express Co", "AON": "Aon plc",
    "AAPL": "Apple Inc", "BATRK": "Atlanta Braves Holdings Inc",
    "BAC": "Bank of America Corp", "COF": "Capital One Financial Corp",
    "CHTR": "Charter Communications Inc", "CVX": "Chevron Corp",
    "CB": "Chubb Ltd", "KO": "Coca-Cola Co", "STZ": "Constellation Brands Inc",
    "DVA": "DaVita Inc", "DEO": "Diageo plc", "DPZ": "Domino's Pizza Inc",
    "HEI.A": "HEICO Corp", "JEF": "Jefferies Financial Group Inc",
    "KHC": "Kraft Heinz Co", "KR": "Kroger Co", "LAMR": "Lamar Advertising Co",
    "LEN.B": "Lennar Corp", "LEN": "Lennar Corp",
    "LILA": "Liberty Latin America Ltd", "LILAK": "Liberty Latin America Ltd",
    "LLYVA": "Liberty Media Corp (Liberty Live)",
    "LLYVK": "Liberty Media Corp (Liberty Live)",
    "FWONK": "Liberty Media Corp (Formula One)",
    "LPX": "Louisiana-Pacific Corp", "MA": "Mastercard Inc",
    "MCO": "Moody's Corp", "NYT": "New York Times Co", "NUE": "Nucor Corp",
    "NVR": "NVR Inc", "OXY": "Occidental Petroleum Corp", "POOL": "Pool Corp",
    "SIRI": "Sirius XM Holdings Inc", "UNH": "UnitedHealth Group Inc",
    "VRSN": "VeriSign Inc", "V": "Visa Inc", "DAL": "Delta Air Lines Inc",
    "M": "Macy's Inc",
}
CL = {
    "GOOGL": "CL A", "GOOG": "CL C", "BATRK": "SER C", "CHTR": "CL A",
    "HEI.A": "CL A", "LEN.B": "CL B", "LILA": "CL A", "LILAK": "CL C",
    "LLYVA": "CL A", "LLYVK": "CL C", "FWONK": "CL C", "MA": "CL A",
    "NYT": "CL A", "V": "CL A", "LAMR": "CL A",
}

# (ticker, shares, value_usd)
Q3_2025 = [
    ("ALLE", 780133, 138356588), ("ALLY", 29000000, 1136800000),
    ("GOOGL", 17846142, 4338397121), ("AMZN", 10000000, 2195700000),
    ("AXP", 151610700, 50359010112), ("AON", 4100000, 1461978000),
    ("AAPL", 238212764, 60656116097), ("BATRK", 223645, 9301396),
    ("BAC", 568070012, 29306731919), ("COF", 7150000, 1519947000),
    ("CHTR", 1060882, 291853943), ("CVX", 122064792, 18955441549),
    ("CB", 31332895, 8843709614), ("KO", 400000000, 26528000000),
    ("STZ", 13400000, 1804578000), ("DVA", 32160579, 4273176132),
    ("DEO", 227750, 21734183), ("DPZ", 2981945, 1287335476),
    ("HEI.A", 1294612, 328947963), ("JEF", 433558, 28363364),
    ("KHC", 325634818, 8479530661), ("KR", 50000000, 3370500001),
    ("LAMR", 1202110, 147162306), ("LEN.B", 180980, 21715790),
    ("LEN", 7050950, 888701738), ("LILA", 2630792, 21809266),
    ("LILAK", 1284020, 10837129), ("LLYVA", 4986588, 470235248),
    ("LLYVK", 10917661, 1058685587), ("FWONK", 3018555, 315288070),
    ("LPX", 5664793, 503260211), ("MA", 3986648, 2267645249),
    ("MCO", 24669778, 11754655821), ("NUE", 6407749, 867801447),
    ("NVR", 11112, 89281142), ("OXY", 264941431, 12518482615),
    ("POOL", 3458885, 1072496472), ("SIRI", 124807117, 2904885649),
    ("UNH", 5039564, 1740161449), ("VRSN", 8989880, 2513300752),
    ("V", 8297460, 2832586895),
]
Q4_2025 = [
    ("ALLE", 780133, 124212776), ("ALLY", 29000000, 1313410001),
    ("GOOGL", 17846142, 5585842446), ("AMZN", 2276000, 525346320),
    ("AXP", 151610700, 56088378465), ("AON", 3602995, 1271424876),
    ("AAPL", 227917808, 61961735283), ("BATRK", 115428, 4553634),
    ("BAC", 517295934, 28451276370), ("COF", 7150000, 1732874000),
    ("CHTR", 1060882, 221459118), ("CVX", 130156362, 19837131131),
    ("CB", 34249183, 10689854998), ("KO", 400000000, 27964000000),
    ("STZ", 13000000, 1793480000), ("DVA", 31759065, 3608147375),
    ("DEO", 227750, 19647993), ("DPZ", 3350000, 1396347000),
    ("HEI.A", 1294612, 326798907), ("JEF", 433558, 26867589),
    ("KHC", 325634818, 7896644337), ("KR", 50000000, 3124000000),
    ("LAMR", 1202410, 152201058), ("LEN.B", 180980, 17214818),
    ("LEN", 7050950, 724837660), ("LILA", 2396665, 17711354),
    ("LILAK", 1284020, 9578789), ("LLYVA", 4986588, 406406923),
    ("LLYVK", 10917661, 907912688), ("FWONK", 3018555, 297357853),
    ("LPX", 5664793, 457488683), ("MA", 3986648, 2275897610),
    ("MCO", 24669778, 12602556092), ("NYT", 5065744, 351663948),
    ("NUE", 6407749, 1045167939), ("NVR", 11112, 81037260),
    ("OXY", 264941431, 10894391643), ("POOL", 3068885, 702007444),
    ("SIRI", 124807117, 2495518305), ("UNH", 5039564, 1663610472),
    ("VRSN", 8989880, 2184091346), ("V", 8297460, 2910002197),
]
Q1_2026 = [
    ("ALLY", 29000000, 1137670000), ("GOOGL", 54249798, 15600071913),
    ("GOOG", 3585215, 1028454775), ("AXP", 151610700, 45859204536),
    ("AAPL", 227917808, 57843260493), ("BAC", 513624165, 25039178044),
    ("COF", 7150000, 1304374500), ("CVX", 84375856, 17457364606),
    ("CB", 34249183, 11162836215), ("KO", 400000000, 30420000000),
    ("STZ", 632890, 94933500), ("DVA", 30100585, 4626158909),
    ("DAL", 39809456, 2646532635), ("JEF", 433558, 17892939),
    ("KHC", 325634818, 7323527057), ("KR", 50000000, 3618000000),
    ("LEN.B", 237703, 19995576), ("LEN", 10099642, 877052911),
    ("LLYVA", 4986588, 456970925), ("LLYVK", 10587143, 996356028),
    ("LPX", 5664793, 412113691), ("M", 3038355, 54963842),
    ("MCO", 24669778, 10762190653), ("NYT", 15146535, 1268219376),
    ("NUE", 3907075, 660686383), ("NVR", 11112, 73226191),
    ("OXY", 264941431, 17221193015), ("SIRI", 124807117, 2880548260),
    ("VRSN", 8989880, 2232726597),
]

META = {
    "2025-09-30": {"filed": "2025-11-14", "accession": "0001193125-25-282901",
                   "reported_total": 267334501955},
    "2025-12-31": {"filed": "2026-02-17", "accession": "0001193125-26-054580",
                   "reported_total": 274160086701},
    "2026-03-31": {"filed": "2026-05-15", "accession": "0001193125-26-226661",
                   "reported_total": 263095703570},
}
DATA = {"2025-09-30": Q3_2025, "2025-12-31": Q4_2025, "2026-03-31": Q1_2026}
SOURCE = "bootstrap: valuesider (derived from SEC 13F)"


def row(ticker, shares, value):
    return [ticker, NAMES[ticker], CL.get(ticker, ""), shares, value]


def main():
    all_ok = True
    for period, holdings in DATA.items():
        rows = [row(*h) for h in holdings]
        rows.sort(key=lambda r: r[4], reverse=True)
        total = sum(r[4] for r in rows)
        m = META[period]
        reported = m["reported_total"]
        drift = (total - reported) / reported * 100
        flag = "OK" if abs(drift) <= 0.5 else "DRIFT!"
        if abs(drift) > 0.5:
            all_ok = False
        pdir = os.path.join(RAW, period)
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, "holdings.json"), "w", encoding="utf-8") as f:
            json.dump({"period": period, "holdings": rows}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(pdir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({
                "period": period, "filed": m["filed"], "form": "13F-HR",
                "accession": m["accession"], "total_value": reported,
                "summed_value": total, "num_holdings": len(rows), "source": SOURCE,
            }, f, ensure_ascii=False, indent=2)
        print(f"{period}: {len(rows):2d} holdings  summed {total:,}  "
              f"reported {reported:,}  drift {drift:+.3f}%  [{flag}]")
    print("ALL WITHIN TOLERANCE" if all_ok else "SOME PERIODS OUT OF TOLERANCE")


if __name__ == "__main__":
    main()
