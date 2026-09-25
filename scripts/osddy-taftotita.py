#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ταυτότητα αποφάσεων που κατεβαίνουν από τον ΟΣΔΔΥ.

Οι αποφάσεις κατεβαίνουν με όνομα που φέρει είδος, αριθμό και έτος χωρίς το
δικαστήριο (A2941-2026.odt), οπότε αποφάσεις διαφορετικών δικαστηρίων με τον
ίδιο αριθμό συμπίπτουν στο όνομα και ο φυλλομετρητής προσθέτει «(1)», «(2)».
Το δικαστήριο όμως υπάρχει πάντοτε μέσα στο κείμενο, στις πρώτες παραγράφους.

Το script διαβάζει κάθε .odt, βγάζει δικαστήριο, τμήμα, αριθμό, έτος,
δικαστή, γραμματέα και ημερομηνία δημοσίευσης, γράφει κατάλογο TSV και,
με --apply, μετονομάζει και τακτοποιεί σε φακέλους ανά δικαστήριο και έτος.

Χωρίς --apply δεν αγγίζει κανένα αρχείο. Δεν διαγράφει ποτέ τίποτε, ούτε τα
πραγματικά διπλότυπα, τα οποία απλώς επισημαίνει.

    python3 osddy-taftotita.py <φάκελος> [...] --tsv katalogos.tsv
    python3 osddy-taftotita.py <φάκελος> --apply --out <φάκελος προορισμού>
