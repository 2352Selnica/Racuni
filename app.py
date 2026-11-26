# app.py
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import pdfplumber
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# 1. POMOŽNE FUNKCIJE
# ---------------------------------------------------------------------------
def _f(vrednost, privzeto=0.0):
    if vrednost is None: return privzeto
    vrednost = str(vrednost).strip().replace(' ', '').replace(',', '.')
    try: return float(vrednost)
    except ValueError: return privzeto

def zaokrozi_na_dve(vrednost):
    if pd.isna(vrednost): return 0.0
    return float(Decimal(str(vrednost)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

def normaliziraj_naziv(n):
    if not n: return ""
    n = str(n).lower()
    n = re.sub(r'[^a-z0-9]+', ' ', n)
    return ' '.join(n.split())

def poisci_po_imenu(ciljni_naziv, slovar_postavk):
    if not ciljni_naziv: return None
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
            if enota == 'H87': enota = 'KOS'

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
    return postavke

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
    """Pretvori prilepljeno besedilo (iz brskalnika) v DataFrame."""
    if not besedilo.strip():
        return pd.DataFrame(columns=["Šifra artikla", "Naziv", "Enota", "Količina", "Cena"])
    
    # Poskusimo prebrati s tabulatorji (najpogostejši način pri kopiranju iz brskalnika/Excela)
    try:
        df = pd.read_csv(io.StringIO(besedilo), sep='\t', dtype=str, header=None)
    except Exception:
        # Če ne uspe, poskusimo s podpičjem
        df = pd.read_csv(io.StringIO(besedilo), sep=';', dtype=str, header=None)
        
    # Preverimo, ali ima tabela dovolj stolpcev (predpostavimo, da je šifra v 2. stolpcu, naziv v 3., enota v 4., količina 6., cena 7.)
    # Prilagodite indekse glede na točno strukturo, ki jo dobite pri kopiranju!
    if df.shape[1] >= 5:
        # Vzamemo samo želene stolpce in jih preimenujemo (indeksi se lahko razlikujejo glede na vaš sistem!)
        # Za maop sistem (priponka 5 in 6): šifra=1, naziv=2, enota=3, količina=5, cena=6 (šteto od 0)
        df_izbrani = df.iloc[:, [1, 2, 3, 5, 6]].copy() if df.shape[1] > 6 else df.iloc[:, [1, 2, 3, 4, 5]].copy()
        df_izbrani.columns = ["Šifra artikla", "Naziv", "Enota", "Količina", "Cena"]
        
        # Počistimo vrstice, kjer je šifra prazna ali vsebuje glavo tabele
        df_izbrani = df_izbrani[df_izbrani["Šifra artikla"].notna()]
        df_izbrani = df_izbrani[~df_izbrani["Šifra artikla"].str.contains("Artikel|Šifra|VP", case=False, na=False)]
        
        return df_izbrani.reset_index(drop=True)
    
    # Če ne uspe, vrnemo prazno tabelo
    return pd.DataFrame(columns=["Šifra artikla", "Naziv", "Enota", "Količina", "Cena"])

def pretvori_dataframe_v_slovar(df, tip="prevzemnica"):
    postavke = {}
    if df is None or df.empty: 
        return postavke
        
    for _, vrstica in df.iterrows():
        sifra = str(vrstica.get('Šifra artikla', '')).strip()
        if not sifra or sifra.lower() == 'none': 
            continue
            
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
            'cena_brez': cena, 
            'cena_z': cena, 
            'popust': 0.0, 
            'ddv': 0.0,
            'znesek_brez': kolicina * cena, 
            'znesek_z': kolicina * cena
        }
    return postavke

# ---------------------------------------------------------------------------
# 3. PRIMERJAVA
# ---------------------------------------------------------------------------
def izracunaj_opozorila(racun_kol, prevzem_kol, racun_cena, narocilo_cena, racun_znesek, izracunan_znesek):
    opozorila = []
    
    # 1. Primerjava količin
    if pd.notna(racun_kol) and pd.notna(prevzem_kol):
        if abs(racun_kol - prevzem_kol) > 0.001:
            opozorila.append(f"KOLIČINA (račun {racun_kol} ≠ prevzem {prevzem_kol})")
            
    # 2. Primerjava cen
    if pd.notna(racun_cena) and pd.notna(narocilo_cena) and narocilo_cena > 0:
        if abs(racun_cena - narocilo_cena) > 0.0001:
            opozorila.append(f"CENA (račun {racun_cena:.4f} ≠ naročilo {narocilo_cena:.4f})")
            
    # 3. Primerjava zneskov
    if pd.notna(racun_znesek) and pd.notna(izracunan_znesek):
        if zaokrozi_na_dve(racun_znesek) != zaokrozi_na_dve(izracunan_znesek):
            opozorila.append(f"VREDNOST (račun {racun_znesek:.2f} ≠ izračun {izracunan_znesek:.2f})")
            
    return '; '.join(opozorila) if opozorila else 'OK'

def primerjaj(eracun, prevzemnica, narocilnica):
    rezultati = []
    for _, e in eracun.items():
        p = prevzemnica.get(e['sifra_in']) if e['sifra_in'] else None
        if not p: p = poisci_po_imenu(e['naziv'], prevzemnica)
        
        n = narocilnica.get(e['sifra_in']) if e['sifra_in'] else None
        if not n: n = poisci_po_imenu(e['naziv'], narocilnica)
        
        ident = e['sifra_in']
        if p and p['sifra']: ident = p['sifra']
        elif n and n['sifra']: ident = n['sifra']

        kol_r = e['kolicina']
        kol_p = p['kolicina'] if p else 0.0
        kol_n = n['kolicina'] if n else 0.0

        cena_n = n['cena'] if n else 0.0
        
        osnova_za_znesek = kol_p if p else 0.0
        znesek_n = osnova_za_znesek * cena_n
        
        opozorila = izracunaj_opozorila(kol_r, kol_p, e['cena_brez'], cena_n, e['znesek_brez'], znesek_n)
        
        rezultati.append({
            'Ident': ident, 
            'Šifra dob.': e['sifra_sa'],
            'Naziv': e['naziv'],
            'Em račun': e['enota'],
            'Kol. račun': round(kol_r, 2), 
            'Em prevzem': p['enota'] if p else '',
            'Kol. prevzem': round(kol_p, 2) if p else None, 
            'Em naročilo': n['enota'] if n else '',
            'Kol. naročilo': round(kol_n, 2), 
            'Cena račun': round(e['cena_brez'], 4), 
            'Cena naročilo': round(cena_n, 4),
            'Znesek račun': zaokrozi_na_dve(e['znesek_brez']), 
            'Znesek naročilo': zaokrozi_na_dve(znesek_n),
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
    
    # 1. eRačun
    st.markdown("**1. eRačun**")
    f_eracun = st.file_uploader("Naložite eRačun (XML, eSLOG)", type=["xml"], label_visibility="collapsed")
    
    st.markdown("---")
    
    # 2. Prevzemnica in 3. Naročilnica
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**2. Prevzemnica (Dobavnica)**")
        nacin_prevzem = st.radio("Način vnosa prevzemnice:", ["Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)", "Naloži datoteko"], horizontal=True, key="nacin_prevzem")
        
        if nacin_prevzem == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)":
            st.caption("Označite celotno tabelo v maopu (Ctrl+A), jo kopirajte (Ctrl+C) in prilepite tukaj (Ctrl+V).")
            
            # Uporabimo text_area, ki omogoča lepljenje celotnega bloka
            besedilo_prevzem = st.text_area(
                "Prilepite surovo besedilo iz tabele:", 
                height=200, 
                key="txt_prevzem",
                placeholder="Tukaj prilepite vsebino..."
            )
            
            if besedilo_prevzem:
                df_prevzem_vnos = pretvori_text_area_v_df(besedilo_prevzem)
                st.write("Predogled prebranih podatkov:")
                st.dataframe(df_prevzem_vnos, use_container_width=True, hide_index=True)
            else:
                df_prevzem_vnos = pd.DataFrame()
            f_prevzemnica = None
        else:
            f_prevzemnica = st.file_uploader("Naložite prevzemnico (XML ali PDF)", type=["xml", "pdf"], label_visibility="collapsed")
            df_prevzem_vnos = None

    with col2:
        st.markdown("**3. Naročilnica**")
        nacin_narocilo = st.radio("Način vnosa naročilnice:", ["Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)", "Naloži datoteko (TXT)"], horizontal=True, key="nacin_narocilo")
        
        if nacin_narocilo == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)":
            st.caption("Označite celotno tabelo v maopu (Ctrl+A), jo kopirajte (Ctrl+C) in prilepite tukaj (Ctrl+V).")
            
            besedilo_narocilo = st.text_area(
                "Prilepite surovo besedilo iz tabele:", 
                height=200, 
                key="txt_narocilo",
                placeholder="Tukaj prilepite vsebino..."
            )
            
            if besedilo_narocilo:
                df_narocilo_vnos = pretvori_text_area_v_df(besedilo_narocilo)
                st.write("Predogled prebranih podatkov:")
                st.dataframe(df_narocilo_vnos, use_container_width=True, hide_index=True)
            else:
                df_narocilo_vnos = pd.DataFrame()
            f_narocilnica = None
        else:
            f_narocilnica = st.file_uploader("Naložite naročilnico (TXT)", type=["txt"], label_visibility="collapsed")
            df_narocilo_vnos = None

st.markdown("---")

if st.button("🔍 Zaženi primerjavo", type="primary", use_container_width=True):
    if not f_eracun:
        st.warning("Prosimo, naložite eRačun.")
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
            eracun = preberi_eracun(f_eracun)
            
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
            
            cas = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            sestevek_racun = sum([r['Znesek račun'] for r in rezultati])
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
    
    st.subheader("📊 Povzetek")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Postavk na računu", len(df))
    c2.metric("Brez opozoril", (df['Opozorila'] == 'OK').sum())
    c3.metric("Z opozorili", (df['Opozorila'] != 'OK').sum())
    
    skupaj_racun = df['Znesek račun'].sum()
    skupaj_narocilo = df['Znesek naročilo'].sum()
    razlika = abs(skupaj_racun - skupaj_narocilo)
    
    if razlika > 0.01:
        st.error(f"⚠️ **Skupni seštevek se ne ujema!** Račun: {skupaj_racun:.2f} €, Izračun: {skupaj_narocilo:.2f} € (Razlika: {razlika:.2f} €)")
    else:
        st.success(f"✅ **Skupni seštevek se ujema!** ({skupaj_racun:.2f} €)")

    st.subheader("📋 Primerjalna tabela")
    st.info("💡 Namig: Kliknite na celico v stolpcu **'Cena naročilo'**, da ročno popravite ceno. Če se bo cena ujemala z računom, bo opozorilo izginilo.")
    
    def obarvaj_vrstico(vrstica):
        if vrstica['Opozorila'] == 'OK':
            return ['background-color: #d4edda'] * len(vrstica)
        return ['background-color: #f8d7da'] * len(vrstica)

    edited_df = st.data_editor(
        df,
        column_config={
            "Ident": st.column_config.TextColumn("Ident", disabled=True),
            "Šifra dob.": st.column_config.TextColumn("Šifra dob.", disabled=True),
            "Naziv": st.column_config.TextColumn("Naziv", width="large", disabled=True),
            "Em račun": st.column_config.TextColumn("Em račun", disabled=True),
            "Kol. račun": st.column_config.NumberColumn("Kol. račun", format="%.2f", disabled=True),
            "Em prevzem": st.column_config.TextColumn("Em prevzem", disabled=True),
            "Kol. prevzem": st.column_config.NumberColumn("Kol. prevzem", format="%.2f", disabled=True),
            "Em naročilo": st.column_config.TextColumn("Em naročilo", disabled=True),
            "Kol. naročilo": st.column_config.NumberColumn("Kol. naročilo", format="%.2f", disabled=True), 
            "Cena račun": st.column_config.NumberColumn("Cena račun", format="%.4f", disabled=True),
            "Cena naročilo": st.column_config.NumberColumn("Cena naročilo", format="%.4f", step=0.0001), 
            "Znesek račun": st.column_config.NumberColumn("Znesek račun", format="%.2f", disabled=True),
            "Znesek naročilo": st.column_config.NumberColumn("Znesek naročilo", format="%.2f", disabled=True),
            "Opozorila": st.column_config.TextColumn("Opozorila", width="medium", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        key="editor"
    )

    if not edited_df.equals(df):
        for idx, row in edited_df.iterrows():
            if pd.notna(row['Kol. prevzem']) and pd.notna(row['Cena naročilo']):
                edited_df.at[idx, 'Znesek naročilo'] = zaokrozi_na_dve(row['Kol. prevzem'] * row['Cena naročilo'])
            edited_df.at[idx, 'Opozorila'] = izracunaj_opozorila(
                row['Kol. račun'], row['Kol. prevzem'], 
                row['Cena račun'], row['Cena naročilo'], 
                row['Znesek račun'], edited_df.at[idx, 'Znesek naročilo']
            )
        st.session_state['df_rezultati'] = edited_df
        st.rerun()

    st.markdown("##### Predogled barvnega stanja (po morebitnih popravkih):")
    df_predogled = edited_df.drop(columns=['Em račun', 'Em prevzem', 'Em naročilo', 'Šifra dob.'], errors='ignore')
    st.dataframe(
        df_predogled.style.apply(obarvaj_vrstico, axis=1).format(precision=2, na_rep="-"),
        use_container_width=True,
        hide_index=True
    )

    st.markdown("### 💰 Skupni seštevki")
    col_s1, col_s2 = st.columns(2)
    col_s1.metric("Skupaj račun (brez DDV)", f"{skupaj_racun:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.'))
    col_s2.metric("Skupaj naročilo (brez DDV)", f"{skupaj_narocilo:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.'))

    df_export = edited_df.copy()
    df_export = df_export.rename(columns={
        'Cena račun': 'Cena račun (EUR)', 
        'Cena naročilo': 'Cena naročilo (EUR)', 
        'Znesek račun': 'Znesek račun (EUR)', 
        'Znesek naročilo': 'Znesek naročilo (EUR)'
    })
    df_export = df_export.drop(columns=['Em račun', '
