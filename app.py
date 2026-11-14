import os, itertools, requests, numpy as np, pandas as pd, streamlit as st

st.set_page_config(page_title="Rotasyon Danışmanı", page_icon="🌾", layout="wide")

BOLGELER = {"Kırklareli, Türkiye": (41.74, 27.22),
            "Iowa, ABD": (41.59, -93.62),
            "Pencap, Hindistan": (30.90, 75.86)}

# YER TUTUCU: kaynaklı değerlerle değiştirilecek
URUNLER = {
    "Buğday":   {"su": 2, "baklagil": False, "kok": "orta",  "grup": "tahil",    "gelir": 2},
    "Ayçiçeği": {"su": 2, "baklagil": False, "kok": "derin", "grup": "yagli",    "gelir": 3},
    "Fiğ":      {"su": 1, "baklagil": True,  "kok": "orta",  "grup": "baklagil", "gelir": 1},
    "Kolza":    {"su": 2, "baklagil": False, "kok": "derin", "grup": "yagli",    "gelir": 2},
}

# YER TUTUCU katsayılar (çiftçi beyanına göre ayarlanır, bilimsel değer değildir)
DOKU = {"Kumlu": -1, "Tınlı": 0, "Killi": 1, "Bilmiyorum": 0}
DER = {"Sığ": -1, "Orta": 0, "Derin": 1, "Bilmiyorum": 0}
ORG = {"Düşük": -8, "Orta": 0, "Yüksek": 8, "Bilmiyorum": 0}
EGIM = {"Düz": 0, "Hafif eğimli": -3, "Dik": -6, "Bilmiyorum": 0}
SUL = {"Kuru tarım": 1.0, "Kısmi sulama": 0.7, "Tam sulama": 0.4}

@st.cache_data(show_spinner="NASA POWER verisi çekiliyor (ilk seferde 10-30 sn)...")
def veri_getir(lat, lon):
    dosya = f"onbellek_{lat:.2f}_{lon:.2f}.csv"
    if os.path.exists(dosya):
        return pd.read_csv(dosya, index_col=0, parse_dates=True)
    p = {"parameters": "PRECTOTCORR,T2M", "community": "AG", "latitude": lat,
         "longitude": lon, "start": "20050101", "end": "20241231", "format": "JSON"}
    r = requests.get("https://power.larc.nasa.gov/api/temporal/daily/point",
                     params=p, timeout=180).json()
    df = pd.DataFrame(r["properties"]["parameter"])
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(-999, np.nan).rename(columns={"PRECTOTCORR": "yagis", "T2M": "sicaklik"})
    df.to_csv(dosya)
    return df

def ozet(df):
    y = df["yagis"].resample("YS").sum()
    esik = y.quantile(0.20)
    return {"ort": round(y.mean()), "cv": round(y.std() / y.mean(), 2),
            "acik": round(1 - y[y <= esik].mean() / y.mean(), 2), "yillik": y}