"""

import argparse
import hashlib
import html
import os
import re
import shutil
import sys
import unicodedata
import zipfile

# --------------------------------------------------------------------------
# Εξαγωγή κειμένου από .odt

def odt_paragraphs(path):
    """Οι παράγραφοι του .odt, χωρίς τις κενές."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    xml = re.sub(r"</text:(p|h)>", "\n", xml)
    xml = re.sub(r"<text:(line-break|tab)[^>]*/>", " ", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    text = html.unescape(xml)
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def odt_meta(path):
    """Τα meta:user-defined του .odt, όπου ο ΟΣΔΔΥ γράφει το OriginalFileName."""
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("meta.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        return out
    for m in re.finditer(
        r'<meta:user-defined meta:name="([^"]+)"[^>]*>([^<]*)</meta:user-defined>', xml
    ):
        out[m.group(1)] = html.unescape(m.group(2))
    return out


# --------------------------------------------------------------------------
# Κανονική μορφή ελληνικών, για συγκρίσεις

_LATIN_LOOKALIKE = str.maketrans(
    "ABEZHIKMNOPTXYabekoprtxy", "ΑΒΕΖΗΙΚΜΝΟΡΤΧΥαβεκορρτχγ"
)


def greek_fold(s):
    """Πεζά, χωρίς τόνους, με τα λατινικά ομοιόμορφα γράμματα διορθωμένα."""
    s = s.translate(_LATIN_LOOKALIKE)
    s = s.replace("΢", "Σ").replace("µ", "μ")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = unicodedata.normalize("NFC", s)
    return s.lower().replace("ς", "σ")


# --------------------------------------------------------------------------
# Αναγνώριση της ταυτότητας

RE_ARITHMOS = re.compile(
    r"αριθμ(?:ος|\.)?\s*(?:απο[φπ]ασ(?:ησ|εωσ))?\s*[:\.]?\s*"
    r"([Α-ΩA-Z]{0,3})\s*(\d{1,6})\s*/\s*(\d{4})"
)

RE_ETOS_MONO = re.compile(r"(\d{1,6})\s*/\s*(\d{4})")

KEYWORDS_DIKASTIRIO = (
    "δικαστηριο",
    "εφετειο",
    "πρωτοδικειο",
    "συμβουλιο τησ επικρατειασ",
    "ελεγκτικο συνεδριο",
)

RE_TMIMA = re.compile(r"^\s*(ΤΜΗΜΑ|ΤΜΉΜΑ)\b.*", re.IGNORECASE)

RE_DIMOSIEFSI = re.compile(
    r"δημοσιευ[θτ]ηκε.*?στι[σς]\s+(\d{1,2})\s+([Α-Ωα-ωΆ-Ώά-ώ]+)\s+(\d{4})"
)

RE_DIKASTIS = re.compile(
    r"με\s+δικαστ[ήη](?:ρια)?\s+(?:τη[νο]?|τον)\s+([Α-ΩΆΈΉΊΌΎΏ][^,\.]{2,60}?)\s+"
    r"(?:[ΕΈ]φ[έε]τη|Πρ[όο]εδρο|Πρωτοδ[ίι]κη|Π[άα]ρεδρο)"
)

RE_DIKASTIS_ANO = re.compile(
    r"^(?:Δικαστ[ήη]ς|Εισηγητ[ήη]ς|Πρ[όο]εδρος)\s*[:\-]\s*(.+)$"
)

RE_YPOGRAFI = re.compile(
    r"^(?:Η|Ο|ΟΙ)\s+(?:ΔΙΚΑΣΤ|ΠΡΟΕΔΡ|ΕΙΣΗΓΗΤ)", re.IGNORECASE
)

MINES = {
    "ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4,
    "μαιου": 5, "ιουνιου": 6, "ιουλιου": 7, "αυγουστου": 8,
    "σεπτεμβριου": 9, "οκτωβριου": 10, "νοεμβριου": 11, "δεκεμβριου": 12,
}

# Συντομογραφίες δικαστηρίων, κατά τον καθιερωμένο τρόπο παράθεσης.
SYNTOMOGRAFIES = (
    ("διοικητικο εφετειο", "ΔΕφ"),
    ("διοικητικο πρωτοδικειο", "ΔΠρ"),
    ("συμβουλιο τησ επικρατειασ", "ΣτΕ"),
    ("ελεγκτικο συνεδριο", "ΕλΣυν"),
    ("εφετειο", "Εφ"),
    ("πρωτοδικειο", "ΠρΠ"),
)


def _is_upperish(line):
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 4:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) > 0.8


def find_dikastirio(paras):
    """Το δικαστήριο και το τμήμα, από τις πρώτες παραγράφους."""
    dikastirio = ""
    tmima = ""
    for i, ln in enumerate(paras[:12]):
        f = greek_fold(ln)
        if not dikastirio and _is_upperish(ln):
            if any(k in f for k in KEYWORDS_DIKASTIRIO):
                dikastirio = re.sub(r"\s+", " ", ln).strip(" .,")
                # Το τμήμα ακολουθεί συνήθως αμέσως μετά.
                for nxt in paras[i + 1 : i + 4]:
                    if RE_TMIMA.match(nxt):
                        tmima = re.sub(r"\s+", " ", nxt).strip(" .,")
                        break
                break
    if not tmima:
        for ln in paras[:12]:
            if RE_TMIMA.match(ln):
                tmima = re.sub(r"\s+", " ", ln).strip(" .,")
                break
    return dikastirio, tmima


def find_arithmos(paras, fallback_name=""):
    """Αριθμός και έτος, από τις πρώτες παραγράφους ή από το όνομα."""
    for ln in paras[:12]:
        m = RE_ARITHMOS.search(greek_fold(ln))
        if m:
            return m.group(2), m.group(3)
    m = RE_ETOS_MONO.search(fallback_name)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"[Α-ΩA-Z]*?(\d{1,6})-(\d{4})", os.path.basename(fallback_name))
    if m:
        return m.group(1), m.group(2)
    return "", ""


def find_dimosiefsi(paras):
    for ln in reversed(paras):
        m = RE_DIMOSIEFSI.search(greek_fold(ln))
        if m:
            mina = MINES.get(m.group(2))
            if mina:
                return "%04d-%02d-%02d" % (int(m.group(3)), mina, int(m.group(1)))
    return ""


def find_dikastis(paras):
    """Ο δικαστής, από το προοίμιο, από ρητή ένδειξη ή από την υπογραφή."""
    for ln in paras[:14]:
        m = RE_DIKASTIS.search(ln)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" .,")
    for ln in paras[:14]:
        m = RE_DIKASTIS_ANO.match(ln)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" .,")
    # Το μπλοκ υπογραφών στο τέλος, όπου η επόμενη γραμμή φέρει τα ονόματα.
    for i, ln in enumerate(paras[-6:], max(0, len(paras) - 6)):
        if RE_YPOGRAFI.match(ln) and i + 1 < len(paras):
            onomata = re.sub(r"\s{2,}", " | ", paras[i + 1]).strip()
            if onomata and _is_upperish(onomata):
                return onomata.split(" | ")[0].strip()
    return ""


