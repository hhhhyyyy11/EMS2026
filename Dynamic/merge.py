import os
from fpdf import FPDF
from PIL import Image
import io
import tempfile  # ★ 追加

# --- 設定項目 ---
image_folder = 'png_DP' 
output_pdf_name = 'Optimization_Report_DP.pdf'
IMAGES_PER_PAGE = 8
COLS = 2
ROWS = 4
PAGE_WIDTH = 210
PAGE_HEIGHT = 297
MARGIN = 17
IMG_WIDTH = (PAGE_WIDTH - MARGIN * (COLS + 1)) / COLS
IMG_HEIGHT = (PAGE_HEIGHT - MARGIN * (ROWS + 1)) / ROWS

# --- ここからスクリプト本体 ---

print("PDFレポートの作成を開始します...")

# グラフをPDFに含める順番を定義
ordered_variables = [
    'gP1', 'gP2', 'dA1', 'dA2', 'dB1', 
    'dB2', 'dC1', 'dC2', 'sBY', 'xFC1', 
    'xFC2', 'xFD1', 'xFD2', 'bF', 'bF_actual', 
    's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual', 'solar_radiation', 'pBY',
    # 'dD1', 'dD'
]

# 存在する画像ファイルのパスリストを作成
image_paths = [os.path.join(image_folder, f"{var}.png") for var in ordered_variables]
existing_image_paths = [path for path in image_paths if os.path.exists(path)]

if not existing_image_paths:
    print(f"エラー: フォルダ '{image_folder}' に画像ファイルが見つかりません。")
else:
    try:
        # 画像をメモリバッファにプリロード
        print("画像をメモリバッファにプリロードしています...")
        image_buffers = []
        for path in existing_image_paths:
            img = Image.open(path)
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            image_buffers.append({'buffer': buffer, 'pil_img': img})
        print("プリロードが完了しました。")
        
        pdf = FPDF('P', 'mm', 'A4')

        for i, data in enumerate(image_buffers):
            pos_index = i % IMAGES_PER_PAGE
            
            if pos_index == 0:
                pdf.add_page()
                pdf.set_font('Arial', 'B', 16)
                page_num = i // IMAGES_PER_PAGE + 1
                pdf.cell(0, 10, f'Optimization Results - Page {page_num}', 0, 1, 'C')
            
            row = pos_index // COLS
            col = pos_index % COLS
            
            x = MARGIN + col * (IMG_WIDTH + MARGIN)
            y = MARGIN + 15 + row * (IMG_HEIGHT + MARGIN)
            
            pil_image = data['pil_img']
            img_aspect = pil_image.width / pil_image.height
            box_aspect = IMG_WIDTH / IMG_HEIGHT
            
            if img_aspect > box_aspect:
                w = IMG_WIDTH
                h = w / img_aspect
            else:
                h = IMG_HEIGHT
                w = h * img_aspect
            
            x_offset = (IMG_WIDTH - w) / 2
            y_offset = (IMG_HEIGHT - h) / 2
            
            # --- 修正: 一時ファイルに保存してからpdf.imageに渡す ---
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmpfile:
                tmpfile.write(data['buffer'].getvalue())
                tmpfile.flush()
                pdf.image(tmpfile.name, x=x + x_offset, y=y + y_offset, w=w, h=h)
            
            pil_image.close()

        pdf.output(output_pdf_name)
        print(f"成功: {len(existing_image_paths)}個のPNGファイルが '{output_pdf_name}' に統合されました。")

    except Exception as e:
        print(f"エラーが発生しました: {e}")
