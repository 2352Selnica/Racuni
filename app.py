# app.py
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import pdfplumber
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

try:
    from clipboard_component import paste_component
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False
    paste_component = None

# ---------------------------------------------------------------------------
# 1. POMOŽNE FUNKCIJE
# ---------------------------------------------------------------------------
def _f(vrednost, privzeto=0.0):
    if vrednost is None:
        return privzeto
    vrednost = str(vrednost).strip().replace(' ', '').replace(',', '.')
    try:
        return float(vrednost)
    except ValueError:
        return privzeto

def zaokrozi_na_dve(vrednost):
    if pd.isna(vrednost):
        return 0.0
    return float(Decimal(str(vrednost)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

def normaliziraj_naziv(n):
    if not n:
        return ""
    n = str(n).lower()
    n = re.sub(r'[^a-z0-9]+', ' ', n)
    return ' '.join(n.split())

def poisci_po_imenu(ciljni_naziv, slovar_postavk):
    if not ciljni_naziv:
        return None
    norm_cilj = normaliziraj_naziv(ciljni_naziv)
    for k, v in slovar_postavk.items():
        if normaliziraj_naziv(v['naziv']) == norm_cilj:
            return v
    ciljne_besede = set(norm_cilj.split())
    najboljse_ujemanje = None
    najvec_besed = 0
    for k, v in slovar_postavk.items():
        norm_v = normaliziraj_naziv(v['naziv'])
        v_besede = set(norm_v.split())
        skupne = ciljne_besede.intersection(v_besede)
        kljucne_ujemajoce = [b for b in skupne if len(b) >= 4]
        if len(kljucne_ujemajoce) > najvec_besed:
            najvec_besed = len(kljucne_ujemajoce)
            najboljse_ujemanje = v
    return najboljse_ujemanje if najvec_besed >= 1 else None

# ---------------------------------------------------------------------------
# 2. BRANJE DATOTEK
# ---------------------------------------------------------------------------
def preberi_eracun(stream):
    ns = {'eslog': 'urn:eslog:2.00'}
    tree = ET.parse(stream)
    root = tree.getroot()
    postavke = {}
    
    # Branje osnovnih podatkov računa (glava)
    glava = {
        'stevilka_racuna': '', 'datum_izdaje': '', 'datum_zapadlosti': '',
        'dobavitelj_naziv': '', 'dobavitelj_davcna': '',
        'prejemnik_naziv': '', 'prejemnik_davcna': '',
        'skupaj_brez_ddv': 0.0, 'skupaj_ddv': 0.0, 'skupaj_z_ddv': 0.0,
    }
    
    # Iskanje številke računa (v C_C106 namesto C_C002)
    bgm = root.find('.//eslog:S_BGM/eslog:C_C106', ns)
    if bgm is not None:
        glava['stevilka_racuna'] = bgm.findtext('eslog:D_1004', default='', namespaces=ns)
        
    for dtm in root.findall('.//eslog:S_DTM/eslog:C_C507', ns):
        tip = dtm.findtext('eslog:D_2005', default='', namespaces=ns)
        if tip == '137':
            glava['datum_izdaje'] = dtm.findtext('eslog:D_2380', default='', namespaces=ns)
        elif tip == '13':
            glava['datum_zapadlosti'] = dtm.findtext('eslog:D_2380', default='', namespaces=ns)
            
    for nad in root.findall('.//eslog:S_NAD', ns):
        vloga = nad.findtext('eslog:D_3035', default='', namespaces=ns)
        if vloga in ['SU', 'SE']:
            glava['dobavitelj_naziv'] = nad.findtext('eslog:C_C080/eslog:D_3036', default='', namespaces=ns)
        elif vloga in ['BY', 'DP', 'IV']:
            glava['prejemnik_naziv'] = nad.findtext('eslog:C_C080/eslog:D_3036', default='', namespaces=ns)
            
    for rff in root.findall('.//eslog:S_RFF/eslog:C_C506', ns):
        tip = rff.findtext('eslog:D_1153', default='', namespaces=ns)
        if tip in ['VA', 'FC']:
            vrednost = rff.findtext('eslog:D_1154', default='', namespaces=ns)
            if not glava['dobavitelj_davcna']:
                glava['dobavitelj_davcna'] = vrednost
            else:
                glava['prejemnik_davcna'] = vrednost

    # Iskanje skupnih zneskov na ravni dokumenta (v G_SG50)
    for sg50 in root.findall('.//eslog:G_SG50', ns):
        moa = sg50.find('eslog:S_MOA/eslog:C_C516', ns)
        if moa is not None:
            tip = moa.findtext('eslog:D_5025', default='', namespaces=ns)
            vred = _f(moa.findtext('eslog:D_5004', default='0', namespaces=ns))
            if tip == '79': 
                glava['skupaj_brez_ddv'] = vred
            elif tip == '176': 
                glava['skupaj_ddv'] = vred
            elif tip == '9': 
                glava['skupaj_z_ddv'] = vred

    # Branje postavk
    for sg26 in root.findall('.//eslog:G_SG26', ns):
        sifra_sa = sifra_in = ''
        for pia in sg26.findall('eslog:S_PIA', ns):
            c212 = pia.find('eslog:C_C212', ns)
            if c212 is None: continue
            vrednost = c212.findtext('eslog:D_7140', default='', namespaces=ns)
            tip = c212.findtext('eslog:D_7143', default='', namespaces=ns)
            if tip == 'SA': sifra_sa = vrednost
            elif tip == 'IN': sifra_in = vrednost
            
        naziv = ''
        imd = sg26.find('eslog:S_IMD', ns)
        if imd is not None:
            naziv = imd.findtext('eslog:C_C273/eslog:D_7008', default='', namespaces=ns)
        
        kolicina = 0.0
        enota = 'KOS'
        qty = sg26.find('eslog:S_QTY/eslog:C_C186', ns)
        if qty is not None:
            kolicina = _f(qty.findtext('eslog:D_6060', default='0', namespaces=ns))
            enota = qty.findtext('eslog:D_6411', default='KOS', namespaces=ns)
            if enota in ['H87', 'C62']: 
                enota = 'KOS'

        cena_brez = cena_z = 0.0
        for pri in sg26.findall('eslog:G_SG29/eslog:S_PRI/eslog:C_C509', ns):
            tip = pri.findtext('eslog:D_5125', default='', namespaces=ns)
            vred = _f(pri.findtext('eslog:D_5118', default='0', namespaces=ns))
            if tip == 'AAA': cena_brez = vred
            elif tip == 'AAB': cena_z = vred
            
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
            if tip == '203': znesek_brez = vred
            elif tip == '38': znesek_z = vred
            
        kljuc = sifra_in or sifra_sa or naziv
        postavke[kljuc] = {
            'sifra_sa': sifra_sa, 'sifra_in': sifra_in, 'naziv': naziv,
            'kolicina': kolicina, 'enota': enota, 'cena_brez': cena_brez, 'cena_z': cena_z,
            'popust': popust, 'ddv': ddv, 'znesek_brez': znesek_brez, 'znesek_z': znesek_z,
        }
        
    return {'glava': glava, 'postavke': postavke}

def preberi_eracun_iz_besedila(xml_besedilo):
    if isinstance(xml_besedilo, bytes):
        stream = io.BytesIO(xml_besedilo)
    else:
        stream = io.BytesIO(xml_besedilo.encode('utf-8'))
    return preberi_eracun(stream)

def preberi_prevzemnico_pdf(stream):
    postavke = {}
    with pdfplumber.open(stream) as pdf:
        vse_besedilo = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text: vse_besedilo += text + "\n"
    vrstice = vse_besedilo.split('\n')
    i = 0
    while i < len(vrstice):
        vrstica = vrstice[i]
        m = re.search(r'^(\d+)\s+(\d{6})\s+(.+?)\s+KOS\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)', vrstica)
        if m:
            sifra = m.group(2)
            naziv = m.group(3).strip()
            kolicina = _f(m.group(4))
            cena = _f(m.group(5))
            vrednost = _f(m.group(6))
            cena_brez, ddv, popust = 0.0, 0.0, 0.0
            if i + 1 < len(vrstice):
                naslednja = vrstice[i+1]
                m2 = re.search(r'^\d+\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)', naslednja)
                if m2:
                    cena_brez = _f(m2.group(1))
                    ddv = _f(m2.group(2))
                    popust = _f(m2.group(3))
            postavke[sifra] = {
                'sifra': sifra, 'naziv': naziv, 'enota': 'KOS',
                'kolicina': kolicina, 'cena_brez': cena_brez, 'cena_z': cena,
                'popust': popust, 'ddv': ddv, 'znesek_brez': vrednost, 'znesek_z': vrednost,
            }
            i += 1
        i += 1
    return postavke

def preberi_prevzemnico_xml(stream):
    vsebina = stream.read()
    if isinstance(vsebina, bytes): vsebina = vsebina.decode('utf-8', errors='replace')
    vsebina_ociscena = vsebina.replace('$', '_')
    stream_ociscen = io.BytesIO(vsebina_ociscena.encode('utf-8'))
    tree = ET.parse(stream_ociscen)
    root = tree.getroot()
    postavke = {}
    for post in root.findall('.//CG_G_POST'):
        sifra = post.findtext('ART_S_ARTIKLA', default='').strip()
        postavke[sifra] = {
            'sifra': sifra, 'naziv': post.findtext('ART_N_ARTIKLA', default='').strip(), 'enota': 'KOS',
            'kolicina': _f(post.findtext('POST_KOLICINA', default='0')),
            'cena_brez': _f(post.findtext('CF_CENA_BREZ_DDV', default='0')),
            'cena_z': _f(post.findtext('CF_CENA_Z_DDV', default='0')),
            'popust': _f(post.findtext('RABAT_DOB', default='0')),
            'ddv': _f(post.findtext('POST_O_PDAVKA', default='0')),
            'znesek_brez': _f(post.findtext('POST_VR_BREZ_DDV', default='0')),
            'znesek_z': _f(post.findtext('POST_VR_Z_DDV', default='0')),
        }
    return postavke

def preberi_narocilnico(stream):
    postavke = {}
    vsebina = stream.read()
    if isinstance(vsebina, bytes): vsebina = vsebina.decode('utf-8', errors='replace')
    for vrstica in vsebina.splitlines():
        if not vrstica.strip(): continue
        m = re.match(r'^\s*\d+\s+([0-9A-Za-z]+)\s+(.+?)\s+(\d+)\s*(KOS|SC)\s+([\d.,]+)', vrstica, re.IGNORECASE)
        if not m: continue
        sifra = m.group(1).strip()
        postavke[sifra] = {
            'sifra': sifra, 'naziv': m.group(2).strip(),
            'kolicina': _f(m.group(3)), 'enota': m.group(4).upper(),
            'cena': _f(m.group(5)),
        }
    return postavke

def pretvori_text_area_v_df(besedilo):
    if not besedilo.strip():
        return pd.DataFrame(columns=["Šifra artikla", "Naziv", "Enota", "Količina", "Cena"])
    enotno_besedilo = besedilo.replace('\r\n', '\n').replace('\r', '\n')
    zdruzeno = re.sub(r'\n\s*(?=\d{1,3}\s+\d{5,6}|\d{5,6}\s+[A-ZČŠŽ])', ' ||| ', enotno_besedilo)
    zdruzeno = zdruzeno.replace('\n', ' ')
    vrstice = zdruzeno.split(' ||| ')
    podatki = []
    for vrstica in vrstice:
        vrstica = vrstica.strip()
        if not vrstica: continue
        besede = vrstica.split()
        if len(besede) < 5: continue
        sifra = ""
        enota = ""
        idx_kos = -1
        for i, b in enumerate(besede):
            if b.upper() in ["KOS", "SC"]:
                idx_kos = i
                enota = b.upper()
                break
        if idx_kos != -1:
            for b in besede[:idx_kos]:
                if re.match(r'^\d{5,6}$', b):
                    sifra = b
                    break
            if not sifra and len(besede) > 1 and re.match(r'^\d{5,6}$', besede[1]):
                sifra = besede[1]
            try:
                idx_sifra = besede.index(sifra) if sifra in besede else 0
                naziv = " ".join(besede[idx_sifra+1:idx_kos])
            except ValueError:
                naziv = " ".join(besede[1:idx_kos])
            stevilke_za_kos = []
            for b in besede[idx_kos+1:]:
                cisto = b.replace(',', '.')
                if re.match(r'^\d+(\.\d+)?$', cisto) and '-' not in b:
                    stevilke_za_kos.append(cisto)
                    if len(stevilke_za_kos) == 2:
                        break
            if len(stevilke_za_kos) >= 2:
                kolicina = stevilke_za_kos[0]
                cena = stevilke_za_kos[1]
                if sifra and naziv and "artikel" not in naziv.lower():
                    podatki.append({
                        "Šifra artikla": sifra,
                        "Naziv": naziv,
                        "Enota": enota,
                        "Količina": kolicina,
                        "Cena": cena
                    })
    if not podatki:
        return pd.DataFrame(columns=["Šifra artikla", "Naziv", "Enota", "Količina", "Cena"])
    return pd.DataFrame(podatki)

def pretvori_dataframe_v_slovar(df, tip="prevzemnica"):
    postavke = {}
    if df is None or df.empty: return postavke
    for _, vrstica in df.iterrows():
        sifra = str(vrstica.get('Šifra artikla', '')).strip()
        if not sifra or sifra.lower() == 'none': continue
        def vrednost(stolpec):
            val = vrstica.get(stolpec, 0.0)
            if pd.isna(val): return 0.0
            return _f(str(val).replace(',', '.'))
        kolicina = vrednost('Količina')
        cena = vrednost('Cena')
        postavke[sifra] = {
            'sifra': sifra,
            'naziv': str(vrstica.get('Naziv', '')).strip(),
            'enota': str(vrstica.get('Enota', 'KOS')).strip(),
            'kolicina': kolicina,
            'cena': cena,
            'cena_brez': cena, 'cena_z': cena,
            'popust': 0.0, 'ddv': 0.0,
            'znesek_brez': kolicina * cena, 'znesek_z': kolicina * cena
        }
    return postavke

# ---------------------------------------------------------------------------
# 3. PRIMERJAVA
# ---------------------------------------------------------------------------
def izracunaj_opozorila(kol_r, kol_p, cena_r, cena_n):
    opozorila = []
    if pd.notna(kol_r) and pd.notna(kol_p):
        if abs(kol_r - kol_p) > 0.001:
            opozorila.append(f"KOLIČINA (račun {kol_r} ≠ prevzem {kol_p})")
    if pd.notna(cena_r) and pd.notna(cena_n) and cena_n > 0:
        if abs(cena_r - cena_n) > 0.0001:
            opozorila.append(f"CENA (račun {cena_r:.4f} ≠ naročilo {cena_n:.4f})")
    return '; '.join(opozorila) if opozorila else 'OK'

def primerjaj(eracun, prevzemnica, narocilnica):
    rezultati = []
    for _, e in eracun.items():
        p = prevzemnica.get(e['sifra_in']) if e['sifra_in'] else None
        if not p: p = poisci_po_imenu(e['naziv'], prevzemnica)
        n = narocilnica.get(e['sifra_in']) if e['sifra_in'] else None
        if not n: n = poisci_po_imenu(e['naziv'], narocilnica)
        
        sifra_interna = e.get('sifra_in', '')
        if p and p.get('sifra'): sifra_interna = p['sifra']
        elif n and n.get('sifra'): sifra_interna = n['sifra']

        kol_r = e['kolicina']
        kol_p = p['kolicina'] if p else 0.0
        cena_r = e['cena_brez']
        cena_n = n['cena'] if n else 0.0

        opozorila = izracunaj_opozorila(kol_r, kol_p, cena_r, cena_n)
        
        rezultati.append({
            'Šifra (naša)': sifra_interna,
            'Šifra (dobavitelj)': e.get('sifra_sa', ''),
            'Naziv': e['naziv'],
            'Enota': e['enota'],
            'Količina': round(kol_r, 2), 
            'Cena': round(cena_r, 4), 
            'Opozorila': opozorila,
        })
    return rezultati

# ---------------------------------------------------------------------------
# 4. STREAMLIT VMESNIK
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Primerjava računa", page_icon="📑", layout="wide")
st.title("📑 Primerjava eRačuna, prevzemnice in naročilnice")

if 'zgodovina' not in st.session_state:
    st.session_state['zgodovina'] = []

with st.container(border=True):
    st.markdown("### 📂 Vnos podatkov")
    st.markdown("**1. eRačun**")
    
    if not CLIPBOARD_AVAILABLE:
        st.warning("Komponenta `streamlit-clipboard` ni nameščena. Uporabite lahko le nalaganje datoteke XML.")
        nacin_eracun = "📁 Naloži datoteko XML"
    else:
        nacin_eracun = st.radio(
            "Način vnosa eRačuna:",
            ["📋 Preberi iz odložišča", "📁 Naloži datoteko XML"],
            horizontal=True,
            key="nacin_eracun_radio",
        )

    f_eracun = None
    xml_iz_odlozisca = None
    eracun_podatki = None

    if nacin_eracun == "📋 Preberi iz odložišča":
        st.caption("V sistemu za likvidacijo kliknite na povezavo za prenos XML, v brskalniku pritisnite Ctrl+A za izbiro vsega, nato Ctrl+C za kopiranje, ter se vrnite v to aplikacijo in kliknite spodnji gumb.")
        if CLIPBOARD_AVAILABLE:
            xml_iz_odlozisca = paste_component("📋 Preberi XML iz odložišča")
        if xml_iz_odlozisca:
            st.success("✅ Uspešno prebrano iz odložišča")
            eracun_podatki = preberi_eracun_iz_besedila(xml_iz_odlozisca)
    else:
        f_eracun = st.file_uploader("Naložite eRačun (XML, eSLOG)", type=["xml"], label_visibility="collapsed", key="uploader_eracun")
        if f_eracun:
            eracun_podatki = preberi_eracun(f_eracun)

    # --- Predogled prebranih podatkov iz eRačuna ---
    if eracun_podatki:
        st.write("Predogled prebranih podatkov:")
        df_eracun_predogled = pd.DataFrame([
            {
                "Šifra artikla": e.get('sifra_in') or e.get('sifra_sa', ''),
                "Naziv": e.get('naziv', ''),
                "Enota": e.get('enota', 'KOS'),
                "Količina": round(e.get('kolicina', 0.0), 2),
                "Cena": round(e.get('cena_brez', 0.0), 4)
            } for e in eracun_podatki['postavke'].values()
        ])
        st.dataframe(df_eracun_predogled, width="stretch", hide_index=True)

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**2. Prevzemnica (Dobavnica)**")
        nacin_prevzem = st.radio("Način vnosa prevzemnice:", ["Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)", "Naloži datoteko"], horizontal=True, key="nacin_prevzem_radio")
        if nacin_prevzem == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)":
            st.caption("Označite celotno tabelo v maopu (Ctrl+A), jo kopirajte (Ctrl+C) in prilepite tukaj (Ctrl+V).")
            besedilo_prevzem = st.text_area("Prilepite surovo besedilo iz tabele:", height=200, key="txt_prevzem", placeholder="Tukaj prilepite vsebino...")
            if besedilo_prevzem:
                df_prevzem_vnos = pretvori_text_area_v_df(besedilo_prevzem)
                st.write("Predogled prebranih podatkov:")
                st.dataframe(df_prevzem_vnos, width="stretch", hide_index=True)
            else:
                df_prevzem_vnos = pd.DataFrame()
            f_prevzemnica = None
        else:
            f_prevzemnica = st.file_uploader("Naložite prevzemnico (XML ali PDF)", type=["xml", "pdf"], label_visibility="collapsed", key="uploader_prevzemnica")
            df_prevzem_vnos = None

    with col2:
        st.markdown("**3. Naročilnica**")
        nacin_narocilo = st.radio("Način vnosa naročilnice:", ["Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)", "Naloži datoteko (TXT)"], horizontal=True, key="nacin_narocilo_radio")
        if nacin_narocilo == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)":
            st.caption("Označite celotno tabelo v maopu (Ctrl+A), jo kopirajte (Ctrl+C) in prilepite tukaj (Ctrl+V).")
            besedilo_narocilo = st.text_area("Prilepite surovo besedilo iz tabele:", height=200, key="txt_narocilo", placeholder="Tukaj prilepite vsebino...")
            if besedilo_narocilo:
                df_narocilo_vnos = pretvori_text_area_v_df(besedilo_narocilo)
                st.write("Predogled prebranih podatkov:")
                st.dataframe(df_narocilo_vnos, width="stretch", hide_index=True)
            else:
                df_narocilo_vnos = pd.DataFrame()
            f_narocilnica = None
        else:
            f_narocilnica = st.file_uploader("Naložite naročilnico (TXT)", type=["txt"], label_visibility="collapsed", key="uploader_narocilnica")
            df_narocilo_vnos = None

