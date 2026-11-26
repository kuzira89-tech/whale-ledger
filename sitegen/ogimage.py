"""공유 미리보기 그림(1200×630 PNG). 표준 라이브러리만 쓴다.

X·LINE·카카오톡에 링크를 붙였을 때 뜨는 그림이다. 글꼴 파일을 읽을 수 없어서
5×7 점 글꼴을 직접 찍는다. 그래서 글자는 영문 대문자와 숫자, 기호 몇 가지뿐이고,
한글·일본어 제목은 페이지의 og:title이 맡는다.
"""
from __future__ import annotations

import struct
import zlib

W, H = 1200, 630
PAD = 48
MAP_X, MAP_Y, MAP_W, MAP_H = PAD, 172, W - 2 * PAD, 384

BG = (13, 17, 23)
TEXT = (232, 236, 242)
MUTED = (155, 166, 181)
# 칸의 (바탕, 글자). sitegen/build.py의 CSS와 같은 색이다.
COLORS = {
    "s-up": ((255, 138, 76), (26, 14, 6)),
    "s-up2": ((107, 58, 30), (255, 216, 194)),
    "s-dn": ((42, 85, 189), (255, 255, 255)),
    "s-dn2": ((31, 58, 122), (220, 230, 255)),
    "s-nt": ((35, 43, 55), (232, 236, 242)),
    "etc": ((26, 33, 43), (174, 184, 198)),
}

_GLYPHS = """
A .###. #...# #...# ##### #...# #...# #...#
B ####. #...# #...# ####. #...# #...# ####.
C .###. #...# #.... #.... #.... #...# .###.
D ####. #...# #...# #...# #...# #...# ####.
E ##### #.... #.... ####. #.... #.... #####
F ##### #.... #.... ####. #.... #.... #....
G .###. #...# #.... #.### #...# #...# .###.
H #...# #...# #...# ##### #...# #...# #...#
I .###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.
J ..### ...#. ...#. ...#. ...#. #..#. .##..
K #...# #..#. #.#.. ##... #.#.. #..#. #...#
L #.... #.... #.... #.... #.... #.... #####
M #...# ##.## #.#.# #.#.# #...# #...# #...#
N #...# ##..# #.#.# #..## #...# #...# #...#
O .###. #...# #...# #...# #...# #...# .###.
P ####. #...# #...# ####. #.... #.... #....
Q .###. #...# #...# #...# #.#.# #..#. .##.#
R ####. #...# #...# ####. #.#.. #..#. #...#
S .#### #.... #.... .###. ....# ....# ####.
T ##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..
U #...# #...# #...# #...# #...# #...# .###.
V #...# #...# #...# #...# #...# .#.#. ..#..
W #...# #...# #...# #.#.# #.#.# ##.## #...#
X #...# #...# .#.#. ..#.. .#.#. #...# #...#
Y #...# #...# .#.#. ..#.. ..#.. ..#.. ..#..
Z ##### ....# ...#. ..#.. .#... #.... #####
0 .###. #...# #..## #.#.# ##..# #...# .###.
1 ..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.
2 .###. #...# ....# ...#. ..#.. .#... #####
3 ####. ....# ....# .###. ....# ....# ####.
4 ...#. ..##. .#.#. #..#. ##### ...#. ...#.
5 ##### #.... ####. ....# ....# #...# .###.
6 .###. #.... #.... ####. #...# #...# .###.
7 ##### ....# ...#. ..#.. .#... .#... .#...
8 .###. #...# #...# .###. #...# #...# .###.
9 .###. #...# #...# .#### ....# ....# .###.
. ..... ..... ..... ..... ..... .##.. .##..
, ..... ..... ..... ..... .##.. ..#.. .#...
% ##..# ##.#. ...#. ..#.. .#... .#.## #..##
$ ..#.. .#### #.#.. .###. ..#.# ####. ..#..
+ ..... ..#.. ..#.. ##### ..#.. ..#.. .....
- ..... ..... ..... ##### ..... ..... .....
: ..... .##.. .##.. ..... .##.. .##.. .....
/ ....# ....# ...#. ..#.. .#... #.... #....
& .##.. #..#. #.#.. .#... #.#.# #..#. .##.#
( ...#. ..#.. .#... .#... .#... ..#.. ...#.
) .#... ..#.. ...#. ...#. ...#. ..#.. .#...
' ..#.. ..#.. ..... ..... ..... ..... .....
"""
FONT = {ln.split()[0]: ln.split()[1:] for ln in _GLYPHS.strip().splitlines()}
FONT[" "] = ["....."] * 7
FONT["·"] = [".....", ".....", ".....", ".##..", ".##..", ".....", "....."]


