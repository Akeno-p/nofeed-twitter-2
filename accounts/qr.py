import io

import qrcode
import qrcode.image.svg


def svg_data(text):
    """QRコードを SVG 文字列で返す (Pillow 不要)。"""
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()