def skorla(rot, b, w, t, kurak=False):
    u = [URUNLER[x] for x in rot]; n = len(rot)
    ort_su = sum(x["su"] for x in u) / n
    derin = sum(x["kok"] == "derin" for x in u)
    yagis_f = min(max(b["ort"] / 600, 0.5), 1.5)
    sf = SUL[t["sulama"]]
    nedenler = []

    su = (100 - ((ort_su - 1) / 2) * 60 / yagis_f - 4 * derin
          + 6 * DOKU[t["doku"]] + 4 * DER[t["derinlik"]] + (1 - sf) * 25)
    bak = sum(x["baklagil"] for x in u); cesit = len(set(rot))
    toprak = 40 + 20 * min(bak, 1) + 10 * (cesit - 1) + ORG[t["organik"]] + EGIM[t["egim"]]
    if bak: nedenler.append("Baklagil, uygun koşullarda azot katkısı sağlayabilir.")
    if cesit >= 3: nedenler.append("Ürün çeşitliliği hastalık döngüsünü kırabilir.")
    if derin >= 2: nedenler.append("Birden fazla derin köklü ürün alt katman nemini tüketebilir.")
    if t["egim"] == "Dik": nedenler.append("Dik eğim: erozyon riski var, bitki örtüsü sürekliliği değerlendirilmeli.")
    if t["doku"] == "Kumlu": nedenler.append("Kumlu toprak suyu az tutar, su stresi riski artabilir (çiftçi beyanı).")
    for a, c in zip(rot, rot[1:]):
        if URUNLER[a]["grup"] == URUNLER[c]["grup"]:
            toprak -= 10
            nedenler.append(f"{a}→{c}: benzer ürün grubu art arda, hastalık riski.")
    pen = 100 * (0.5 * b["cv"] / 0.3 + 0.5 * b["acik"] / 0.4) * (ort_su / 3) * sf
    iklim = 100 - pen
    eko = sum(x["gelir"] for x in u) / n / 3 * 100
    if kurak:
        su *= 1 - 0.2 * sf; iklim *= 1 - 0.15 * sf
    sk = {k: max(0, min(100, round(v))) for k, v in
          {"Su": su, "Toprak": toprak, "İklim": iklim, "Ekonomi": eko}.items()}
    toplam = round(sum(sk[k] * w[k] for k in sk) / (sum(w.values()) or 1))
    return sk, toplam, nedenler

# ---------------- Arayüz ----------------
st.title("🌾 Rotasyon Danışmanı")
st.caption("NASA verileriyle geliştirilen karar destek aracı · TASLAK: ürün ve toprak katsayıları yer tutucudur, tarımsal tavsiye değildir.")

with st.sidebar:
    st.header("1. Bölge")
    secim = st.selectbox("Hazır bölge", list(BOLGELER) + ["Kendi koordinatım"])
    lat0, lon0 = BOLGELER.get(secim, (41.0, 28.0))
    lat = st.number_input("Enlem", value=lat0, format="%.4f")
    lon = st.number_input("Boylam", value=lon0, format="%.4f")

    st.header("2. Tarlan (biliyorsan)")
    t = {"doku": st.selectbox("Toprak dokusu", ["Bilmiyorum", "Kumlu", "Tınlı", "Killi"]),
         "derinlik": st.selectbox("Toprak derinliği", ["Bilmiyorum", "Sığ", "Orta", "Derin"]),
         "organik": st.selectbox("Organik madde", ["Bilmiyorum", "Düşük", "Orta", "Yüksek"]),
         "egim": st.selectbox("Eğim", ["Bilmiyorum", "Düz", "Hafif eğimli", "Dik"]),
         "sulama": st.selectbox("Sulama", list(SUL))}

    st.header("3. Mevcut düzenin")
    varsayilan = [0, 1, 0, 1]
    mevcut = [st.selectbox(f"{i+1}. yıl ürünü", list(URUNLER), index=varsayilan[i], key=f"m{i}")
              for i in range(4)]

    st.header("4. Ekebileceğin ürünler")
    havuz = st.multiselect("Alternatiflerde kullanılsın", list(URUNLER), default=list(URUNLER))

    st.header("5. Önceliklerin")
    w = {"Su": st.slider("💧 Su", 0, 100, 35), "Toprak": st.slider("🌱 Toprak sağlığı", 0, 100, 30),
         "İklim": st.slider("🌡️ İklim riski", 0, 100, 15), "Ekonomi": st.slider("💰 Ekonomi", 0, 100, 20)}

df = veri_getir(round(lat, 2), round(lon, 2))
b = ozet(df)

bilinen = sum(t[k] != "Bilmiyorum" for k in ["doku", "derinlik", "organik", "egim"])
guven = "Orta-Yüksek" if bilinen >= 3 else "Orta"