def ascii_label(s: str) -> str:
    """점 글꼴로 찍을 수 있는 글자만 남긴다."""
    return "".join(c for c in s.upper() if c in FONT).strip()


def text_width(s: str, scale: int) -> int:
    return max(0, (len(s) * 6 - 1) * scale)


def fit_scale(s: str, max_w: float, hi: int, lo: int = 1) -> int:
    """폭 max_w 안에 들어가는 가장 큰 배율. 가장 작은 배율로도 넘치면 0."""
    for scale in range(hi, lo - 1, -1):
        if text_width(s, scale) <= max_w:
            return scale
    return 0


class Canvas:
    def __init__(self, w: int = W, h: int = H, bg: tuple = BG):
        self.w, self.h = w, h
        self.rows = [bytearray(bytes(bg) * w) for _ in range(h)]

    def rect(self, x: float, y: float, w: float, h: float, color: tuple) -> None:
        x0, y0 = max(0, round(x)), max(0, round(y))
        x1, y1 = min(self.w, round(x + w)), min(self.h, round(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        fill = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            self.rows[yy][x0 * 3:x1 * 3] = fill

    def text(self, x: float, y: float, s: str, scale: int, color: tuple) -> None:
        cx = round(x)
        for ch in s:
            for gy, line in enumerate(FONT.get(ch, FONT[" "])):
                for gx, bit in enumerate(line):
                    if bit == "#":
                        self.rect(cx + gx * scale, y + gy * scale, scale, scale, color)
            cx += 6 * scale

    def png(self) -> bytes:
        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        raw = b"".join(b"\x00" + bytes(r) for r in self.rows)
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


def card(title: str, sub: str, tiles: list[tuple], legend: bool = True) -> bytes:
    """미리보기 그림 한 장.

    tiles는 (이름, 아랫줄, 색 이름, x, y, w, h)이고 좌표는 MAP_W × MAP_H 안의 값이다.
    """
    c = Canvas()
    title, sub = ascii_label(title), ascii_label(sub)
    ts = fit_scale(title, W - 2 * PAD, 7, 3) or 3
    c.text(PAD, 44, title, ts, TEXT)
    c.text(PAD, 44 + 7 * ts + 20, sub, 3, MUTED)

    for label, under, cls, x, y, w, h in tiles:
        bg, fg = COLORS.get(cls, COLORS["s-nt"])
        c.rect(MAP_X + x + 2, MAP_Y + y + 2, w - 4, h - 4, bg)
        label, under = ascii_label(label), ascii_label(under)
        inner_w, inner_h = w - 4 - 20, h - 4 - 16
        hi = 7 if w * h >= 60000 else 5 if w * h >= 22000 else 4 if w * h >= 9000 else 3
        s1 = fit_scale(label, inner_w, hi, 2)
        if not label or not s1 or 7 * s1 > inner_h:
            continue
        tx, ty = MAP_X + x + 2 + 10, MAP_Y + y + 2 + 8
        c.text(tx, ty, label, s1, fg)
        s2 = fit_scale(under, inner_w, max(2, s1 - 2), 2)
        if under and s2 and 7 * s1 + 8 + 7 * s2 <= inner_h:
            c.text(tx, ty + 7 * s1 + 8, under, s2, fg)

    fy = MAP_Y + MAP_H + 24
    if legend:
        lx = PAD
        for cls, word in (("s-up", "ADDED"), ("s-dn", "REDUCED"), ("s-nt", "UNCHANGED")):
            c.rect(lx, fy + 2, 16, 16, COLORS[cls][0])
            c.text(lx + 24, fy + 3, word, 2, MUTED)
            lx += 24 + text_width(word, 2) + 28
    site = "WHALEPORTFOLIO.COM"
    c.text(W - PAD - text_width(site, 3), fy, site, 3, TEXT)
    return c.png()