# Οι πόλεις κατά τον καθιερωμένο τρόπο παράθεσης (ΔΕφΑθ, ΔΠρΠειρ κ.ο.κ.).
POLEIS = {
    "αθηνων": "Αθ", "πειραιωσ": "Πειρ", "πειραια": "Πειρ",
    "θεσσαλονικησ": "Θεσ", "πατρων": "Πατρ", "λαρισασ": "Λαρ",
    "λαρισησ": "Λαρ", "ιωαννινων": "Ιωαν", "κομοτηνησ": "Κομ",
    "τριπολησ": "Τριπ", "χανιων": "Χαν", "ηρακλειου": "Ηρακλ",
    "κερκυρασ": "Κερκ", "μυτιληνησ": "Μυτ", "ροδου": "Ροδ",
    "συρου": "Συρ", "βολου": "Βολ", "σερρων": "Σερ", "καβαλασ": "Καβ",
    "αλεξανδρουπολησ": "Αλεξ", "ναυπλιου": "Ναυπλ", "λαμιασ": "Λαμ",
    "μεσολογγιου": "Μεσολ", "αγρινιου": "Αγριν", "καλαματασ": "Καλαμ",
    "κορινθου": "Κορ", "λιβαδειασ": "Λιβ", "κοζανησ": "Κοζ",
    "βεροιασ": "Βερ", "δραμασ": "Δραμ", "ξανθησ": "Ξανθ",
    "χαλκιδασ": "Χαλκ", "πυργου": "Πυργ", "τρικαλων": "Τρικ",
    "καρδιτσασ": "Καρδ", "καστοριασ": "Καστ", "φλωρινασ": "Φλωρ",
    "γρεβενων": "Γρεβ", "πρεβεζασ": "Πρεβ", "αρτασ": "Αρτ",
    "ηγουμενιτσασ": "Ηγουμ", "ρεθυμνου": "Ρεθ", "λασιθιου": "Λασ",
    "χιου": "Χιου", "σαμου": "Σαμ",
}


def syntomografia(dikastirio):
    """ΔΕφΑθ, ΔΠρΠειρ κ.ο.κ. Όπου η πόλη δεν είναι γνωστή, μένει ολόκληρη."""
    f = greek_fold(dikastirio)
    for key, short in SYNTOMOGRAFIES:
        idx = f.find(key)
        if idx < 0:
            continue
        poli_raw = dikastirio[idx + len(key):].strip(" .,")
        poli_raw = re.sub(r"\s+", " ", poli_raw)
        if not poli_raw:
            return short
        poli = POLEIS.get(greek_fold(poli_raw))
        if not poli:
            poli = poli_raw.title().replace(" ", "")
        return short + poli
    return re.sub(r"[^\w]+", "", dikastirio)[:20] or "Αγνωστο"


def eidos_apo_onoma(name):
    m = re.match(r"([Α-ΩA-Z]+)\d", os.path.basename(name))
    return m.group(1) if m else ""


# --------------------------------------------------------------------------

def keimeno_hash(paras):
    """Αποτύπωμα του κειμένου, αγνοώντας κενά, στίξη και κεφαλαία."""
    s = greek_fold(" ".join(paras))
    s = re.sub(r"[^\w]+", "", s)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def analyse(path):
    try:
        paras = odt_paragraphs(path)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        return {"path": path, "sfalma": str(exc)}
    meta = odt_meta(path)
    onoma = meta.get("OriginalFileName") or os.path.basename(path)
    dikastirio, tmima = find_dikastirio(paras)
    arithmos, etos = find_arithmos(paras, onoma)
    return {
        "path": path,
        "onoma": os.path.basename(path),
        "onoma_osddy": onoma,
        "eidos": eidos_apo_onoma(onoma),
        "dikastirio": dikastirio,
        "tmima": tmima,
        "arithmos": arithmos,
        "etos": etos,
        "dikastis": find_dikastis(paras),
        "dimosiefsi": find_dimosiefsi(paras),
        "hash": keimeno_hash(paras),
        "paragrafoi": str(len(paras)),
        "sfalma": "",
    }


STILES = (
    "dikastirio", "tmima", "eidos", "arithmos", "etos", "dimosiefsi",
    "dikastis", "onoma_osddy", "paragrafoi", "hash", "path", "sfalma",
)