st.subheader("Bölge özeti")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Ort. yıllık yağış", f"{b['ort']} mm")
c2.metric("Yıllar arası değişkenlik", b["cv"])
c3.metric("Kurak yıl şiddeti", b["acik"])
c4.metric("Veri güveni", guven)
st.info("Bölge iklimi NASA POWER (küresel, kaba çözünürlük) verisinden gelir; yerel sağanakları göstermeyebilir. "
        "Kurak yıl, bölgenin kendi son 20 yılının en düşük %20'si olarak tanımlandı. "
        "Toprak bilgileri çiftçi beyanıdır, ölçüm değildir.")
st.line_chart(b["yillik"].rename("Yıllık yağış (mm)").set_axis(b["yillik"].index.year))

with st.expander("Hangi bilgi nereden geldi?"):
    satirlar = [("Yağış, değişkenlik, kurak yıl", "NASA POWER (veri)")]
    for ad, k in [("Toprak dokusu", "doku"), ("Toprak derinliği", "derinlik"),
                  ("Organik madde", "organik"), ("Eğim", "egim")]:
        satirlar.append((ad, f"{t[k]} · " + ("çiftçi beyanı" if t[k] != "Bilmiyorum" else "varsayılan (etkisiz)")))
    satirlar.append(("Sulama", f"{t['sulama']} · çiftçi beyanı"))
    st.table(pd.DataFrame(satirlar, columns=["Bilgi", "Kaynak"]))

# ---- Rotasyon üretimi ----
st.subheader("Rotasyon karşılaştırması")
if len(havuz) < 2:
    st.warning("Alternatif üretmek için en az 2 ürün seç.")
    st.stop()

adaylar = []
for rot in itertools.product(havuz, repeat=4):
    if all(a != c for a, c in zip(rot, rot[1:])) and list(rot) != mevcut:
        sk, top, ned = skorla(list(rot), b, w, t)
        adaylar.append((top, list(rot)))
adaylar.sort(key=lambda x: x[0], reverse=True)

secilen = []
if adaylar:
    secilen.append(adaylar[0])
    for a in adaylar[1:]:
        if sorted(a[1]) != sorted(adaylar[0][1]):
            secilen.append(a); break
    if len(secilen) < 2 and len(adaylar) > 1:
        secilen.append(adaylar[1])

liste = [("Mevcut düzen", mevcut)] + [(f"Alternatif {i+1}", r) for i, (_, r) in enumerate(secilen)]
sonuc = {}
for col, (isim, rot) in zip(st.columns(len(liste)), liste):
    sk, top, ned = skorla(rot, b, w, t)
    _, top_k, _ = skorla(rot, b, w, t, kurak=True)
    sonuc[isim] = (top, top_k, ned)
    with col:
        st.markdown(f"**{isim}**")
        st.caption(" → ".join(rot))
        fark = "" if isim == "Mevcut düzen" else f"mevcuta göre {top - sonuc['Mevcut düzen'][0]:+d} · "
        st.metric("Toplam skor", top, delta=f"{fark}kurak yılda {top_k}", delta_color="off")
        for k, v in sk.items():
            st.progress(v / 100, text=f"{k}: {v}")

en_iyi = max(sonuc, key=lambda k: sonuc[k][0])
st.success(f"En yüksek skor: **{en_iyi}**")
st.markdown("**Neden?**")
for n_ in sonuc[en_iyi][2] or ["Belirgin bir artı veya risk kuralı tetiklenmedi."]:
    st.write("• " + n_)
st.caption("Skorlar karşılaştırma içindir; kesin verim veya kazanç tahmini değildir. Karar çiftçiye aittir.")

st.subheader("Kuraklık stres testi")
st.bar_chart(pd.DataFrame({"Normal yıl": {k: v[0] for k, v in sonuc.items()},
                           "Kurak yıl": {k: v[1] for k, v in sonuc.items()}}))