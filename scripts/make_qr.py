#!/usr/bin/env python3
"""17卓分のQRコードを一括生成する。

使い方:
    pip install qrcode pillow
    python3 scripts/make_qr.py https://<ユーザー名>.github.io/<リポジトリ名>/

出力: qr/QR_A.png 〜 qr/QR_Q.png（印刷用・約1200px、誤り訂正レベルQ）
"""
import sys
from pathlib import Path

try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_Q
except ImportError:
    sys.exit("qrcode ライブラリが必要です: pip install qrcode pillow")

TABLE_IDS = list("ABCDEFGHIJKLMNOPQ")
TARGET_PX = 1200  # 印刷用（4cm角で約750dpi、十分な解像度）


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("使い方: python3 scripts/make_qr.py <公開URL>\n"
                 "例:     python3 scripts/make_qr.py https://example.github.io/wedding/")
    base = sys.argv[1]
    sep = "&" if "?" in base else "?"

    out_dir = Path(__file__).resolve().parent.parent / "qr"
    out_dir.mkdir(exist_ok=True)

    for tid in TABLE_IDS:
        url = f"{base}{sep}t={tid}"
        qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        modules = qr.modules_count + qr.border * 2
        qr.box_size = max(1, -(-TARGET_PX // modules))  # 切り上げでTARGET_PX以上に
        img = qr.make_image(fill_color="#3E4C6D", back_color="white")
        path = out_dir / f"QR_{tid}.png"
        img.save(path)
        print(f"{path.name}  ({img.size[0]}px)  →  {url}")

    print(f"\n{len(TABLE_IDS)}枚を {out_dir}/ に出力しました")


if __name__ == "__main__":
    main()