def neo_onoma(rec):
    short = syntomografia(rec["dikastirio"]) if rec["dikastirio"] else "Αγνωστο"
    eidos = rec["eidos"] or "A"
    base = "%s %s%s-%s" % (short, eidos, rec["arithmos"], rec["etos"])
    return re.sub(r"[\\/:*?\"<>|]", "_", base) + ".odt"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folders", nargs="+", help="φάκελοι με αποφάσεις .odt")
    ap.add_argument("--tsv", help="αρχείο καταλόγου (προεπιλογή: στην οθόνη)")
    ap.add_argument("--apply", action="store_true",
                    help="μετονομασία και τακτοποίηση, αλλιώς μόνο δοκιμή")
    ap.add_argument("--out", help="φάκελος προορισμού για --apply")
    ap.add_argument("--move", action="store_true",
                    help="μετακίνηση αντί για αντιγραφή")
    args = ap.parse_args(argv)

    if args.apply and not args.out:
        ap.error("το --apply απαιτεί --out")

    recs = []
    for folder in args.folders:
        for root, _dirs, files in os.walk(folder):
            for fn in sorted(files):
                if fn.lower().endswith(".odt"):
                    recs.append(analyse(os.path.join(root, fn)))

    # Ομάδες με το ίδιο κείμενο, δηλαδή γνήσια διπλότυπα.
    ana_hash = {}
    for r in recs:
        if not r.get("sfalma"):
            ana_hash.setdefault(r["hash"], []).append(r)
    diplotypa = {h: g for h, g in ana_hash.items() if len(g) > 1}

    # Ομάδες με τον ίδιο αριθμό αλλά διαφορετικό κείμενο, δηλαδή συμπτώσεις.
    ana_arithmo = {}
    for r in recs:
        if not r.get("sfalma") and r["arithmos"]:
            ana_arithmo.setdefault((r["eidos"], r["arithmos"], r["etos"]), []).append(r)
    symptoseis = {
        k: g for k, g in ana_arithmo.items()
        if len(g) > 1 and len({x["hash"] for x in g}) > 1
    }

    lines = ["\t".join(STILES)]
    for r in sorted(recs, key=lambda x: (x.get("dikastirio", ""),
                                         x.get("etos", ""),
                                         int(x["arithmos"]) if x.get("arithmos", "").isdigit() else 0)):
        lines.append("\t".join((r.get(c, "") or "") for c in STILES))
    out = "\n".join(lines) + "\n"
    if args.tsv:
        with open(args.tsv, "w", encoding="utf-8") as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)

    sfalmata = [r for r in recs if r.get("sfalma")]
    axoris = [r for r in recs if not r.get("sfalma") and not r["dikastirio"]]

    sys.stderr.write("\nΑρχεία: %d\n" % len(recs))
    sys.stderr.write("Με δικαστήριο από το κείμενο: %d\n" % (len(recs) - len(axoris) - len(sfalmata)))
    sys.stderr.write("Χωρίς αναγνωρισμένο δικαστήριο: %d\n" % len(axoris))
    sys.stderr.write("Σφάλματα ανάγνωσης: %d\n" % len(sfalmata))
    sys.stderr.write("Γνήσια διπλότυπα (ίδιο κείμενο): %d ομάδες\n" % len(diplotypa))
    sys.stderr.write("Συμπτώσεις αριθμού (διαφορετικό κείμενο): %d ομάδες\n" % len(symptoseis))
    for k, g in sorted(symptoseis.items()):
        sys.stderr.write("  %s%s/%s -> %s\n" % (
            k[0], k[1], k[2],
            " | ".join("%s [%s]" % (x["onoma"], x["dikastirio"] or "άγνωστο") for x in g)))

    if not args.apply:
        sys.stderr.write("\nΔοκιμή μόνο. Κανένα αρχείο δεν άλλαξε. Με --apply --out <φάκελος> τακτοποιούνται.\n")
        return 0

    egrapsan = 0
    for r in recs:
        if r.get("sfalma"):
            continue
        klados = os.path.join(args.out,
                              syntomografia(r["dikastirio"]) if r["dikastirio"] else "Αγνωστο δικαστηριο",
                              r["etos"] or "χωρίς έτος")
        os.makedirs(klados, exist_ok=True)
        stoxos = os.path.join(klados, neo_onoma(r))
        n = 1
        while os.path.exists(stoxos):
            # Ποτέ δεν γράφουμε πάνω σε υπάρχον αρχείο.
            riza, ext = os.path.splitext(neo_onoma(r))
            stoxos = os.path.join(klados, "%s (%d)%s" % (riza, n, ext))
            n += 1
        (shutil.move if args.move else shutil.copy2)(r["path"], stoxos)
        egrapsan += 1
    sys.stderr.write("\nΤακτοποιήθηκαν %d αρχεία στο %s\n" % (egrapsan, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
