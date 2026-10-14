"""Carrier directory: ocean carriers (SCAC, container owner prefixes, B/L prefixes) and airlines.

Used to detect the carrier from a reference (container owner prefix, B/L SCAC prefix,
AWB airline prefix) and to resolve a user-typed carrier name/code.
"""

from __future__ import annotations

from dataclasses import dataclass

from ff_tracking.domain.enums import TransportMode
from ff_tracking.domain.models import CarrierRef


@dataclass(frozen=True, slots=True)
class Carrier:
    code: str
    name: str
    name_ar: str
    mode: TransportMode
    scac: str | None = None
    container_prefixes: tuple[str, ...] = ()
    bl_prefixes: tuple[str, ...] = ()
    iata_code: str | None = None
    awb_prefix: str | None = None
    vessel_prefix: str | None = None

    def ref(self) -> CarrierRef:
        return CarrierRef(
            code=self.code,
            name=self.name,
            name_ar=self.name_ar,
            scac=self.scac,
            iata_code=self.iata_code,
            awb_prefix=self.awb_prefix,
        )


_SEA = TransportMode.SEA
_AIR = TransportMode.AIR

OCEAN_CARRIERS: tuple[Carrier, ...] = (
    Carrier("msc", "MSC Mediterranean Shipping Company", "إم إس سي", _SEA, "MSCU",
            ("MSCU", "MEDU", "MSDU", "MSMU"), ("MEDU", "MSCU"), vessel_prefix="MSC"),
    Carrier("maersk", "Maersk", "ميرسك", _SEA, "MAEU",
            ("MAEU", "MSKU", "MRKU", "MRSU", "MNBU", "SUDU"), ("MAEU", "SUDU"), vessel_prefix="MAERSK"),
    Carrier("cma_cgm", "CMA CGM", "سي إم إيه سي جي إم", _SEA, "CMDU",
            ("CMAU", "CGMU", "ECMU", "APZU", "APHU"), ("CMDU", "APLU"), vessel_prefix="CMA CGM"),
    Carrier("cosco", "COSCO Shipping Lines", "كوسكو للشحن", _SEA, "COSU",
            ("COSU", "CBHU", "CCLU", "CSNU"), ("COSU",), vessel_prefix="COSCO SHIPPING"),
    Carrier("hapag_lloyd", "Hapag-Lloyd", "هاباغ لويد", _SEA, "HLCU",
            ("HLXU", "HLCU", "HLBU", "UACU"), ("HLCU",), vessel_prefix="HL"),
    Carrier("evergreen", "Evergreen Line", "إيفرغرين", _SEA, "EGLV",
            ("EGLV", "EISU", "EMCU", "EGHU", "EGSU", "EITU"), ("EGLV",), vessel_prefix="EVER"),
    Carrier("one", "Ocean Network Express (ONE)", "أوشن نتورك إكسبريس (ONE)", _SEA, "ONEY",
            ("ONEU", "NYKU", "MOLU", "KKFU"), ("ONEY",), vessel_prefix="ONE"),
    Carrier("yang_ming", "Yang Ming", "يانغ مينغ", _SEA, "YMLU",
            ("YMLU", "YMMU"), ("YMLU",), vessel_prefix="YM"),
    Carrier("oocl", "OOCL", "أو أو سي إل", _SEA, "OOLU",
            ("OOLU", "OOCU"), ("OOLU",), vessel_prefix="OOCL"),
    Carrier("zim", "ZIM", "زيم", _SEA, "ZIMU",
            ("ZIMU", "ZCSU"), ("ZIMU",), vessel_prefix="ZIM"),
    Carrier("hmm", "HMM", "إتش إم إم", _SEA, "HDMU",
            ("HDMU", "HMMU"), ("HDMU",), vessel_prefix="HMM"),
    Carrier("pil", "Pacific International Lines (PIL)", "باسيفيك إنترناشيونال لاينز", _SEA, "PCIU",
            ("PCIU",), ("PCIU",), vessel_prefix="KOTA"),
    Carrier("wan_hai", "Wan Hai Lines", "وان هاي", _SEA, "WHLC",
            ("WHLU", "WHSU"), ("WHLC",), vessel_prefix="WAN HAI"),
    # Added in Phase 4 prep (best effort: verify owner codes against the BIC registry before relying on them)
    Carrier("sealand", "Sealand", "سيلاند", _SEA, "SEJJ", ("SEAU", "SEBU"), ("SEJJ",), vessel_prefix="SEALAND"),
    Carrier("anl", "ANL", "إيه إن إل", _SEA, "ANNU", ("ANNU", "ANLU"), ("ANNU",), vessel_prefix="ANL"),
    Carrier("matson", "Matson", "ماتسون", _SEA, "MATS", ("MATU",), ("MATS",), vessel_prefix="MATSON"),
    Carrier("rcl", "Regional Container Lines (RCL)", "ريجونال كونتينر لاينز", _SEA, "RCLU", ("RCLU",), ("RCLU",)),
    Carrier("sitc", "SITC Container Lines", "إس آي تي سي", _SEA, "SITC", ("SITU",), ("SITC",), vessel_prefix="SITC"),
    Carrier("kmtc", "KMTC", "كي إم تي سي", _SEA, "KMTU", ("KMTU",), ("KMTU",), vessel_prefix="KMTC"),
    Carrier("sm_line", "SM Line", "إس إم لاين", _SEA, "SMLM", ("SMLU",), ("SMLM",), vessel_prefix="SM"),
    Carrier("ts_lines", "T.S. Lines", "تي إس لاينز", _SEA, "TSLU", ("TSLU",), ("TSLU",)),
    Carrier("sinokor", "Sinokor", "سينوكور", _SEA, "SKLU", ("SKLU",), ("SKLU",), vessel_prefix="SINOKOR"),
    Carrier("heung_a", "Heung-A Line", "هيونغ آ", _SEA, "HASU", ("HASU",), ("HASU",), vessel_prefix="HEUNG-A"),
)

