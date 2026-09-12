"""PWA 아이콘 PNG 생성기 (`public/icons/`).

아이콘을 손으로 만든 바이너리로 두면 크기나 색을 바꿀 때 원본이 없다. 여기서
생성하고 결과를 커밋한다. 빌드 파이프라인에 넣지 않는다 --- 아이콘은 거의 바뀌지
않고, 빌드가 Pillow에 의존하게 만들 이유가 없다.

    python3 scripts/generate-icons.py

마크는 "문장 안에서 표현 하나가 subtle하게 강조된 상태"다(03_UI_UX_SPEC.md).
색은 reference mockup(`spec/reference/ui/core-learning-mockup.html`)의 --accent와 --bg.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (79, 109, 245, 255)  # --accent #4f6df5
SURFACE = (255, 255, 255, 255)
# accent 위에 흰색 43%를 **미리 섞은** 값. ImageDraw는 알파를 합성하지 않고
# 픽셀을 덮어쓰므로, 반투명 흰색을 그대로 칠하면 배경까지 뚫린다.
SURFACE_SOFT = (155, 172, 249, 255)
OUT = Path(__file__).resolve().parent.parent / "public" / "icons"


def draw_mark(image: Image.Image, scale: float) -> None:
    """가운데 정렬된 마크. `scale`은 아이콘 변 대비 마크 폭의 비율."""
    size = image.size[0]
    draw = ImageDraw.Draw(image)
    width = size * scale
    left = (size - width) / 2
    bar_height = width * 0.115
    gap = width * 0.105
    total = bar_height * 3 + gap * 2
    top = (size - total) / 2
    radius = bar_height / 2

    # 1행/3행은 평범한 문장, 2행이 강조된 학습 대상 span이다.
    rows = [
        (width, SURFACE_SOFT),
        (width * 0.72, SURFACE),
        (width * 0.86, SURFACE_SOFT),
    ]
    for index, (row_width, color) in enumerate(rows):
        y = top + index * (bar_height + gap)
        draw.rounded_rectangle(
            (left, y, left + row_width, y + bar_height), radius=radius, fill=color
        )


def build(size: int, *, maskable: bool) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if maskable:
        # full-bleed. 플랫폼이 어떤 모양으로 잘라도 배경이 남는다.
        draw.rectangle((0, 0, size, size), fill=ACCENT)
        # 마크는 안쪽 80% safe zone 안에 둔다.
        draw_mark(image, scale=0.46)
    else:
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size * 0.22, fill=ACCENT)
        draw_mark(image, scale=0.56)
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build(192, maskable=False).save(OUT / "icon-192.png")
    build(512, maskable=False).save(OUT / "icon-512.png")
    build(512, maskable=True).save(OUT / "icon-512-maskable.png")


if __name__ == "__main__":
    main()
