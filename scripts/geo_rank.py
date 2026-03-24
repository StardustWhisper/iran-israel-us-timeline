#!/usr/bin/env python3
"""Rank geo/econ items from merged RSS list.

Heuristic scoring; no external deps.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Keyword weights
CORE_KW = [
    (r"战争|冲突|军事|袭击|停火|导弹|无人机|核|武装|政变|边境", 4.0),
    (r"制裁|关税|贸易|出口管制|禁令|限制|反制|WTO", 3.5),
    (r"油价|原油|天然气|能源|OPEC|电力|电网|LNG", 3.0),
    (r"通胀|CPI|PPI|利率|加息|降息|汇率|货币政策|央行", 3.0),
    (r"国债|债券|财政|预算|赤字|税收|债务上限", 2.5),
    (r"供应链|航运|港口|物流|运费|红海|巴拿马运河|苏伊士", 2.5),
    (r"关停|减产|罢工|停工|裁员|破产|重组|并购", 2.0),
    (r"粮食|小麦|玉米|大豆|化肥|稀土|关键矿产|锂|钴|镍", 2.0),
    (r"地缘政治|大国博弈|盟友|北约|印太|中东|欧洲|亚太", 2.0),
]
EN_KW = [
    (r"war|conflict|missile|nuclear|ceasefire|drone", 3.5),
    (r"sanction|tariff|export control|ban", 3.0),
    (r"oil|crude|gas|energy|opec|lng", 2.5),
    (r"inflation|cpi|ppi|interest rate|central bank|fx", 2.5),
    (r"debt|bond|fiscal|budget|deficit", 2.0),
    (r"supply chain|shipping|port|freight|red sea|suez|panama", 2.0),
    (r"strike|shutdown|bankrupt|merger|acquisition", 1.5),
    (r"grain|wheat|corn|soy|fertilizer|rare earth|lithium|cobalt|nickel", 1.5),
]

# Per-language boosts (geo + macro + energy)
LANG_KW = {
    "ES": [
        (r"guerra|conflicto|misil|nuclear|alto el fuego", 3.2),
        (r"sanci[oó]n|arancel|comercio|control de exportaci[oó]n", 3.0),
        (r"petr[oó]leo|crudo|gas|energ[ií]a|opep|lng", 2.6),
        (r"inflaci[oó]n|ipc|tasa de inter[eé]s|banco central", 2.5),
        (r"deuda|bono|fiscal|presupuesto|d[eé]ficit", 2.0),
        (r"cadena de suministro|env[ií]o|puerto|flete|mar rojo|suez|panam[aá]", 2.0),
    ],
    "AR": [
        (r"حرب|نزاع|صراع|هدنة|صواريخ|نووي", 3.2),
        (r"عقوبات|تعرفة|تجارة|حظر|قيود التصدير", 3.0),
        (r"نفط|خام|غاز|طاقة|أوبك|الغاز المسال", 2.6),
        (r"تضخم|أسعار الفائدة|البنك المركزي|سعر الصرف", 2.5),
        (r"ديون|سندات|عجز|ميزانية", 2.0),
        (r"سلسلة التوريد|شحن|ميناء|بحر الأحمر|قناة السويس", 2.0),
    ],
    "RU": [
        (r"войн|конфликт|ракет|ядерн|перемири|дрон", 3.2),
        (r"санкц|пошлин|торгов|контрол[ья] экспорта|запрет", 3.0),
        (r"нефт|сырь|газ|энерг|ОПЕК|СПГ", 2.6),
        (r"инфляц|ставк|центробанк|курс валют", 2.5),
        (r"долг|облигац|бюджет|дефицит", 2.0),
        (r"цепочк.*постав|судоход|порт|красное море|суэц", 2.0),
    ],
    "FR": [
        (r"guerre|conflit|missile|nucl[eé]aire|cessez-le-feu|drone", 3.2),
        (r"sanction|tarif|commerce|contr[oô]le des exportations|interdiction", 3.0),
        (r"p[eé]trole|brut|gaz|[eé]nergie|opep|gnl", 2.6),
        (r"inflation|taux d'int[eé]r[eê]t|banque centrale|cpi", 2.5),
        (r"dette|obligation|budget|d[eé]ficit", 2.0),
        (r"cha[iî]ne d'approvisionnement|exp[eé]dition|port|mer rouge|suez", 2.0),
    ],
    "DE": [
        (r"krieg|konflikt|rakete|nuklear|waffenstillstand|drohne", 3.2),
        (r"sanktion|zoll|handel|exportkontrolle|verbot", 3.0),
        (r"[oö]l|erd[oö]l|gas|energie|opec|lng", 2.6),
        (r"inflation|zins|zentralbank|leitzins|wechselkurs", 2.5),
        (r"schuld|anleihe|haushalt|defizit", 2.0),
        (r"lieferkett|schifffahrt|hafen|rotes meer|suez", 2.0),
    ],
    "JA": [
        (r"戦争|紛争|衝突|停戦|ミサイル|核|ドローン", 3.2),
        (r"制裁|関税|貿易|輸出管理|禁止", 3.0),
        (r"原油|石油|ガス|エネルギー|OPEC|LNG", 2.6),
        (r"インフレ|物価|金利|中央銀行|為替", 2.5),
        (r"国債|債券|財政|予算|赤字", 2.0),
        (r"供給網|サプライチェーン|海運|港|紅海|スエズ", 2.0),
    ],
    "PT": [
        (r"guerra|conflito|m[ií]ssil|nuclear|cessar-fogo|drone", 3.2),
        (r"san[cç][aã]o|tarifa|com[eé]rcio|controle de exporta[cç][aã]o|banimento", 3.0),
        (r"petr[oó]leo|cru|g[aá]s|energia|opep|gnl", 2.6),
        (r"infla[cç][aã]o|cpi|juros|banco central|c[aâ]mbio", 2.5),
        (r"d[ií]vida|t[ií]tulo|fiscal|or[cç]amento|d[eé]ficit", 2.0),
        (r"cadeia de suprimentos|transporte mar[ií]timo|porto|frete|mar vermelho|suez", 2.0),
    ],
    "IT": [
        (r"guerra|conflitto|missile|nucleare|cessate il fuoco|drone", 3.2),
        (r"sanzion|tariffa|commercio|controllo export|divieto", 3.0),
        (r"petrolio|greggio|gas|energia|opep|gnl", 2.6),
        (r"inflazione|tasso|banca centrale|cambio", 2.5),
        (r"debito|obbligazion|bilancio|deficit", 2.0),
        (r"catena di approvvigionamento|spedizion|porto|mar rosso|suez", 2.0),
    ],
    "KO": [
        (r"전쟁|분쟁|충돌|휴전|미사일|핵|드론", 3.2),
        (r"제재|관세|무역|수출 통제|금지", 3.0),
        (r"석유|원유|가스|에너지|OPEC|LNG", 2.6),
        (r"인플레이션|물가|금리|중앙은행|환율", 2.5),
        (r"국채|채권|재정|예산|적자", 2.0),
        (r"공급망|해운|운송|항만|홍해|수에즈", 2.0),
    ],
    "TR": [
        (r"savaş|çatışma|füze|nükleer|ateşkes|drone", 3.2),
        (r"yaptırım|tarife|ticaret|ihracat kontrol|yasak", 3.0),
        (r"petrol|ham petrol|gaz|enerji|opek|lng", 2.6),
        (r"enflasyon|faiz|merkez bankası|döviz", 2.5),
        (r"borç|tahvil|bütçe|açık", 2.0),
        (r"tedarik zinciri|deniz taşımacılığı|liman|navlun|kızıldeniz|süveyş", 2.0),
    ],
    "FA": [
        (r"جنگ|درگیری|موشک|هسته|آتش بس|پهپاد", 3.2),
        (r"تحریم|تعرفه|تجارت|کنترل صادرات|ممنوع", 3.0),
        (r"نفت|نفت خام|گاز|انرژی|اوپک|ال ان جی", 2.6),
        (r"تورم|نرخ بهره|بانک مرکزی|ارز", 2.5),
        (r"بدهی|اوراق|بودجه|کسری", 2.0),
        (r"زنجیره تأمین|زنجیره تامین|کشتیرانی|بندر|دریای سرخ|سوئز", 2.0),
    ],
}

# Penalty keywords (sports/celebrity/promo etc.) across languages
PENALTY = [
    (r"娱乐|明星|体育|足球|电影|综艺", 2.0),
    (r"测评|优惠|折扣|促销|发布会直播", 1.5),
    (r"sport|sports|football|soccer|nba|tennis|match|celebrity|movie|music|entertainment", 1.6),
    (r"promo|promotion|discount|coupon|sale", 1.2),
    (r"deportes|f[uú]tbol|celebridad|entretenimiento|cine|m[uú]sica", 1.6),
    (r"promoci[oó]n|descuento|oferta", 1.2),
    (r"sport|football|c[eé]l[eé]brit[eé]|divertissement|cin[eé]ma|musique", 1.6),
    (r"promotion|r[eé]duction|soldes", 1.2),
    (r"sport|fu[ßs]ball|promi|unterhaltung|kino|musik", 1.6),
    (r"angebot|rabatt|sale", 1.2),
    (r"スポーツ|サッカー|芸能|有名人|映画|音楽", 1.6),
    (r"セール|割引|キャンペーン", 1.2),
    (r"спорт|футбол|звезд|шоу|кино|музык", 1.6),
    (r"скидк|распродаж|акци", 1.2),
    (r"رياض|كرة القدم|مشاهير|ترفيه|سينما|موسيقى", 1.6),
    (r"خصم|تخفيض|عرض", 1.2),
    (r"esporte|futebol|celebridade|entretenimento|cinema|m[uú]sica", 1.6),
    (r"promo[cç][aã]o|desconto|oferta", 1.2),
    (r"sport|calcio|celebr|intrattenimento|cinema|musica", 1.6),
    (r"promozione|sconto|offerta", 1.2),
    (r"스포츠|축구|연예|유명인|영화|음악", 1.6),
    (r"할인|프로모션|세일", 1.2),
    (r"spor|futbol|[üu]nl[üu]|magazin|e[gğ]lence|sinema|m[üu]zik", 1.6),
    (r"indirim|kampanya", 1.2),
    (r"ورزش|فوتبال|سلبریتی|مشهور|سرگرمی|سینما|موسیقی", 1.6),
    (r"تخفیف|حراج|پروموشن", 1.2),
]

LANG_SOURCES = {
    "FR": ["lemonde", "france24-fr"],
    "DE": ["tagesschau", "zdf-nachrichten", "spiegel"],
    "JA": ["nhk", "asahi"],
    "ES": ["elpais", "bbc-mundo", "france24-es"],
    "AR": ["bbc-arabic", "dw-arabic", "france24-ar", "aljazeera-ar"],
    "RU": ["bbc-russian", "dw-russian"],
    "PT": ["uol-noticias", "g1-mundo"],
    "IT": ["ansa-mondo", "repubblica-esteri"],
    "KO": ["yna", "koreaherald"],
    "TR": ["aa-dunya", "hurriyet-dunya"],
    "FA": ["bbc-persian"],
}

STOPWORDS = {
    "the","a","an","and","or","for","to","of","in","on","with","from","into","is","are",
    "的","了","和","与","及","或","在","是","把","对","中","后","上","下","这","那","一个","一种",
}


def normalize_title(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def detect_lang(source_blog: str) -> str:
    sb = (source_blog or "").lower()
    for lang, keys in LANG_SOURCES.items():
        for k in keys:
            if k in sb:
                return lang
    return "EN"


def base_score(title: str, lang: str) -> float:
    s = 0.0
    # Chinese core signals (rare in this pipeline but safe)
    for pat, w in CORE_KW:
        if re.search(pat, title, re.I):
            s += w
    if lang == "EN":
        for pat, w in EN_KW:
            if re.search(pat, title, re.I):
                s += w
    else:
        for pat, w in LANG_KW.get(lang, []):
            if re.search(pat, title, re.I):
                s += w
    for pat, w in PENALTY:
        if re.search(pat, title, re.I):
            s -= w
    if len(title) > 60:
        s -= (len(title) - 60) * 0.01
    return s


def tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9\-\.]{1,}", text)
    return {p for p in parts if p not in STOPWORDS}


def dedup(items: list[dict]) -> list[dict]:
    seen_urls = set()
    out = []
    for it in items:
        url = (it.get("url") or "").strip()
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(it)
    # Title-based fuzzy dedup
    deduped = []
    seen_titles = []
    for it in out:
        title = normalize_title(it.get("title") or "")
        toks = tokenize(title)
        is_dup = False
        for old_title, old_toks in seen_titles:
            if not toks or not old_toks:
                continue
            overlap = len(toks & old_toks) / max(1, len(toks | old_toks))
            if overlap >= 0.6:
                is_dup = True
                break
        if not is_dup:
            deduped.append(it)
            seen_titles.append((title, toks))
    return deduped


def rank_items(items: list[dict]) -> list[dict]:
    for it in items:
        title = normalize_title(it.get("title") or "")
        lang = detect_lang(it.get("sourceBlog") or "")
        s = base_score(title, lang)
        it["score"] = round(float(s), 3)
    return sorted(items, key=lambda x: x.get("score", 0), reverse=True)


def _item_key(it: dict) -> str:
    return (it.get("url") or "") + "|" + (it.get("title") or "")


def diversify_topN(
    ranked: list[dict],
    top: int,
    min_score: float = 0.8,
    min_non_en_langs: int = 3,
    max_per_lang: int = 6,
) -> list[dict]:
    if top <= 0:
        return []
    picked: list[dict] = []
    picked_keys: set[str] = set()
    counts: dict[str, int] = defaultdict(int)

    # Ensure a few non-EN languages are represented if available
    best_by_lang: dict[str, dict] = {}
    for it in ranked:
        if it.get("score", 0) < min_score:
            continue
        lang = detect_lang(it.get("sourceBlog") or "")
        if lang == "EN":
            continue
        if lang not in best_by_lang:
            best_by_lang[lang] = it
    target = min(min_non_en_langs, len(best_by_lang))
    for _, it in sorted(best_by_lang.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)[:target]:
        k = _item_key(it)
        if k in picked_keys:
            continue
        picked.append(it)
        picked_keys.add(k)
        counts[detect_lang(it.get("sourceBlog") or "")] += 1

    # Pass 1: fill with cap to avoid dominance
    for it in ranked:
        if len(picked) >= top:
            break
        k = _item_key(it)
        if k in picked_keys:
            continue
        lang = detect_lang(it.get("sourceBlog") or "")
        if counts[lang] >= max_per_lang:
            continue
        picked.append(it)
        picked_keys.add(k)
        counts[lang] += 1

    # Pass 2: if still short, relax caps
    if len(picked) < top:
        for it in ranked:
            if len(picked) >= top:
                break
            k = _item_key(it)
            if k in picked_keys:
                continue
            picked.append(it)
            picked_keys.add(k)
    return picked


def _sanity_check() -> None:
    """Quick sanity: ensure diversity selector pulls non-EN when available."""
    items = [
        {"title": "War in region", "url": "u1", "sourceBlog": "bbc-world", "score": 3.0},
        {"title": "Guerra y sanciones", "url": "u2", "sourceBlog": "elpais-internacional", "score": 3.0},
        {"title": "تحريم جديد", "url": "u3", "sourceBlog": "bbc-arabic", "score": 2.8},
        {"title": "Krieg und Energie", "url": "u4", "sourceBlog": "tagesschau", "score": 2.7},
        {"title": "Sports update", "url": "u5", "sourceBlog": "bbc-world", "score": 1.0},
    ]
    top = diversify_topN(items, top=4, min_score=1.0)
    langs = {detect_lang(it.get("sourceBlog") or "") for it in top}
    assert len([l for l in langs if l != "EN"]) >= 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    items = list(data.get("items") or [])
    items = [it for it in items if it.get("title") and it.get("url")]
    items = dedup(items)
    ranked = rank_items(items)

    top = diversify_topN(ranked, max(1, args.top))
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(ranked),
        "top": top[0] if top else None,
        "topN": top,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if os.environ.get("GEO_RANK_SANITY") == "1":
        _sanity_check()
    main()
