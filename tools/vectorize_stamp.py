from pathlib import Path
from PIL import Image, ImageFilter, ImageDraw
import math


SOURCE = Path(r"C:/Users/11847/Desktop/WhatsApp Image 2026-06-29 at 18.39.17.jpeg")
OUTPUT = Path(r"D:/ai-novel-video-generator/assets/stamp/oval_stamp_face_mirrored.dxf")
PREVIEW = Path(r"D:/ai-novel-video-generator/assets/stamp/oval_stamp_face_mirrored_preview.png")


def rdp(points, epsilon):
    if len(points) < 3:
        return points
    x1, y1 = points[0]
    x2, y2 = points[-1]
    dx, dy = x2 - x1, y2 - y1
    denom = math.hypot(dx, dy)
    max_dist, index = 0.0, 0
    for i, (x, y) in enumerate(points[1:-1], 1):
        if denom == 0:
            dist = math.hypot(x - x1, y - y1)
        else:
            dist = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / denom
        if dist > max_dist:
            max_dist, index = dist, i
    if max_dist > epsilon:
        left = rdp(points[: index + 1], epsilon)
        right = rdp(points[index:], epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


def polygon_area(points):
    return 0.5 * sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )


def trace_edges(mask, width, height):
    edges = {}

    def add(a, b):
        edges.setdefault(a, []).append(b)

    for y in range(height):
        row = y * width
        for x in range(width):
            if not mask[row + x]:
                continue
            if y == 0 or not mask[(y - 1) * width + x]:
                add((x, y), (x + 1, y))
            if x == width - 1 or not mask[row + x + 1]:
                add((x + 1, y), (x + 1, y + 1))
            if y == height - 1 or not mask[(y + 1) * width + x]:
                add((x + 1, y + 1), (x, y + 1))
            if x == 0 or not mask[row + x - 1]:
                add((x, y + 1), (x, y))

    contours = []
    while edges:
        start = next(iter(edges))
        current = start
        contour = [start]
        for _ in range(width * height * 2):
            candidates = edges.get(current)
            if not candidates:
                break
            nxt = candidates.pop()
            if not candidates:
                del edges[current]
            current = nxt
            if current == start:
                break
            contour.append(current)
        if current == start and len(contour) >= 4:
            contours.append(contour)
    return contours


def write_dxf(contours, path):
    lines = ["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
             "0", "SECTION", "2", "ENTITIES"]
    for contour in contours:
        lines += ["0", "LWPOLYLINE", "8", "STAMP_FACE", "90", str(len(contour)), "70", "1"]
        for x, y in contour:
            lines += ["10", f"{x:.4f}", "20", f"{y:.4f}"]
    lines += ["0", "ENDSEC", "0", "EOF"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def write_preview(contours, path):
    canvas = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(canvas)
    scale = 20
    ox, oy = canvas.width // 2, canvas.height // 2
    for contour in contours:
        points = [(ox + x * scale, oy - y * scale) for x, y in contour]
        draw.line(points + [points[0]], fill=(0, 40, 150), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def main():
    image = Image.open(SOURCE).convert("RGB")
    image.thumbnail((820, 620), Image.Resampling.LANCZOS)
    pixels = list(image.getdata())
    blue = [b > 70 and b > r * 1.25 and b > g * 1.08 for r, g, b in pixels]

    xs, ys = [], []
    for i, value in enumerate(blue):
        if value:
            xs.append(i % image.width)
            ys.append(i // image.width)
    if not xs:
        raise RuntimeError("No blue artwork detected")

    margin = 3
    left, right = max(0, min(xs) - margin), min(image.width - 1, max(xs) + margin)
    top, bottom = max(0, min(ys) - margin), min(image.height - 1, max(ys) + margin)
    bw = Image.new("L", image.size, 0)
    bw.putdata([255 if value else 0 for value in blue])
    bw = bw.crop((left, top, right + 1, bottom + 1))
    bw = bw.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    bw = bw.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    width, height = bw.size
    mask = [value >= 128 for value in bw.getdata()]
    raw = trace_edges(mask, width, height)

    target_w, target_h = 43.6, 28.6
    scale = min(target_w / width, target_h / height)
    cx, cy = width / 2, height / 2
    cleaned = []
    for contour in raw:
        if abs(polygon_area(contour)) < 5:
            continue
        closed = contour + [contour[0]]
        simple = rdp(closed, 0.7)
        if simple[0] == simple[-1]:
            simple = simple[:-1]
        if len(simple) < 3:
            continue
        converted = [((x - cx) * scale, (cy - y) * scale) for x, y in simple]
        cleaned.append(converted)

    write_dxf(cleaned, OUTPUT)
    write_preview(cleaned, PREVIEW)
    print(f"wrote {OUTPUT} with {len(cleaned)} closed contours; scale={scale:.6f} mm/pixel")


if __name__ == "__main__":
    main()
