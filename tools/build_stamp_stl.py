from pathlib import Path
from PIL import Image, ImageFilter
import struct
import math

SOURCE = Path(r"C:/Users/11847/Desktop/WhatsApp Image 2026-06-29 at 18.39.17.jpeg")
OUTPUT = Path(r"D:/ai-novel-video-generator/assets/stamp/oval_stamp_head_mesh.stl")

DX = DY = 0.30
DZ = 0.25
NX, NY = 150, 100
BASE_LAYERS = 20
ART_LAYERS = 4


def prepare_art():
    im = Image.open(SOURCE).convert("RGB")
    pix = list(im.getdata())
    mask = [255 if b > 70 and b > r * 1.25 and b > g * 1.08 else 0 for r, g, b in pix]
    bw = Image.new("L", im.size, 0)
    bw.putdata(mask)
    box = bw.getbbox()
    if not box:
        raise RuntimeError("No blue artwork found")
    bw = bw.crop(box)
    bw.thumbnail((146, 96), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (NX, NY), 0)
    canvas.paste(bw, ((NX - bw.width) // 2, (NY - bw.height) // 2))
    canvas = canvas.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    canvas = canvas.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    return [v >= 96 for v in canvas.getdata()]


def occupied(x, y, z, art):
    if x < 0 or y < 0 or z < 0 or x >= NX or y >= NY or z >= BASE_LAYERS + ART_LAYERS:
        return False
    px = (x + 0.5) * DX - 22.5
    py = (y + 0.5) * DY - 15.0
    inside_base = (px / 22.5) ** 2 + (py / 15.0) ** 2 <= 1.0
    if not inside_base:
        return False
    if z < BASE_LAYERS:
        return True
    return art[y * NX + x]


def normal(a, b, c):
    ux, uy, uz = (b[i] - a[i] for i in range(3))
    vx, vy, vz = (c[i] - a[i] for i in range(3))
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / length, ny / length, nz / length


def add_quad(tris, a, b, c, d):
    tris.append((a, b, c))
    tris.append((a, c, d))


def build():
    art = prepare_art()
    tris = []
    faces = [
        ((-1, 0, 0), lambda x, y, z: [(x, y, z), (x, y, z + 1), (x, y + 1, z + 1), (x, y + 1, z)]),
        ((1, 0, 0), lambda x, y, z: [(x + 1, y, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x + 1, y, z + 1)]),
        ((0, -1, 0), lambda x, y, z: [(x, y, z), (x + 1, y, z), (x + 1, y, z + 1), (x, y, z + 1)]),
        ((0, 1, 0), lambda x, y, z: [(x, y + 1, z), (x, y + 1, z + 1), (x + 1, y + 1, z + 1), (x + 1, y + 1, z)]),
        ((0, 0, -1), lambda x, y, z: [(x, y, z), (x, y + 1, z), (x + 1, y + 1, z), (x + 1, y, z)]),
        ((0, 0, 1), lambda x, y, z: [(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)]),
    ]
    for z in range(BASE_LAYERS + ART_LAYERS):
        for y in range(NY):
            for x in range(NX):
                if not occupied(x, y, z, art):
                    continue
                for (ox, oy, oz), corners in faces:
                    if occupied(x + ox, y + oy, z + oz, art):
                        continue
                    pts = [((cx * DX) - 22.5, (cy * DY) - 15.0, cz * DZ) for cx, cy, cz in corners(x, y, z)]
                    add_quad(tris, *pts)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("wb") as f:
        f.write(b"Oval mirrored stamp head".ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for tri in tris:
            n = normal(*tri)
            f.write(struct.pack("<12fH", *(n + tri[0] + tri[1] + tri[2]), 0))
    print(f"wrote {OUTPUT} with {len(tris)} triangles")


if __name__ == "__main__":
    build()