AIRLINES: tuple[Carrier, ...] = (
    Carrier("american_airlines", "American Airlines Cargo", "الخطوط الأمريكية للشحن", _AIR, iata_code="AA", awb_prefix="001"),
    Carrier("delta", "Delta Cargo", "دلتا للشحن", _AIR, iata_code="DL", awb_prefix="006"),
    Carrier("united", "United Cargo", "يونايتد للشحن", _AIR, iata_code="UA", awb_prefix="016"),
    Carrier("lufthansa", "Lufthansa Cargo", "لوفتهانزا للشحن", _AIR, iata_code="LH", awb_prefix="020"),
    Carrier("air_france", "Air France Cargo", "الخطوط الفرنسية للشحن", _AIR, iata_code="AF", awb_prefix="057"),
    Carrier("saudia", "Saudia Cargo", "السعودية للشحن", _AIR, iata_code="SV", awb_prefix="065"),
    Carrier("ethiopian", "Ethiopian Cargo", "الإثيوبية للشحن", _AIR, iata_code="ET", awb_prefix="071"),
    Carrier("gulf_air", "Gulf Air Cargo", "طيران الخليج للشحن", _AIR, iata_code="GF", awb_prefix="072"),
    Carrier("iraqi_airways", "Iraqi Airways", "الخطوط الجوية العراقية", _AIR, iata_code="IA", awb_prefix="073"),
    Carrier("klm", "KLM Cargo", "كيه إل إم للشحن", _AIR, iata_code="KL", awb_prefix="074"),
    Carrier("mea", "Middle East Airlines", "طيران الشرق الأوسط", _AIR, iata_code="ME", awb_prefix="076"),
    Carrier("egyptair", "EgyptAir Cargo", "مصر للطيران للشحن", _AIR, iata_code="MS", awb_prefix="077"),
    Carrier("china_cargo", "China Cargo Airlines", "الصين للشحن الجوي", _AIR, iata_code="CK", awb_prefix="112"),
    Carrier("british_airways", "IAG Cargo (British Airways)", "آي إيه جي للشحن (الخطوط البريطانية)", _AIR, iata_code="BA", awb_prefix="125"),
    Carrier("flydubai", "flydubai Cargo", "فلاي دبي للشحن", _AIR, iata_code="FZ", awb_prefix="141"),
    Carrier("qatar_airways", "Qatar Airways Cargo", "القطرية للشحن", _AIR, iata_code="QR", awb_prefix="157"),
    Carrier("cathay", "Cathay Cargo", "كاثي للشحن", _AIR, iata_code="CX", awb_prefix="160"),
    Carrier("cargolux", "Cargolux", "كارغولوكس", _AIR, iata_code="CV", awb_prefix="172"),
    Carrier("emirates", "Emirates SkyCargo", "الإمارات للشحن الجوي", _AIR, iata_code="EK", awb_prefix="176"),
    Carrier("korean_air", "Korean Air Cargo", "الكورية للشحن", _AIR, iata_code="KE", awb_prefix="180"),
    Carrier("kuwait_airways", "Kuwait Airways Cargo", "الخطوط الكويتية للشحن", _AIR, iata_code="KU", awb_prefix="229"),
    Carrier("turkish", "Turkish Cargo", "التركية للشحن", _AIR, iata_code="TK", awb_prefix="235"),
    Carrier("china_airlines", "China Airlines Cargo", "الخطوط الصينية (تايوان) للشحن", _AIR, iata_code="CI", awb_prefix="297"),
    Carrier("royal_jordanian", "Royal Jordanian Cargo", "الملكية الأردنية للشحن", _AIR, iata_code="RJ", awb_prefix="512"),
    Carrier("etihad", "Etihad Cargo", "الاتحاد للشحن", _AIR, iata_code="EY", awb_prefix="607"),
    Carrier("singapore_airlines", "Singapore Airlines Cargo", "السنغافورية للشحن", _AIR, iata_code="SQ", awb_prefix="618"),
    Carrier("eva_air", "EVA Air Cargo", "إيفا للشحن", _AIR, iata_code="BR", awb_prefix="695"),
    Carrier("xiamen_airlines", "Xiamen Airlines", "خطوط شيامن الجوية", _AIR, iata_code="MF", awb_prefix="731"),
    Carrier("china_eastern", "China Eastern Airlines", "الصين الشرقية للطيران", _AIR, iata_code="MU", awb_prefix="781"),
    Carrier("china_southern", "China Southern Cargo", "الصين الجنوبية للشحن", _AIR, iata_code="CZ", awb_prefix="784"),
    Carrier("sichuan_airlines", "Sichuan Airlines", "خطوط سيتشوان الجوية", _AIR, iata_code="3U", awb_prefix="876"),
    Carrier("hainan_airlines", "Hainan Airlines", "خطوط هاينان الجوية", _AIR, iata_code="HU", awb_prefix="880"),
    Carrier("oman_air", "Oman Air Cargo", "الطيران العُماني للشحن", _AIR, iata_code="WY", awb_prefix="910"),
    Carrier("air_china", "Air China Cargo", "طيران الصين للشحن", _AIR, iata_code="CA", awb_prefix="999"),
    Carrier("fedex", "FedEx Express", "فيديكس", _AIR, iata_code="FX", awb_prefix="023"),
    Carrier("ups", "UPS Airlines", "يو بي إس", _AIR, iata_code="5X", awb_prefix="406"),
    Carrier("air_india", "Air India Cargo", "طيران الهند للشحن", _AIR, iata_code="AI", awb_prefix="098"),
    Carrier("atlas_air", "Atlas Air", "أطلس إير", _AIR, iata_code="5Y", awb_prefix="369"),
    Carrier("jal", "Japan Airlines Cargo", "طيران اليابان للشحن", _AIR, iata_code="JL", awb_prefix="131"),
    Carrier("ana", "ANA Cargo", "إيه إن إيه للشحن", _AIR, iata_code="NH", awb_prefix="205"),
    Carrier("thai", "Thai Airways Cargo", "الخطوط التايلاندية للشحن", _AIR, iata_code="TG", awb_prefix="217"),
    Carrier("malaysia", "MASkargo", "ماس كارغو", _AIR, iata_code="MH", awb_prefix="232"),
    Carrier("air_canada", "Air Canada Cargo", "طيران كندا للشحن", _AIR, iata_code="AC", awb_prefix="014"),
    Carrier("pegasus", "Pegasus Cargo", "بيغاسوس للشحن", _AIR, iata_code="PC", awb_prefix="624"),
    Carrier("air_arabia", "Air Arabia Cargo", "العربية للطيران للشحن", _AIR, iata_code="G9", awb_prefix="514"),
    Carrier("aeroflot", "Aeroflot Cargo", "أيروفلوت للشحن", _AIR, iata_code="SU", awb_prefix="555"),
    Carrier("vietnam", "Vietnam Airlines Cargo", "الخطوط الفيتنامية للشحن", _AIR, iata_code="VN", awb_prefix="738"),
    Carrier("asiana", "Asiana Cargo", "آسيانا للشحن", _AIR, iata_code="OZ", awb_prefix="988"),
    Carrier("pia", "PIA Cargo", "الباكستانية للشحن", _AIR, iata_code="PK", awb_prefix="214"),
    Carrier("srilankan", "SriLankan Cargo", "السريلانكية للشحن", _AIR, iata_code="UL", awb_prefix="603"),
    Carrier("swiss", "Swiss WorldCargo", "سويس وورلد كارغو", _AIR, iata_code="LX", awb_prefix="724"),
    Carrier("virgin_atlantic", "Virgin Atlantic Cargo", "فيرجن أتلانتيك للشحن", _AIR, iata_code="VS", awb_prefix="932"),
    Carrier("iberia", "Iberia Cargo", "إيبيريا للشحن", _AIR, iata_code="IB", awb_prefix="075"),
    Carrier("tap", "TAP Air Portugal Cargo", "تاب البرتغالية للشحن", _AIR, iata_code="TP", awb_prefix="047"),
    Carrier("finnair", "Finnair Cargo", "فينير للشحن", _AIR, iata_code="AY", awb_prefix="105"),
    Carrier("qantas", "Qantas Freight", "كانتاس للشحن", _AIR, iata_code="QF", awb_prefix="081"),
    Carrier("kenya_airways", "Kenya Airways Cargo", "الكينية للشحن", _AIR, iata_code="KQ", awb_prefix="706"),
)

