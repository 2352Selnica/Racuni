# parser.py
# -*- coding: utf-8 -*-
"""
Parsanje eRačuna (eSLOG 2.0), prevzemnice (XML) in naročilnice (TXT)
ter primerjava postavk.
"""

import xml.etree.ElementTree as ET
import re

# ---------------------------------------------------------------------------
# Pomožne funkcije
# ---------------------------------------------------------------------------
def _f(vrednost, privzeto=0.0):
    """Varno pretvori niz v float (podpira vejico in piko)."""
    if vrednost is None:
        return privzeto
    vrednost = str(vrednost).strip().replace('.', '').replace(',', '.') \
        if ',' in str(vrednost) and '.' in str(vrednost) else str(vrednost).strip().replace(',', '.')
    try:
        return float(vrednost)
    except ValueError:
        return privzeto


def normaliziraj_naziv(n):
    n = (n or '').lower()
    n = re.sub(r'[^a-z0-9]+', ' ', n)
    return ' '.join(n.split())


# ---------------------------------------------------------------------------
# 1. eRačun (eSLOG 2.0)
# ---------------------------------------------------------------------------
def preberi_eracun(stream):
    ns = {'eslog': 'urn:eslog:2.00'}
    tree = ET.parse(stream)
    root = tree.getroot()

    postavke = {}
    for sg26 in root.findall('.//eslog:G_SG26', ns):
        sifra_sa = sifra_in = ''
        for pia in sg26.findall('eslog:S_PIA', ns):
            c212 = pia.find('eslog:C_C212', ns)
            if c212 is None:
                continue
            vrednost = c212.findtext('eslog:D_7140', default='', namespaces=ns)
            tip = c212.findtext('eslog:D_7143', default='', namespaces=ns)
            if tip == 'SA':
                sifra_sa = vrednost
            elif tip == 'IN':
                sifra_in = vrednost

        naziv = ''
        imd = sg26.find('eslog:S_IMD', ns)
        if imd is not None:
            naziv = imd.findtext('eslog:C_C273/eslog:D_7008', default='', namespaces=ns)

        kolicina = 0.0
        qty = sg26.find('eslog:S_QTY/eslog:C_C186', ns)
        if qty is not None:
            kolicina = _f(qty.findtext('eslog:D_6060', default='0', namespaces=ns))

        cena_brez = cena_z = 0.0
        for pri in sg26.findall('eslog:G_SG29/eslog:S_PRI/eslog:C_C509', ns):
            tip = pri.findtext('eslog:D_5125', default='', namespaces=ns)
            vred = _f(pri.findtext('eslog:D_5118', default='0', namespaces=ns))
            if tip == 'AAA':
                cena_brez = vred
            elif tip == 'AAB':
                cena_z = vred

        popust = 0.0
        pcd = sg26.find('.//eslog:G_SG39/eslog:G_SG41/eslog:S_PCD/eslog:C_C501', ns)
        if pcd is not None:
            popust = _f(pcd.findtext('eslog:D_5482', default='0', namespaces=ns))

        ddv = 0.0
        tax = sg26.find('.//eslog:G_SG34/eslog:S_TAX/eslog:C_C243', ns)
        if tax is not None:
            ddv = _f(tax.findtext('eslog:D_5278', default='0', namespaces=ns))

        znesek_brez = znesek_z = 0.0
        for moa in sg26.findall('eslog:G_SG27/eslog:S_MOA/eslog:C_C516', ns):
            tip = moa.findtext('eslog:D_5025', default='', namespaces=ns)
            vred = _f(moa.findtext('eslog:D_5004', default='0', namespaces=ns))
            if tip == '203':
                znesek_brez = vred
            elif tip == '38':
                znesek_z = vred

        kljuc = sifra_in or sifra_sa or naziv
        postavke[kljuc] = {
            'sifra_sa': sifra_sa,
            'sifra_in': sifra_in,
            'naziv': naziv,
            'kolicina': kolicina,
            'cena_brez': cena_brez,
            'cena_z': cena_z,
            'popust': popust,
            'ddv': ddv,
            'znesek_brez': znesek_brez,
            'znesek_z': znesek_z,
        }
    return postavke


# ---------------------------------------------------------------------------
# 2. Prevzemnica (XML iz IS)
# ---------------------------------------------------------------------------
def preberi_prevzemnico(stream):
    tree = ET.parse(stream)
    root = tree.getroot()

    postavke = {}
    for post in root.findall('.//CG$G_POST'):
        sifra = post.findtext('ART_S_ARTIKLA', default='').strip()
        postavke[sifra] = {
            'sifra': sifra,
            'naziv': post.findtext('ART_N_ARTIKLA', default='').strip(),
            'kolicina': _f(post.findtext('POST_KOLICINA', default='0')),
            'cena_brez': _f(post.findtext('CF_CENA_BREZ_DDV', default='0')),
            'cena_z': _f(post.findtext('CF_CENA_Z_DDV', default='0')),
            'popust': _f(post.findtext('RABAT_DOB', default='0')),
            'ddv': _f(post.findtext('POST_O_PDAVKA', default='0')),
            'znesek_brez': _f(post.findtext('POST_VR_BREZ_DDV', default='0')),
            'znesek_z': _f(post.findtext('POST_VR_Z_DDV', default='0')),
        }
    return postavke


