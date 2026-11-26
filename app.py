# app.py (celotna koda, ključne spremembe so označene s komentarji)

import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import pdfplumber
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# 【Novo】Uvoz komponente za odložišče
from clipboard_component import paste_component

# ---------------------------------------------------------------------------
# 1. POMOŽNE FUNKCIJE (ohranjene brez sprememb)
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
# 2. BRANJE DATOTEK (ohranjeno brez sprememb, dodana pomožna funkcija)
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

# 【Novo】Pomožna funkcija za pretvorbo besedilnega niza v tok
def preberi_eracun_iz_besedila(xml_besedilo):
    """Pretvori besedilni niz XML v BytesIO in pokliči izvirno funkcijo preberi_eracun"""
    if isinstance(xml_besedilo, bytes):
        stream = io.BytesIO(xml_besedilo)
    else:
        stream = io.BytesIO(xml_besedilo.encode('utf-8'))
    return preberi_eracun(stream)

def preberi_prevzemnico_pdf(stream):
    # ... (vaša izvirna koda, brez sprememb)
    pass

def preberi_prevzemnico_xml(stream):
    # ... (vaša izvirna koda, brez sprememb)
    pass

def preberi_narocilnico(stream):
    # ... (vaša izvirna koda, brez sprememb)
    pass

def pretvori_text_area_v_df(besedilo):
    # ... (vaša izvirna koda, brez sprememb)
    pass

def pretvori_dataframe_v_slovar(df, tip="prevzemnica"):
    # ... (vaša izvirna koda, brez sprememb)
    pass

# ---------------------------------------------------------------------------
# 3. PRIMERJAVA (ohranjeno brez sprememb)
# ---------------------------------------------------------------------------
def izracunaj_opozorila(racun_kol, prevzem_kol, racun_cena, narocilo_cena, racun_znesek, izracunan_znesek):
    # ... (vaša izvirna koda, brez sprememb)
    pass

def primerjaj(eracun, prevzemnica, narocilnica):
    # ... (vaša izvirna koda, brez sprememb)
    pass

# ---------------------------------------------------------------------------
# 4. STREAMLIT VMESNIK
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Primerjava računa", page_icon="📑", layout="wide")
st.title("📑 Primerjava eRačuna, prevzemnice in naročilnice")

if 'zgodovina' not in st.session_state:
    st.session_state['zgodovina'] = []

with st.container(border=True):
    st.markdown("### 📂 Vnos podatkov")
    
    # 【Sprememba】Razdelek za eRačun: ponuja dva načina – nalaganje in branje iz odložišča
    st.markdown("**1. eRačun**")
    nacin_eracun = st.radio(
        "Način vnosa eRačuna:",
        ["📋 Preberi iz odložišča", "📁 Naloži datoteko XML"],
        horizontal=True,
        key="nacin_eracun"
    )
    
    f_eracun = None
    xml_iz_odlozisca = None
    
    if nacin_eracun == "📋 Preberi iz odložišča":
        st.caption("V sistemu za likvidacijo kliknite na povezavo za prenos XML, v brskalniku pritisnite Ctrl+A za izbiro vsega, nato Ctrl+C za kopiranje, ter se vrnite v to aplikacijo in kliknite spodnji gumb.")
        # Uporabite komponento paste_component
        xml_iz_odlozisca = paste_component("📋 Preberi XML iz odložišča")
        if xml_iz_odlozisca:
            st.success("✅ Uspešno prebrano iz odložišča")
            # Prikažite predogled (neobvezno, za lažje preverjanje uporabnika)
            with st.expander("Predogled vsebine odložišča (prvih 500 znakov)"):
                st.code(xml_iz_odlozisca[:500] + "..." if len(xml_iz_odlozisca) > 500 else xml_iz_odlozisca)
    else:
        f_eracun = st.file_uploader("Naložite eRačun (XML, eSLOG)", type=["xml"], label_visibility="collapsed")
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**2. Prevzemnica (Dobavnica)**")
        nacin_prevzem = st.radio("Način vnosa prevzemnice:", ["Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)", "Naloži datoteko"], horizontal=True, key="nacin_prevzem")
        
        if nacin_prevzem == "Besedilo (Ctrl+A, Ctrl+C, Ctrl+V)":
            st.caption("Označite celotno tabelo v maopu (Ctrl+A), jo kopirajte (Ctrl+C) in prilepite tukaj (Ctrl+V).")
            
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
    # 【Sprememba】Preverjanje: vir eRačuna je lahko datoteka ali odložišče
    eracun_vi == None
    if nacin_eracun == "📁 Naloži datoteko XML":
        if not f_eracun:
            st.warning("Prosimo, naložite eRačun.")
            st.stop()
    else:
        if not xml_iz_odlozisca:
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
            # 【Sprememba】Glede na način vnosa preberite eRačun
            if nacin_eracun == "📁 Naloži datoteko XML":
                eracun = preberi_eracun(f_eracun)
            else:
                eracun = preberi_eracun_iz_besedila(xml_iz_odlozisca)
            
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

# ... (spodnja koda za prikaz rezultatov in urejanje je popolnoma enaka vaši izvirni kodi, zato je tu ne ponavljamo)
