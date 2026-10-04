import base64

import streamlit as st

from agent import ask_agent

st.set_page_config(page_title="Agent NBA", page_icon="🏀", layout="centered")


def basketball_court_svg():
    """Dessine un terrain de basket (parquet et lignes) vu depuis la ligne de fond, en perspective."""
    import math
    W, H = 1600, 1000
    f, d, h, horizon, cx = 1000, 3.0, 6.5, 40, W / 2

    def p(x, z):
        s = f / (z + d)
        return cx + x * s, horizon + h * s

    def poly(points, width=0.06, close=False):
        pts = [p(x, z) for x, z in points]
        z_mean = sum(z for _, z in points) / len(points)
        w = max(1.2, width * f / (z_mean + d))
        tag = "polygon" if close else "polyline"
        coords = " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)
        return f'<{tag} points="{coords}" fill="none" stroke-width="{w:.1f}"/>'

    L, HW = 28.65, 7.62          # longueur et demi-largeur du terrain (mètres)
    mid = L / 2
    lines = [poly([(-HW, 0), (HW, 0), (HW, L), (-HW, L)], close=True),
             poly([(-HW, mid), (HW, mid)])]
    circle = [(1.8 * math.cos(a / 40 * 2 * math.pi), mid + 1.8 * math.sin(a / 40 * 2 * math.pi)) for a in range(41)]
    lines.append(poly(circle))
    for base, sign in ((0, 1), (L, -1)):
        hoop = base + sign * 1.6
        key = [(-2.44, base), (-2.44, base + sign * 5.79), (2.44, base + sign * 5.79), (2.44, base)]
        lines.append(poly(key))
        ft = [(1.8 * math.cos(a / 20 * math.pi), base + sign * 5.79 + sign * 1.8 * math.sin(a / 20 * math.pi)) for a in range(21)]
        lines.append(poly(ft))
        # ligne à 3 points : corners droits puis arc de 7,24 m autour du panier
        corner = 6.71
        a0 = math.asin(corner / 7.24)
        arc = [(7.24 * math.sin(t), hoop + sign * 7.24 * math.cos(t))
               for t in [-a0 + i * (2 * a0) / 40 for i in range(41)]]
        z_corner = arc[0][1]
        lines.append(poly([(-corner, base)] + arc + [(corner, base)]))
    # planches du parquet
    boards = "".join(
        f'<line x1="{p(x, 0)[0]:.1f}" y1="{p(x, 0)[1]:.1f}" x2="{p(x, 60)[0]:.1f}" y2="{p(x, 60)[1]:.1f}" '
        f'stroke="rgba(90,45,15,{0.10 + 0.08 * ((i * 7) % 3)})" stroke-width="2"/>'
        for i, x in enumerate([k * 0.35 for k in range(-80, 81)]))
    paint = " ".join(f"{a:.1f},{b:.1f}" for a, b in [p(-2.44, 0), p(2.44, 0), p(2.44, 5.79), p(-2.44, 5.79)])
    paint2 = " ".join(f"{a:.1f},{b:.1f}" for a, b in [p(-2.44, L), p(2.44, L), p(2.44, L - 5.79), p(-2.44, L - 5.79)])

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="wood" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#B9773F"/><stop offset="1" stop-color="#D9A066"/></linearGradient>
    <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.012 0.6" numOctaves="2" seed="7"/>
      <feColorMatrix values="0 0 0 0 0.35  0 0 0 0 0.18  0 0 0 0 0.06  0 0 0 0.35 0"/></filter>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#wood)"/>
  <rect width="{W}" height="{H}" filter="url(#grain)"/>
  {boards}
  <rect width="{W}" height="{p(0, L + 3.5)[1]:.0f}" fill="#101A2C"/>
  <rect y="{p(0, L + 3.5)[1] - 5:.0f}" width="{W}" height="5" fill="#C8102E" fill-opacity="0.85"/>
  <polygon points="{paint}" fill="rgba(22,58,128,0.78)"/>
  <polygon points="{paint2}" fill="rgba(22,58,128,0.78)"/>
  <g stroke="#FFFFFF" stroke-opacity="0.9" stroke-linejoin="round">{"".join(lines)}</g>
</svg>'''
    return base64.b64encode(svg.encode()).decode()


st.markdown(f"""
<style>
.stApp {{
    background:
        radial-gradient(ellipse 70% 60% at 50% 55%, transparent 40%, rgba(10,6,3,0.55) 100%),
        url("data:image/svg+xml;base64,{basketball_court_svg()}") center / cover no-repeat fixed;
}}
header[data-testid="stHeader"], div[data-testid="stBottom"], div[data-testid="stBottom"] > div {{
    background: transparent;
}}
.block-container {{ max-width: 720px; }}
.spacer {{ height: 40vh; }}

/* Barre de question */
div[data-testid="stChatInput"] > div {{
    background: rgba(28, 14, 9, 0.72);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: 16px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
}}
div[data-testid="stChatInput"] > div:focus-within {{ border-color: rgba(255, 255, 255, 0.75); }}
div[data-testid="stChatInput"] textarea {{ color: #FFFFFF; font-size: 1.08rem; }}
div[data-testid="stChatInput"] textarea::placeholder {{ color: rgba(255, 255, 255, 0.65); }}

/* Messages lisibles sur le parquet */
div[data-testid="stChatMessage"] {{
    background: rgba(28, 14, 9, 0.72);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 14px;
    padding: 0.9rem 1rem;
}}
div[data-testid="stChatMessage"] p {{ color: #FFFFFF; }}
</style>
""", unsafe_allow_html=True)

if "history" not in st.session_state:
    st.session_state.history = []

AVATARS = {"user": ":material/person:", "assistant": ":material/sports_basketball:"}

if not st.session_state.history:
    # Accueil : uniquement la barre, au milieu de l'écran
    st.markdown('<div class="spacer"></div>', unsafe_allow_html=True)
    with st.container():
        question = st.chat_input("Pose ta question sur la NBA...")
else:
    for q, a in st.session_state.history:
        with st.chat_message("user", avatar=AVATARS["user"]):
            st.write(q)
        with st.chat_message("assistant", avatar=AVATARS["assistant"]):
            st.write(a)
    question = st.chat_input("Pose une autre question...")

if question:
    with st.chat_message("user", avatar=AVATARS["user"]):
        st.write(question)
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        with st.spinner("Recherche en cours..."):
            try:
                answer, _ = ask_agent(question, st.session_state.history)
            except Exception as e:
                answer = f"La requête a échoué : {e}"
        st.write(answer)
    st.session_state.history.append((question, answer))
    st.rerun()