# ---------------------------------------------------------------------------
# 3. Naročilnica (TXT)
# ---------------------------------------------------------------------------
def preberi_narocilnico(stream):
    postavke = {}
    vsebina = stream.read()
    if isinstance(vsebina, bytes):
        vsebina = vsebina.decode('utf-8', errors='replace')

    for vrstica in vsebina.splitlines():
        if not vrstica.strip():
            continue
        m = re.match(
            r'^\s*\d+\s+([0-9A-Za-z]+)\s+(.+?)\s+(\d+(?:[.,]\d+)?)\s*(KOS|SC)\s+(\d+(?:[.,]\d+)?)',
            vrstica
        )
        if not m:
            continue
        sifra = m.group(1).strip()
        postavke[sifra] = {
            'sifra': sifra,
            'naziv': m.group(2).strip(),
            'kolicina': _f(m.group(3)),
            'cena': _f(m.group(5)),
        }
    return postavke


# ---------------------------------------------------------------------------
# 4. Primerjava
# ---------------------------------------------------------------------------
def primerjaj(eracun, prevzemnica, narocilnica):
    rezultati = []

    prevz_naziv = {normaliziraj_naziv(v['naziv']): k for k, v in prevzemnica.items()}
    nar_naziv = {normaliziraj_naziv(v['naziv']): k for k, v in narocilnica.items()}

    for _, e in eracun.items():
        # Poveži s prevzemnico
        p = None
        if e['sifra_in'] and e['sifra_in'] in prevzemnica:
            p = prevzemnica[e['sifra_in']]
        elif e['sifra_sa'] and e['sifra_sa'] in prevzemnica:
            p = prevzemnica[e['sifra_sa']]
        else:
            nk = normaliziraj_naziv(e['naziv'])
            if nk in prevz_naziv:
                p = prevzemnica[prevz_naziv[nk]]

        # Poveži z naročilnico
        n = None
        if e['sifra_in'] and e['sifra_in'] in narocilnica:
            n = narocilnica[e['sifra_in']]
        elif e['sifra_sa'] and e['sifra_sa'] in narocilnica:
            n = narocilnica[e['sifra_sa']]
        else:
            nk = normaliziraj_naziv(e['naziv'])
            if nk in nar_naziv:
                n = narocilnica[nar_naziv[nk]]

        opozorila = []

        if p is None:
            opozorila.append('NI V PREVZEMNICI')
        else:
            if abs(e['kolicina'] - p['kolicina']) > 0.001:
                opozorila.append(f"KOLIČINA (račun {e['kolicina']} ≠ prevzem {p['kolicina']})")
            if abs(e['cena_brez'] - p['cena_brez']) > 0.01:
                opozorila.append(f"CENA BREZ DDV (račun {e['cena_brez']:.4f} ≠ prevzem {p['cena_brez']:.4f})")
            if abs(e['popust'] - p['popust']) > 0.01:
                opozorila.append(f"POPUST (račun {e['popust']} ≠ prevzem {p['popust']})")
            if abs(e['znesek_brez'] - p['znesek_brez']) > 0.01:
                opozorila.append(f"ZNESEK BREZ DDV (račun {e['znesek_brez']} ≠ prevzem {p['znesek_brez']})")

        if n is None:
            opozorila.append('NI V NAROČILNICI')
        else:
            if abs(e['kolicina'] - n['kolicina']) > 0.001:
                opozorila.append(f"KOLIČINA (račun {e['kolicina']} ≠ naročilo {n['kolicina']})")
            if abs(e['cena_brez'] - n['cena']) > 0.01:
                opozorila.append(f"CENA (račun {e['cena_brez']:.4f} ≠ naročilo {n['cena']:.4f})")

        rezultati.append({
            'Šifra (interna)': e['sifra_in'],
            'Šifra (dobavitelj)': e['sifra_sa'],
            'Naziv': e['naziv'],
            'Kol. račun': e['kolicina'],
            'Kol. prevzem': p['kolicina'] if p else None,
            'Kol. naročilo': n['kolicina'] if n else None,
            'Cena račun': round(e['cena_brez'], 4),
            'Cena prevzem': round(p['cena_brez'], 4) if p else None,
            'Cena naročilo': round(n['cena'], 4) if n else None,
            'Znesek račun': round(e['znesek_brez'], 2),
            'Znesek prevzem': round(p['znesek_brez'], 2) if p else None,
            'Opozorila': '; '.join(opozorila) if opozorila else 'OK',
        })

    return rezultati