# Container owner codes of leasing companies: the container may sail with any carrier.
LEASING_OWNER_PREFIXES: frozenset[str] = frozenset(
    {"TGHU", "TCNU", "TCLU", "TRLU", "TEMU", "SEGU", "GESU", "CAIU", "FCIU", "FSCU", "BMOU", "CRSU"}
)

ALL_CARRIERS: tuple[Carrier, ...] = OCEAN_CARRIERS + AIRLINES

_BY_CODE = {c.code: c for c in ALL_CARRIERS}
_BY_CONTAINER_PREFIX = {p: c for c in OCEAN_CARRIERS for p in c.container_prefixes}
_BY_BL_PREFIX = {p: c for c in OCEAN_CARRIERS for p in (*c.bl_prefixes, *((c.scac,) if c.scac else ()))}
_BY_AWB_PREFIX = {c.awb_prefix: c for c in AIRLINES if c.awb_prefix}
_BY_IATA = {c.iata_code: c for c in AIRLINES if c.iata_code}
_BY_NAME = {c.name.casefold(): c for c in ALL_CARRIERS}


def carrier_by_code(code: str) -> Carrier | None:
    return _BY_CODE.get(code)


def carrier_for_container_owner(prefix: str) -> Carrier | None:
    """Carrier from the 4-letter owner code + category identifier (e.g. ``MSCU``)."""
    return _BY_CONTAINER_PREFIX.get(prefix.upper())


def carrier_for_bl_prefix(prefix: str) -> Carrier | None:
    return _BY_BL_PREFIX.get(prefix.upper())


def carrier_for_awb_prefix(prefix: str) -> Carrier | None:
    return _BY_AWB_PREFIX.get(prefix)


def is_leasing_owner(prefix: str) -> bool:
    return prefix.upper() in LEASING_OWNER_PREFIXES


def find_carrier(text: str | None, mode: TransportMode | None = None) -> Carrier | None:
    """Resolve a user-typed carrier: code, SCAC, B/L or container prefix, IATA code, AWB prefix or name."""
    if not text:
        return None
    raw = text.strip()
    key = raw.casefold().replace("-", "_").replace(" ", "_")
    upper = raw.upper()
    candidates = (
        _BY_CODE.get(key),
        _BY_BL_PREFIX.get(upper),
        _BY_CONTAINER_PREFIX.get(upper),
        _BY_IATA.get(upper),
        _BY_AWB_PREFIX.get(raw),
        _BY_NAME.get(raw.casefold()),
    )
    for carrier in candidates:
        if carrier is not None and (mode is None or carrier.mode is mode):
            return carrier
    return None