st.markdown("---")

if st.button("🔍 Zaženi primerjavo", type="primary", width="stretch"):
    if nacin_eracun == "📁 Naloži datoteko XML" and not f_eracun:
        st.warning("Prosimo, naložite eRačun.")
        st.stop()
    if nacin_eracun == "📋 Preberi iz odložišča" and not xml_iz_odlozisca:
        st.warning("Prosimo, kliknite gumb »Preberi XML iz odložišča« in poskrbite, da odložišče vsebuje vsebino XML.")
        st.stop()

    if nacin_prevzem == "Naloži datoteko" and not f_prevzemnica:
        st.warning("Prosimo, naložite prevzemnico.")
        st.stop()
    if nacin_prevzem == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)" and (df_prevzem_vnos is None or df_prevzem_vnos.empty):
        st.warning("Prosimo, prilepite podatke v polje za prevzemnico.")
        st.stop()

    if nacin_narocilo == "Naloži datoteko (TXT)" and not f_narocilnica:
        st.warning("Prosimo, naložite naročilnico.")
        st.stop()
    if nacin_narocilo == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)" and (df_narocilo_vnos is None or df_narocilo_vnos.empty):
        st.warning("Prosimo, prilepite podatke v polje za naročilnico.")
        st.stop()

    try:
        with st.spinner("Berem in primerjam ..."):
            if not eracun_podatki:
                if nacin_eracun == "📁 Naloži datoteko XML":
                    eracun_podatki = preberi_eracun(f_eracun)
                else:
                    eracun_podatki = preberi_eracun_iz_besedila(xml_iz_odlozisca)

            glava_racuna = eracun_podatki['glava']
            eracun = eracun_podatki['postavke']
            st.session_state['glava_racuna'] = glava_racuna

            if nacin_prevzem == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)":
                prevzemnica = pretvori_dataframe_v_slovar(df_prevzem_vnos, tip="prevzemnica")
            elif f_prevzemnica.name.lower().endswith('.pdf'):
                prevzemnica = preberi_prevzemnico_pdf(f_prevzemnica)
            else:
                prevzemnica = preberi_prevzemnico_xml(f_prevzemnica)
                
            if nacin_narocilo == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)":
                narocilnica = pretvori_dataframe_v_slovar(df_narocilo_vnos, tip="narocilnica")
            else:
                narocilnica = preberi_narocilnico(f_narocilnica)
            
            rezultati = primerjaj(eracun, prevzemnica, narocilnica)
            st.session_state['df_rezultati'] = pd.DataFrame(rezultati)
            
            # --- Izračun skupnega seštevka (količina × cena) ---
            skupni_izracun = 0.0
            for _, e in eracun.items():
                p = prevzemnica.get(e['sifra_in']) if e['sifra_in'] else None
                if not p: p = poisci_po_imenu(e['naziv'], prevzemnica)
                n = narocilnica.get(e['sifra_in']) if e['sifra_in'] else None
                if not n: n = poisci_po_imenu(e['naziv'], narocilnica)
                
                kol_p = p['kolicina'] if p else 0.0
                cena_n = n['cena'] if n else 0.0
                skupni_izracun += (kol_p * cena_n)
            
            st.session_state['skupni_izracun'] = skupni_izracun
            # ---------------------------------------------------------
            
            cas = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            sestevek_racun = sum([r['Cena'] for r in rezultati])
            st.session_state['zgodovina'].append({
                "Čas": cas,
                "Št. postavk": len(rezultati),
                "Skupaj račun (brez DDV)": f"{sestevek_racun:.2f} €",
                "Opozorila": sum([1 for r in rezultati if r['Opozorila'] != 'OK'])
            })
    except Exception as e:
        st.error(f"Napaka pri obdelavi: {e}")
        st.exception(e)

