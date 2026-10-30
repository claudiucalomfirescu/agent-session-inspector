"""Generate illustrated SVG portrait avatars for the VXC Motors personas.

Each avatar is built from a small spec (skin, hair, outfit, accessories), so the
set stays visually consistent and can be regenerated after edits:

    python company/tools/make_avatars.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "avatars"

SKIN = {
    "light": ("#f6d3b8", "#e3b593"),
    "ruddy": ("#f1c3a5", "#d99e80"),
    "olive": ("#e2b48d", "#c8966f"),
    "tan": ("#c98e62", "#ad744b"),
    "brown": ("#9c6644", "#82512f"),
    "dark": ("#6b4430", "#55331f"),
}

# id -> spec
PEOPLE = {
    "victor-hale": dict(skin="light", hair="receding", hair_color="#b8b8b8", outfit="suit",
                        outfit_color="#1f2a44", tie="#8b1e2d", bg="#dbe7f5", brows="#9a9a9a", glasses="#5a5a5a"),
    "maria-santos": dict(skin="olive", hair="long", hair_color="#3b2418", outfit="blazer",
                         outfit_color="#1f7a7a", bg="#fde7d6", earrings=True, lips="#b5525b"),
    "priya-nair": dict(skin="brown", hair="bun", hair_color="#1b1210", outfit="blazer",
                       outfit_color="#7a2443", bg="#efe3f7", glasses="#333", lips="#8e3b46"),
    "daniel-reed": dict(skin="light", hair="sidepart", hair_color="#6b4a2f", outfit="suit_open",
                        outfit_color="#3a3f47", bg="#e3efe2", stubble=True),
    "sofia-marin": dict(skin="light", hair="long", hair_color="#9a4a24", outfit="blazer",
                        outfit_color="#1c69d4", bg="#e2ecfb", lips="#c0606a"),
    "tom-becker": dict(skin="light", hair="quiff", hair_color="#d9b45a", outfit="suit",
                       outfit_color="#22305a", tie="#2a7de1", bg="#fff1cc"),
    "elena-popescu": dict(skin="light", hair="bob", hair_color="#4a3328", outfit="blazer",
                          outfit_color="#262626", bg="#f7e1e1", glasses="#7a1f2b", lips="#a8464f"),
    "james-okafor": dict(skin="dark", hair="buzz", hair_color="#1a1411", outfit="polo",
                         outfit_color="#4b5563", bg="#ddf1ec", beard="#1a1411"),
    "nina-kovac": dict(skin="light", hair="ponytail", hair_color="#e0c27a", outfit="blazer",
                       outfit_color="#4b5d8a", bg="#e8f4fb", lips="#c2717a"),
    "lucas-meyer": dict(skin="ruddy", hair="short", hair_color="#9e9e9e", outfit="overalls",
                        outfit_color="#1d3557", bg="#e6e6e6", beard="#8f8f8f"),
    "aisha-rahman": dict(skin="tan", hair="hijab", hair_color="#1f5f4a", outfit="overalls",
                         outfit_color="#1d3557", bg="#fdf0d5", glasses="#222", lips="#8e4a4a"),
    "mark-doyle": dict(skin="ruddy", hair="bald", hair_color="#c9c2b8", outfit="polo",
                       outfit_color="#7a3b12", bg="#f3e9dc", moustache="#b8b0a5"),
}


def hair_back(style, c):
    """Hair drawn behind the head (long hair, ponytail, hijab drape)."""
    if style == "long":
        return f'<path d="M58 92 Q56 40 100 38 Q144 40 142 92 L148 168 Q100 180 52 168 Z" fill="{c}"/>'
    if style == "bob":
        return f'<path d="M60 96 Q58 42 100 40 Q142 42 140 96 L142 128 Q100 136 58 128 Z" fill="{c}"/>'
    if style == "ponytail":
        return f'<path d="M132 70 Q160 90 150 140 Q144 120 132 104 Z" fill="{c}"/>'
    if style == "bun":
        return f'<circle cx="100" cy="36" r="16" fill="{c}"/>'
    if style == "hijab":
        return f'<path d="M50 104 Q48 34 100 32 Q152 34 150 104 L158 178 Q100 190 42 178 Z" fill="{c}"/>'
    return ""


def hair_front(style, c):
    """Hair drawn on top of the head."""
    if style in ("long", "bob", "ponytail", "bun"):
        return (f'<path d="M64 86 Q62 44 100 42 Q140 44 136 86 Q124 62 100 60 Q80 62 64 86 Z" fill="{c}"/>'
                f'<path d="M100 44 Q86 52 80 70" stroke="#00000022" stroke-width="2" fill="none"/>')
    if style == "short":
        return f'<path d="M66 80 Q64 46 100 44 Q136 46 134 80 Q126 60 100 58 Q74 60 66 80 Z" fill="{c}"/>'
    if style == "sidepart":
        return (f'<path d="M64 84 Q60 42 102 42 Q140 44 136 82 Q132 62 112 58 Q90 54 76 64 Q68 70 64 84 Z" fill="{c}"/>'
                f'<path d="M84 50 Q100 58 132 62" stroke="#00000030" stroke-width="2" fill="none"/>')
    if style == "quiff":
        return f'<path d="M66 82 Q62 50 86 40 Q100 30 122 38 Q140 48 134 82 Q128 62 104 58 Q78 60 66 82 Z" fill="{c}"/>'
    if style == "buzz":
        return f'<path d="M67 78 Q66 48 100 46 Q134 48 133 78 Q126 60 100 58 Q74 60 67 78 Z" fill="{c}" opacity="0.92"/>'
    if style == "receding":
        return (f'<path d="M64 92 Q62 66 72 58 L76 80 Z" fill="{c}"/>'
                f'<path d="M136 92 Q138 66 128 58 L124 80 Z" fill="{c}"/>'
                f'<path d="M80 52 Q100 44 120 52 Q100 50 80 52 Z" fill="{c}"/>')
    if style == "bald":
        return (f'<path d="M64 96 Q62 76 70 68 L74 92 Z" fill="{c}"/>'
                f'<path d="M136 96 Q138 76 130 68 L126 92 Z" fill="{c}"/>'
                '<ellipse cx="88" cy="58" rx="10" ry="4" fill="#ffffff40"/>')
    if style == "hijab":
        return ('<path d="M60 100 Q58 40 100 38 Q142 40 140 100 Q136 66 100 62 Q64 66 60 100 Z" fill="{c}"/>'
                .format(c=c))
    return ""


def outfit(kind, c, tie=None):
    shoulders = f'<path d="M30 200 Q34 150 74 140 L126 140 Q166 150 170 200 Z" fill="{c}"/>'
    if kind == "suit":
        return (shoulders +
                '<path d="M86 140 L100 172 L114 140 Z" fill="#ffffff"/>'
                f'<path d="M96 146 L100 142 L104 146 L102 176 L100 180 L98 176 Z" fill="{tie}"/>'
                f'<path d="M74 140 L100 186 L88 200 L66 146 Z" fill="#00000026"/>'
                f'<path d="M126 140 L100 186 L112 200 L134 146 Z" fill="#00000026"/>')
    if kind == "suit_open":
        return (shoulders +
                '<path d="M84 140 L100 176 L116 140 Z" fill="#eef3f8"/>'
                '<path d="M90 140 L100 152 L110 140" fill="none" stroke="#c8d2dd" stroke-width="2"/>'
                f'<path d="M74 140 L100 186 L88 200 L66 146 Z" fill="#00000026"/>'
                f'<path d="M126 140 L100 186 L112 200 L134 146 Z" fill="#00000026"/>')
    if kind == "blazer":
        return (shoulders +
                '<path d="M84 140 L100 170 L116 140 Z" fill="#f4f4f4"/>'
                f'<path d="M76 140 L100 180 L90 200 L68 148 Z" fill="#0000002a"/>'
                f'<path d="M124 140 L100 180 L110 200 L132 148 Z" fill="#0000002a"/>')
    if kind == "polo":
        return (shoulders +
                f'<path d="M84 140 L100 162 L116 140 L110 138 L100 150 L90 138 Z" fill="#ffffff55"/>'
                '<rect x="98" y="150" width="4" height="22" fill="#00000022"/>'
                '<text x="134" y="176" font-family="Arial" font-size="9" font-weight="700" fill="#ffffffcc">VXC</text>')
    if kind == "overalls":
        return (shoulders +
                '<path d="M86 140 L100 160 L114 140 Z" fill="#9aa5b1"/>'
                '<rect x="80" y="160" width="4" height="40" fill="#ffffff33"/>'
                '<rect x="116" y="160" width="4" height="40" fill="#ffffff33"/>'
                '<rect x="128" y="166" width="22" height="12" rx="2" fill="#ffffffdd"/>'
                '<text x="131" y="175.5" font-family="Arial" font-size="8" font-weight="700" fill="#1d3557">VXC</text>')
    return shoulders


def face(spec):
    skin, shade = SKIN[spec["skin"]]
    brows = spec.get("brows") or spec["hair_color"]
    if spec["hair"] == "hijab":
        brows = "#2a1a12"
    parts = [f'<rect x="90" y="118" width="20" height="26" fill="{shade}"/>']  # neck
    if spec["hair"] != "hijab":  # ears
        parts += [f'<ellipse cx="64" cy="98" rx="7" ry="11" fill="{shade}"/>',
                  f'<ellipse cx="136" cy="98" rx="7" ry="11" fill="{shade}"/>']
    parts += [
        f'<ellipse cx="100" cy="92" rx="36" ry="42" fill="{skin}"/>',     # head
        f'<path d="M78 82 Q86 77 94 81" stroke="{brows}" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
        f'<path d="M106 81 Q114 77 122 82" stroke="{brows}" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
        '<ellipse cx="86" cy="93" rx="4" ry="4.6" fill="#2b2b2b"/>',
        '<ellipse cx="114" cy="93" rx="4" ry="4.6" fill="#2b2b2b"/>',
        '<circle cx="87.4" cy="91.6" r="1.3" fill="#fff"/>',
        '<circle cx="115.4" cy="91.6" r="1.3" fill="#fff"/>',
        f'<path d="M100 96 Q96 108 100 110 Q103 110 104 108" stroke="{shade}" stroke-width="2.5" fill="none" stroke-linecap="round"/>',
        f'<ellipse cx="78" cy="106" rx="7" ry="4" fill="#e0707033"/>',
        f'<ellipse cx="122" cy="106" rx="7" ry="4" fill="#e0707033"/>',
    ]
    if spec.get("stubble"):
        parts.append(f'<path d="M70 104 Q72 132 100 134 Q128 132 130 104 Q126 126 100 128 Q74 126 70 104 Z" fill="#6b4a2f40"/>')
    if spec.get("beard"):
        parts.append(f'<path d="M66 96 Q66 138 100 138 Q134 138 134 96 Q130 112 120 114 Q110 110 100 112 Q90 110 80 114 Q70 112 66 96 Z" fill="{spec["beard"]}"/>')
    lips = spec.get("lips", "#9c4a3c")
    parts.append(f'<path d="M89 117 Q100 125 111 117" stroke="{lips}" stroke-width="3" fill="none" stroke-linecap="round"/>')
    if spec.get("moustache"):
        parts.append(f'<path d="M86 114 Q100 106 114 114 Q100 112 86 114 Z" fill="{spec["moustache"]}" stroke="{spec["moustache"]}" stroke-width="3"/>')
    if spec.get("glasses"):
        g = spec["glasses"]
        parts.append(f'<g fill="none" stroke="{g}" stroke-width="2.5"><rect x="74" y="85" width="22" height="16" rx="5"/>'
                     f'<rect x="104" y="85" width="22" height="16" rx="5"/><path d="M96 92 L104 92"/>'
                     f'<path d="M74 90 L66 88"/><path d="M126 90 L134 88"/></g>')
    if spec.get("earrings"):
        parts.append('<circle cx="64" cy="112" r="2.6" fill="#e8c35a"/><circle cx="136" cy="112" r="2.6" fill="#e8c35a"/>')
    return "".join(parts)


def avatar(pid, spec):
    hair = spec["hair"]
    c = spec["hair_color"]
    body = [
        f'<circle cx="100" cy="100" r="100" fill="{spec["bg"]}"/>',
        hair_back(hair, c),
        outfit(spec["outfit"], spec["outfit_color"], spec.get("tie")),
        face(spec),
        hair_front(hair, c),
    ]
    if hair == "hijab":  # hijab frames the face; redraw the drape under the chin
        body.append(f'<path d="M64 112 Q70 146 100 150 Q130 146 136 112 Q138 150 100 158 Q62 150 64 112 Z" fill="{c}"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200" '
        f'role="img" aria-label="Portrait of {pid}">'
        '<defs><clipPath id="c"><circle cx="100" cy="100" r="100"/></clipPath></defs>'
        f'<g clip-path="url(#c)">{"".join(body)}</g></svg>\n'
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for pid, spec in PEOPLE.items():
        (OUT / f"{pid}.svg").write_text(avatar(pid, spec))
    print(f"wrote {len(PEOPLE)} avatars to {OUT}")


if __name__ == "__main__":
    main()