if 'df_rezultati' in st.session_state:
    df = st.session_state['df_rezultati']
    
    if 'glava_racuna' in st.session_state:
        glava = st.session_state['glava_racuna']
        st.subheader("📄 Osnovni podatki računa")
        with st.container(border=True):
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.write(f"**Številka računa:** {glava['stevilka_racuna'] or '-'}")
                st.write(f"**Datum izdaje:** {glava['datum_izdaje'] or '-'}")
                st.write(f"**Datum zapadlosti:** {glava['datum_zapadlosti'] or '-'}")
                st.write(f"**Dobavitelj:** {glava['dobavitelj_naziv'] or '-'}")
                st.write(f"**Davčna št. dobavitelja:** {glava['dobavitelj_davcna'] or '-'}")
            with col_g2:
                st.write(f"**Prejemnik:** {glava['prejemnik_naziv'] or '-'}")
                st.write(f"**Davčna št. prejemnika:** {glava['prejemnik_davcna'] or '-'}")
                st.write(f"**Skupaj brez DDV:** {glava['skupaj_brez_ddv']:.2f} €")
                st.write(f"**Skupaj DDV:** {glava['skupaj_ddv']:.2f} €")
                st.write(f"**Skupaj z DDV:** {glava['skupaj_z_ddv']:.2f} €")

    st.subheader("📊 Povzetek")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Postavk na računu", len(df))
    c2.metric("Brez opozoril", (df['Opozorila'] == 'OK').sum())
    c3.metric("Z opozorili", (df['Opozorila'] != 'OK').sum())

    skupaj_racun = df['Cena'].sum()
    
    st.subheader("📋 Primerjalna tabela")
    st.info(
        "💡 Namig: Kliknite na celico v stolpcu **'Cena'**, "
        "da ročno popravite ceno. Če se bo cena ujemala z računom, bo opozorilo izginilo."
    )

    def obarvaj_vrstico(vrstica):
        if vrstica['Opozorila'] == 'OK':
            return ['background-color: #d4edda'] * len(vrstica)
        return ['background-color: #f8d7da'] * len(vrstica)

    edited_df = st.data_editor(
        df,
        column_config={
            "Šifra (naša)": st.column_config.TextColumn("Šifra (naša)", disabled=True),
            "Šifra (dobavitelj)": st.column_config.TextColumn("Šifra (dobavitelj)", disabled=True),
            "Naziv": st.column_config.TextColumn("Naziv", width="large", disabled=True),
            "Enota": st.column_config.TextColumn("Enota", disabled=True),
            "Količina": st.column_config.NumberColumn("Količina", format="%.2f", disabled=True),
            "Cena": st.column_config.NumberColumn("Cena", format="%.4f", step=0.0001),
            "Opozorila": st.column_config.TextColumn("Opozorila", width="medium", disabled=True),
        },
        hide_index=True,
        width="stretch",
        key="editor",
    )

    if not edited_df.equals(df):
        for idx, row in edited_df.iterrows():
            edited_df.at[idx, 'Opozorila'] = izracunaj_opozorila(
                row['Količina'], row['Količina'], 
                row['Cena'], row['Cena']
            )
        st.session_state['df_rezultati'] = edited_df
        st.rerun()

    st.markdown("##### Predogled barvnega stanja (po morebitnih popravkih):")
    st.dataframe(
        edited_df.style.apply(obarvaj_vrstico, axis=1).format(precision=2, na_rep="-"),
        width="stretch",
        hide_index=True,
    )

    st.markdown("### 💰 Skupni seštevki")
    col_s1, col_s2 = st.columns(2)
    
    # Skupaj račun brez DDV
    col_s1.metric(
        "Skupaj račun (brez DDV)",
        f"{skupaj_racun:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')
    )
    
    # Skupaj račun z DDV (iz glave računa)
    skupaj_z_ddv = glava.get('skupaj_z_ddv', 0.0) if 'glava_racuna' in st.session_state else 0.0
    col_s2.metric(
        "Skupaj račun (z DDV)",
        f"{skupaj_z_ddv:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')
    )

    # Skupaj izračun (količina prevzemnice × cena naročilnice)
    if 'skupni_izracun' in st.session_state:
        st.markdown("---")
        izracun = st.session_state['skupni_izracun']
        razlika = abs(skupaj_racun - izracun)
        
        st.metric(
            "Skupaj izračun (Količina prevzemnice × Cena naročilnice)",
            f"{izracun:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')
        )
        
        if razlika > 0.01:
            st.error(f"⚠️ **Razlika med računom in izračunom:** {razlika:.2f} €")
        else:
            st.success("✅ **Seštevki se ujemajo!**")

    st.markdown("### 📤 Izvoz")
    df_export = edited_df.copy()
    csv_buffer = io.StringIO()
    df_export.to_csv(csv_buffer, index=False, sep=';', decimal=',')
    st.download_button(
        label="📥 Prenesi CSV",
        data=csv_buffer.getvalue().encode('utf-8-sig'),
        file_name=f"primerjava_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        width="stretch",
    )
